import ipaddress
import mimetypes
import os
import re
import socket
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from bs4 import BeautifulSoup
from docx import Document as DocxDocument
from fastapi import HTTPException, UploadFile
from pypdf import PdfReader
from sqlalchemy.orm import Session

from database.connection import BACKEND_DIR, SessionLocal
from database.models import Bot, Chunk, Document
from services.chunking_service import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    chunk_text_with_metadata,
    count_tokens,
    normalize_text,
)
from services.embedding_service import generate_embedding

UPLOAD_DIR = Path(os.getenv("KNOWLEDGE_UPLOAD_DIR", BACKEND_DIR / "storage" / "knowledge")).resolve()
MAX_UPLOAD_BYTES = int(os.getenv("KNOWLEDGE_MAX_UPLOAD_MB", "20")) * 1024 * 1024
SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".docx"}
SUPPORTED_MIME_TYPES = {
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/octet-stream": None,
}
REQUEST_HEADERS = {
    "User-Agent": (
        "ChatbotSaaSKnowledgeBot/4.0 "
        "(public website ingestion; +https://example.com/bot) "
        "Mozilla/5.0"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
}
REQUEST_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
RETRY_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def serialize_document(document: Document) -> dict:
    return {
        "id": document.id,
        "bot_id": document.bot_id,
        "filename": document.filename,
        "source_type": document.source_type,
        "source_url": document.source_url,
        "file_size": document.file_size,
        "processing_status": document.processing_status,
        "processing_error": document.processing_error,
        "chunk_count": document.chunk_count,
        "token_count": document.token_count,
        "metadata": document.metadata_json or {},
        "created_at": document.created_at,
        "updated_at": document.updated_at,
    }


def sanitize_filename(filename: str) -> str:
    name = Path(filename or "upload").name
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
    return name[:180] or f"upload-{uuid4().hex}"


def validate_upload(file: UploadFile) -> str:
    filename = sanitize_filename(file.filename or "")
    extension = Path(filename).suffix.lower()
    content_type = (file.content_type or mimetypes.guess_type(filename)[0] or "").lower()
    mime_extension = SUPPORTED_MIME_TYPES.get(content_type)

    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Supported file types are PDF, TXT, and DOCX.")
    if content_type and content_type not in SUPPORTED_MIME_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported MIME type: {content_type}")
    if mime_extension and mime_extension != extension:
        raise HTTPException(status_code=400, detail="File extension does not match its MIME type.")
    return filename


def save_upload(file: UploadFile, bot_id: int) -> tuple[str, int]:
    filename = validate_upload(file)
    target_dir = (UPLOAD_DIR / str(bot_id)).resolve()
    if not str(target_dir).startswith(str(UPLOAD_DIR)):
        raise HTTPException(status_code=400, detail="Invalid upload target.")

    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{uuid4().hex}-{filename}"
    size = 0

    with target.open("wb") as output:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                try:
                    target.unlink(missing_ok=True)
                finally:
                    raise HTTPException(status_code=413, detail="File exceeds upload size limit.")
            output.write(chunk)

    return str(target), size


def validate_public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="URL must be an absolute http(s) URL.")

    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(status_code=400, detail="URL hostname is required.")

    try:
        addresses = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail="URL hostname could not be resolved.") from exc

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            raise HTTPException(status_code=400, detail="Private or local URLs are not allowed.")
    return url


def extract_text_from_file(path: str, source_type: str) -> str:
    if source_type == "txt":
        return Path(path).read_text(encoding="utf-8", errors="ignore")
    if source_type == "pdf":
        reader = PdfReader(path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if source_type == "docx":
        doc = DocxDocument(path)
        return "\n".join(paragraph.text for paragraph in doc.paragraphs)
    raise ValueError(f"Unsupported source type: {source_type}")


def fetch_html(url: str) -> httpx.Response:
    normalized_url = validate_public_url(url)
    last_error: Exception | None = None
    with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True, headers=REQUEST_HEADERS) as client:
        for attempt in range(3):
            try:
                response = client.get(normalized_url)
                if response.status_code not in RETRY_STATUS_CODES:
                    response.raise_for_status()
                    return response
                response.raise_for_status()
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
                status_code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                if attempt == 2 or (status_code is not None and status_code not in RETRY_STATUS_CODES):
                    raise
                time.sleep(0.5 * (attempt + 1))
    raise RuntimeError("Unable to fetch URL.") from last_error


