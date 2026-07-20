from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Path, Query, UploadFile
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import Bot, Chunk, Document, User
from schemas.schemas import (
    KnowledgeAcceptedResponse,
    KnowledgeCrawlRequest,
    KnowledgeDeleteResponse,
    KnowledgeDocumentListResponse,
    KnowledgeDocumentResponse,
)
from services.document_processing_service import (
    create_file_document,
    create_website_document,
    process_document_job,
    serialize_document,
)
from services.auth_service import get_optional_user
from services.organization_service import require_org_role
from services.usage_service import ensure_can_add_document, record_usage, refresh_resource_usage
from services.rag_service import clear_retrieval_cache

router = APIRouter()


def _ensure_bot(db: Session, bot_id: int, user: User | None = None, minimum_role: str = "member") -> Bot:
    bot = db.query(Bot).filter(Bot.id == bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found.")
    if bot.organization_id:
        if not user:
            raise HTTPException(status_code=401, detail="Authentication required")
        require_org_role(db, user, bot.organization_id, minimum_role)
    return bot


def _get_document(db: Session, document_id: int, user: User | None = None, minimum_role: str = "member") -> Document:
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")
    if document.organization_id:
        if not user:
            raise HTTPException(status_code=401, detail="Authentication required")
        require_org_role(db, user, document.organization_id, minimum_role)
    return document


@router.get("/documents", response_model=KnowledgeDocumentListResponse)
def list_documents(
    bot_id: int = Query(..., gt=0),
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    _ensure_bot(db, bot_id, current_user)
    documents = (
        db.query(Document)
        .filter(Document.bot_id == bot_id)
        .order_by(Document.created_at.desc())
        .all()
    )
    return {"documents": [serialize_document(document) for document in documents]}


@router.post("/upload", response_model=KnowledgeAcceptedResponse, status_code=202)
def upload_document(
    background_tasks: BackgroundTasks,
    bot_id: int = Query(..., gt=0),
    file: UploadFile = File(...),
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    bot = _ensure_bot(db, bot_id, current_user, "admin")
    if bot.organization_id:
        ensure_can_add_document(db, bot.organization_id, incoming_bytes=file.size or 0)
    document = create_file_document(db, bot_id=bot_id, file=file)
    clear_retrieval_cache(bot_id)
    if bot.organization_id:
        record_usage(db, bot.organization_id, document_uploads=1, storage_bytes_delta=document.file_size or 0)
    background_tasks.add_task(process_document_job, document.id)
    return {
        "document": serialize_document(document),
        "message": "Upload accepted. Processing will continue in the background.",
    }


@router.post("/crawl", response_model=KnowledgeAcceptedResponse, status_code=202)
def crawl_website(
    data: KnowledgeCrawlRequest,
    background_tasks: BackgroundTasks,
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    bot = _ensure_bot(db, data.bot_id, current_user, "admin")
    if bot.organization_id:
        ensure_can_add_document(db, bot.organization_id)
    document = create_website_document(db, bot_id=data.bot_id, url=str(data.url))
    clear_retrieval_cache(data.bot_id)
    if bot.organization_id:
        record_usage(db, bot.organization_id, document_uploads=1)
    background_tasks.add_task(process_document_job, document.id)
    return {
        "document": serialize_document(document),
        "message": "Crawl accepted. The page will be processed in the background.",
    }


@router.delete("/documents/{document_id}", response_model=KnowledgeDeleteResponse)
def delete_document(
    document_id: int = Path(..., gt=0),
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    document = _get_document(db, document_id, current_user, "admin")
    bot_id = document.bot_id
    organization_id = document.organization_id
    file_size = document.file_size or 0
    db.delete(document)
    db.commit()
    clear_retrieval_cache(bot_id)
    if organization_id:
        record_usage(db, organization_id, storage_bytes_delta=-file_size)
        refresh_resource_usage(db, organization_id)
    return {
        "success": True,
        "document_id": document_id,
        "message": "Knowledge source deleted.",
    }


@router.post("/documents/{document_id}/reindex", response_model=KnowledgeAcceptedResponse, status_code=202)
def reindex_document(
    background_tasks: BackgroundTasks,
    document_id: int = Path(..., gt=0),
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    document = _get_document(db, document_id, current_user, "admin")
    db.query(Chunk).filter(Chunk.document_id == document.id).delete()
    clear_retrieval_cache(document.bot_id)
    document.processing_status = "pending"
    document.processing_error = None
    document.chunk_count = 0
    document.token_count = 0
    db.commit()
    db.refresh(document)
    background_tasks.add_task(process_document_job, document.id)
    return {
        "document": serialize_document(document),
        "message": "Reindex accepted. Processing will continue in the background.",
    }
