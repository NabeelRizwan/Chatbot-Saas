from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Path, Query, UploadFile
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import Bot, Document, IngestionJob, User, Website
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
    remove_unreferenced_upload,
    serialize_document,
)
from services.auth_service import get_current_user
from services.bot_service import get_bot_or_404
from services.usage_service import ensure_can_add_document, record_usage, refresh_resource_usage
from services.rag_service import clear_retrieval_cache
from services.firecrawl_service import normalize_crawl_url

router = APIRouter()


def _ensure_bot(db: Session, bot_id: int, user: User | None = None, minimum_role: str = "member") -> Bot:
    return get_bot_or_404(db, bot_id, user=user, minimum_role=minimum_role)


def _get_document(db: Session, document_id: int, user: User | None = None, minimum_role: str = "member") -> Document:
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")
    bot = get_bot_or_404(db, document.bot_id, user=user, minimum_role=minimum_role)
    if document.organization_id != bot.organization_id:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document


@router.get("/documents", response_model=KnowledgeDocumentListResponse)
def list_documents(
    bot_id: int = Query(..., gt=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_bot(db, bot_id, current_user)
    documents = (
        db.query(Document)
        .filter(Document.bot_id == bot_id)
        .order_by(Document.created_at.desc())
        .all()
    )
    websites = {
        website.id: website
        for website in db.query(Website).filter(Website.bot_id == bot_id).all()
    }
    standalone = [document for document in documents if document.website_id is None]
    website_documents: list[Document] = []
    for website_id, website in websites.items():
        candidates = [document for document in documents if document.website_id == website_id]
        if not candidates:
            continue
        normalized_root = normalize_crawl_url(website.root_url)
        root = next(
            (
                document for document in candidates
                if normalize_crawl_url(document.source_url or "") == normalized_root
            ),
            min(candidates, key=lambda document: document.id),
        )
        website_documents.append(root)
    visible_documents = sorted(
        standalone + website_documents,
        key=lambda document: document.created_at,
        reverse=True,
    )
    return {"documents": [serialize_document(document) for document in visible_documents]}


from services.queue_service import (
    QueueUnavailableError,
    cancel_job,
    enqueue_ingestion_job,
    get_job_status,
    list_job_statuses,
    retry_job,
)
from schemas.schemas import JobListResponse, JobResponse


from utils.rate_limiter import enforce_rate_limit


@router.post("/upload", response_model=KnowledgeAcceptedResponse, status_code=202)
def upload_document(
    background_tasks: BackgroundTasks,
    bot_id: int = Query(..., gt=0),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bot = _ensure_bot(db, bot_id, current_user, "admin")
    enforce_rate_limit(scope="upload", org_id=bot.organization_id, bot_id=bot.id)
    ensure_can_add_document(db, bot.organization_id, incoming_bytes=file.size or 0)
    document = create_file_document(db, bot_id=bot_id, file=file)
    clear_retrieval_cache(bot_id)
    record_usage(db, bot.organization_id, document_uploads=1)
    try:
        job = enqueue_ingestion_job(
            db=db,
            bot_id=bot_id,
            organization_id=bot.organization_id,
            document_id=document.id,
            job_type="document_upload",
            background_tasks=background_tasks,
        )
    except QueueUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Ingestion queue unavailable; the upload was not dispatched.") from exc
    return {
        "document": serialize_document(document),
        "message": "Upload accepted. Processing will continue in the background.",
        "job_id": job.job_id,
    }


@router.delete("/sources/{document_id}", response_model=KnowledgeDeleteResponse)
def delete_source(
    document_id: int = Path(..., gt=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    document = _get_document(db, document_id, current_user, "admin")
    website_id = document.website_id
    if document.source_type == "website" and not website_id:
        latest_website_job = db.query(IngestionJob).filter(
            IngestionJob.document_id == document.id,
            IngestionJob.website_id.is_not(None),
        ).order_by(IngestionJob.created_at.desc()).first()
        website_id = latest_website_job.website_id if latest_website_job else None
    active_jobs = db.query(IngestionJob).filter(
        IngestionJob.bot_id == document.bot_id,
        IngestionJob.organization_id == document.organization_id,
        IngestionJob.status.in_(["queued", "crawling", "processing", "embedding", "validating"]),
        or_(
            IngestionJob.document_id == document.id,
            IngestionJob.website_id == website_id if website_id else False,
        ),
    ).count()
    if active_jobs:
        raise HTTPException(status_code=409, detail="Cancel the active knowledge job before deleting this source.")

    bot_id = document.bot_id
    organization_id = document.organization_id
    file_paths: list[str | None] = []
    scope = "website" if document.source_type == "website" and website_id else "document"
    if scope == "website":
        source_documents = db.query(Document).filter(
            or_(Document.website_id == website_id, Document.id == document.id)
        ).all()
        source_document_ids = [item.id for item in source_documents]
        file_paths = [item.file_path for item in source_documents]
        db.query(IngestionJob).filter(IngestionJob.document_id.in_(source_document_ids)).update(
            {"document_id": None}, synchronize_session=False
        )
        db.query(IngestionJob).filter(IngestionJob.website_id == website_id).update(
            {"website_id": None, "crawl_id": None}, synchronize_session=False
        )
        for item in source_documents:
            db.delete(item)
        website = db.query(Website).filter(Website.id == website_id).first()
        if website:
            db.delete(website)
        deleted_documents = len(source_documents)
    else:
        file_paths = [document.file_path]
        db.query(IngestionJob).filter(IngestionJob.document_id == document.id).update(
            {"document_id": None}, synchronize_session=False
        )
        db.delete(document)
        deleted_documents = 1
    db.commit()
    for file_path in file_paths:
        remove_unreferenced_upload(db, file_path)
    clear_retrieval_cache(bot_id)
    refresh_resource_usage(db, organization_id)
    return {
        "success": True,
        "document_id": document_id,
        "scope": scope,
        "deleted_documents": deleted_documents,
        "message": "Website source and all indexed pages deleted." if scope == "website" else "Uploaded source deleted.",
    }


@router.post("/crawl", response_model=KnowledgeAcceptedResponse, status_code=202)
def crawl_website(
    data: KnowledgeCrawlRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bot = _ensure_bot(db, data.bot_id, current_user, "admin")
    enforce_rate_limit(scope="crawl", org_id=bot.organization_id, bot_id=bot.id)
    ensure_can_add_document(db, bot.organization_id)

    document = create_website_document(
        db,
        bot_id=data.bot_id,
        url=str(data.url),
        crawl_mode=data.crawl_mode,
    )
    clear_retrieval_cache(data.bot_id)
    record_usage(db, bot.organization_id, document_uploads=1)
    try:
        job = enqueue_ingestion_job(
            db=db,
            bot_id=data.bot_id,
            organization_id=bot.organization_id,
            document_id=document.id,
            job_type="crawl",
            website_id=document.website_id,
            background_tasks=background_tasks,
        )
    except QueueUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Ingestion queue unavailable; the crawl was not dispatched.") from exc
    return {
        "document": serialize_document(document),
        "message": "Crawl accepted. The page will be processed in the background.",
        "job_id": job.job_id,
    }



@router.delete("/documents/{document_id}", response_model=KnowledgeDeleteResponse)
def delete_document(
    document_id: int = Path(..., gt=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    document = _get_document(db, document_id, current_user, "admin")
    bot_id = document.bot_id
    organization_id = document.organization_id
    file_path = document.file_path
    db.query(IngestionJob).filter(IngestionJob.document_id == document.id).update(
        {"document_id": None}, synchronize_session=False
    )
    db.delete(document)
    db.commit()
    remove_unreferenced_upload(db, file_path)
    clear_retrieval_cache(bot_id)
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    document = _get_document(db, document_id, current_user, "admin")
    try:
        job = enqueue_ingestion_job(
            db=db,
            bot_id=document.bot_id,
            organization_id=document.organization_id,
            document_id=document.id,
            job_type="document_upload" if document.source_type != "website" else "recrawl",
            website_id=document.website_id,
            background_tasks=background_tasks,
        )
    except QueueUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Ingestion queue unavailable; reindex was not dispatched.") from exc
    return {
        "document": serialize_document(document),
        "message": (
            "Re-crawl accepted. Existing active knowledge remains available until the replacement is ready."
            if document.source_type == "website"
            else "Reindex accepted. Existing active knowledge remains available until the replacement is ready."
        ),
        "job_id": job.job_id,
    }


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job_info(
    job_id: str = Path(..., min_length=1),
    bot_id: int = Query(..., gt=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bot = _ensure_bot(db, bot_id, current_user, "viewer")
    status = get_job_status(db, job_id, bot_id=bot.id, organization_id=bot.organization_id)
    if not status:
        raise HTTPException(status_code=404, detail="Job not found or unauthorized.")
    return status


@router.get("/jobs", response_model=JobListResponse)
def list_jobs(
    bot_id: int = Query(..., gt=0),
    limit: int = Query(default=25, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bot = _ensure_bot(db, bot_id, current_user, "viewer")
    return {"jobs": list_job_statuses(db, bot.id, bot.organization_id, limit)}


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse, status_code=202)
def cancel_job_endpoint(
    job_id: str = Path(..., min_length=1),
    bot_id: int = Query(..., gt=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bot = _ensure_bot(db, bot_id, current_user, "admin")
    cancelled = cancel_job(db, job_id, bot_id=bot.id, organization_id=bot.organization_id)
    if not cancelled:
        raise HTTPException(status_code=400, detail="Job could not be cancelled (it may have already completed or failed).")
    status = get_job_status(db, job_id, bot_id=bot.id, organization_id=bot.organization_id)
    return status


@router.post("/jobs/{job_id}/retry", response_model=JobResponse, status_code=202)
def retry_job_endpoint(
    background_tasks: BackgroundTasks,
    job_id: str = Path(..., min_length=1),
    bot_id: int = Query(..., gt=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bot = _ensure_bot(db, bot_id, current_user, "admin")
    try:
        job = retry_job(db, job_id, bot.id, bot.organization_id, background_tasks)
    except QueueUnavailableError as exc:
        raise HTTPException(status_code=503, detail="The ingestion queue is unavailable. Retry after worker readiness is restored.") from exc
    if not job:
        raise HTTPException(status_code=400, detail="This job is not retryable.")
    return get_job_status(db, job.job_id, bot_id=bot.id, organization_id=bot.organization_id)
