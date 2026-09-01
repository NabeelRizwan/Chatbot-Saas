from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pypdf import PdfReader
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import Bot, Chunk, Document, User
from schemas.schemas import IngestResponse, TextIngestRequest, WebsiteIngestRequest
from services.auth_service import get_current_user
from services.bot_service import get_bot_or_404
from services.chunking_service import chunk_text_with_metadata, count_tokens
from services.embedding_service import generate_embedding
from services.scraper_service import scrape_website
from services.usage_service import ensure_can_add_document, record_usage

router = APIRouter()


def _store_document(
    db: Session,
    bot_id: int,
    source_type: str,
    raw_text: str,
    title: str | None = None,
    source_url: str | None = None,
) -> IngestResponse:
    chunks = chunk_text_with_metadata(
        raw_text,
        page_title=title,
        source_url=source_url,
        metadata={"title": title, "source_type": source_type},
    )
    if not chunks:
        raise HTTPException(status_code=400, detail="No usable text found to ingest")

    bot = db.query(Bot).filter(Bot.id == bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    if bot.organization_id is None:
        raise HTTPException(
            status_code=409,
            detail="This legacy bot must be assigned to an organization before knowledge can be added.",
        )
    logical_size = len(raw_text.encode("utf-8"))
    ensure_can_add_document(db, bot.organization_id, incoming_bytes=logical_size)
    document = Document(
        bot_id=bot_id,
        organization_id=bot.organization_id,
        filename=title or source_url or "text-ingest",
        source_type=source_type,
        source_url=source_url,
        title=title,
        raw_text=raw_text,
        logical_size_bytes=logical_size,
        processing_status="pending",
        chunk_count=0,
        token_count=0,
        metadata_json={"legacy_ingest": True, "title": title},
    )
    db.add(document)
    db.flush()

    for chunk in chunks:
        db.add(
            Chunk(
                document_id=document.id,
                bot_id=bot_id,
                organization_id=document.organization_id,
                chunk_index=chunk.index,
                content=chunk.content,
                embedding=generate_embedding(chunk.content),
                token_count=chunk.token_count,
                metadata_json={
                    "source_type": source_type,
                    "source_url": source_url,
                    "page_title": title or "",
                    "heading": chunk.heading,
                    "section": chunk.section,
                    "start_token": chunk.start_token,
                    "end_token": chunk.end_token,
                },
            )
        )

    document.processing_status = "completed"
    document.chunk_count = len(chunks)
    document.token_count = count_tokens(raw_text)
    db.commit()
    db.refresh(document)
    record_usage(db, document.organization_id, embeddings_used=len(chunks), document_uploads=1)
    return IngestResponse(document_id=document.id, chunks_created=len(chunks))


@router.post("/website", response_model=IngestResponse)
def ingest_website(data: WebsiteIngestRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bot = get_bot_or_404(db, bot_id=data.bot_id, user=current_user, minimum_role="editor")
    title, text = scrape_website(str(data.url), use_playwright=data.use_playwright)
    return _store_document(
        db=db,
        bot_id=bot.id,
        source_type="website",
        source_url=str(data.url),
        title=title,
        raw_text=text,
    )


@router.post("/text", response_model=IngestResponse)
def ingest_text(data: TextIngestRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bot = get_bot_or_404(db, bot_id=data.bot_id, user=current_user, minimum_role="editor")
    if not data.text.strip():
        raise HTTPException(status_code=400, detail="Text is empty")
    return _store_document(
        db=db,
        bot_id=bot.id,
        source_type="text",
        title=data.title,
        raw_text=data.text,
    )


@router.post("/pdf", response_model=IngestResponse)
def ingest_pdf(
    bot_id: int = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    bot = get_bot_or_404(db, bot_id=bot_id, user=current_user, minimum_role="editor")

    reader = PdfReader(file.file)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    return _store_document(
        db=db,
        bot_id=bot.id,
        source_type="pdf",
        title=file.filename,
        raw_text=text,
    )