def extract_readable_text_from_html(html: str, fallback_title: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(
        [
            "script",
            "style",
            "noscript",
            "svg",
            "iframe",
            "header",
            "footer",
            "nav",
            "form",
            "button",
            "aside",
            "table",
            "figure",
            "sup",
        ]
    ):
        tag.decompose()
    for tag in soup.select(".infobox, .navbox, .metadata, .mw-editsection, .reference"):
        tag.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else fallback_title
    main = (
        soup.find(id="mw-content-text")
        or soup.find("main")
        or soup.find("article")
        or soup.find(attrs={"role": "main"})
        or soup.body
        or soup
    )
    paragraphs = [
        normalize_text(block.get_text(" ", strip=True))
        for block in main.find_all(["h1", "h2", "h3", "p"])
    ]
    if not paragraphs:
        paragraphs = [normalize_text(block.get_text(" ", strip=True)) for block in main.find_all("li")]
    text = "\n\n".join(paragraph for paragraph in paragraphs if paragraph)
    if not text:
        text = normalize_text(main.get_text(" "))
    return title, text


def extract_text_from_url(url: str) -> tuple[str, str]:
    response = fetch_html(url)

    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
        raise ValueError("URL did not return an HTML page.")

    return extract_readable_text_from_html(response.text, url)


def create_file_document(db: Session, bot_id: int, file: UploadFile) -> Document:
    path, size = save_upload(file, bot_id)
    filename = sanitize_filename(file.filename or Path(path).name)
    source_type = Path(filename).suffix.lower().lstrip(".")
    bot = db.query(Bot).filter(Bot.id == bot_id).first()
    document = Document(
        bot_id=bot_id,
        organization_id=bot.organization_id if bot else None,
        filename=filename,
        source_type=source_type,
        title=filename,
        raw_text="",
        file_path=path,
        file_size=size,
        processing_status="pending",
        metadata_json={"original_filename": file.filename, "content_type": file.content_type},
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def create_website_document(db: Session, bot_id: int, url: str) -> Document:
    normalized_url = validate_public_url(url)
    bot = db.query(Bot).filter(Bot.id == bot_id).first()
    existing = (
        db.query(Document)
        .filter(Document.bot_id == bot_id, Document.source_url == normalized_url)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="This URL is already in the bot knowledge base.")

    document = Document(
        bot_id=bot_id,
        organization_id=bot.organization_id if bot else None,
        filename=urlparse(normalized_url).netloc,
        source_type="website",
        source_url=normalized_url,
        title=normalized_url,
        raw_text="",
        processing_status="pending",
        metadata_json={"crawl_mode": "single_page"},
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def process_document(db: Session, document_id: int) -> Document:
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise ValueError(f"Document {document_id} was not found")

    document.processing_status = "processing"
    document.processing_error = None
    document.updated_at = datetime.utcnow()
    db.query(Chunk).filter(Chunk.document_id == document.id).delete()
    db.commit()

    try:
        if document.source_type == "website":
            title, text = extract_text_from_url(document.source_url or "")
            document.filename = title[:180] or document.filename
            document.title = title
        else:
            if document.source_type == "text" and document.raw_text:
                text = document.raw_text
            else:
                text = extract_text_from_file(document.file_path or "", document.source_type)

        normalized = normalize_text(text)
        document.raw_text = normalized
        chunks = chunk_text_with_metadata(normalized, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
        if not chunks:
            raise ValueError("No usable text found after parsing.")

        total_tokens = count_tokens(normalized)
        for chunk in chunks:
            db.add(
                Chunk(
                    document_id=document.id,
                    bot_id=document.bot_id,
                    organization_id=document.organization_id,
                    chunk_index=chunk.index,
                    content=chunk.content,
                    embedding=generate_embedding(chunk.content),
                    token_count=chunk.token_count,
                    metadata_json={
                        "start_token": chunk.start_token,
                        "end_token": chunk.end_token,
                        "source_type": document.source_type,
                    },
                )
            )

        document.processing_status = "completed"
        document.processing_error = None
        document.chunk_count = len(chunks)
        document.token_count = total_tokens
    except Exception as exc:
        document.processing_status = "failed"
        document.processing_error = str(exc)[:2000]
        document.chunk_count = 0
        document.token_count = 0
    finally:
        document.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(document)

    return document


def process_document_job(document_id: int) -> None:
    db = SessionLocal()
    try:
        process_document(db, document_id)
    finally:
        db.close()


def reindex_document(db: Session, document_id: int) -> Document:
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")
    return process_document(db, document_id)
