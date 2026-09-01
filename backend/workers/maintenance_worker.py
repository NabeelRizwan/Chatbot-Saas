from datetime import datetime, timedelta
from typing import List

from sqlalchemy import or_
from database.connection import SessionLocal
from database.models import Chunk, Document, IngestionJob, Website, WebsiteCrawl
from services.usage_service import reconcile_stale_message_reservations


def recover_stale_jobs(max_age_seconds: int = 900) -> List[str]:
    """
    Scans for jobs that have been stuck in an active non-terminal state without
    a heartbeat for more than max_age_seconds (e.g. 15 minutes due to worker crash / OOM).
    Safely marks them as failed without corrupting active website knowledge.
    """
    db = SessionLocal()
    recovered_job_ids = []
    cutoff = datetime.utcnow() - timedelta(seconds=max_age_seconds)

    try:
        stale_cancellations = (
            db.query(IngestionJob)
            .filter(
                IngestionJob.status == "cancelled",
                IngestionJob.current_stage == "cancelling",
                or_(IngestionJob.last_heartbeat < cutoff, IngestionJob.updated_at < cutoff),
            )
            .all()
        )
        for job in stale_cancellations:
            # Cancellation already makes promotion impossible. This is only the
            # delayed acknowledgement when the owning worker disappeared.
            job.current_stage = "cancelled"
            job.completed_at = datetime.utcnow()
            job.last_heartbeat = datetime.utcnow()
            recovered_job_ids.append(job.job_id)
            db.query(Chunk).filter(Chunk.ingestion_job_id == job.job_id).delete(synchronize_session=False)
            staged_documents = db.query(Document).filter(
                Document.ingestion_job_id == job.job_id,
                Document.id != job.document_id,
            ).all()
            for staged_document in staged_documents:
                db.delete(staged_document)
            if job.crawl_id:
                crawl = db.query(WebsiteCrawl).filter(WebsiteCrawl.id == job.crawl_id).first()
                if crawl and crawl.status == "processing":
                    crawl.status = "cancelled"
                    crawl.error_summary = "Crawl cancelled before activation."
                    crawl.completed_at = datetime.utcnow()
            if job.website_id:
                website = db.query(Website).filter(Website.id == job.website_id).first()
                if website:
                    website.crawl_status = "cancelled"
                    website.status = "ready" if website.active_crawl_id else "failed"

        stale_jobs = (
            db.query(IngestionJob)
            .filter(
                IngestionJob.status.in_(["crawling", "processing", "embedding", "validating"]),
                or_(IngestionJob.last_heartbeat < cutoff, IngestionJob.updated_at < cutoff),
            )
            .all()
        )

        for job in stale_jobs:
            job.status = "failed"
            job.current_stage = "failed"
            job.error_code = "WORKER_TIMEOUT"
            job.error_message = "Worker process terminated or timed out without heartbeat. Job can be retried safely."
            job.completed_at = datetime.utcnow()
            job.last_heartbeat = datetime.utcnow()
            recovered_job_ids.append(job.job_id)

            db.query(Chunk).filter(Chunk.ingestion_job_id == job.job_id).delete(
                synchronize_session=False
            )
            staged_documents = db.query(Document).filter(
                Document.ingestion_job_id == job.job_id,
                Document.id != job.document_id,
            ).all()
            for staged_document in staged_documents:
                db.delete(staged_document)
            root_document = db.query(Document).filter(Document.id == job.document_id).first()
            if root_document and root_document.ingestion_job_id == job.job_id:
                root_document.ingestion_job_id = None
                has_active = db.query(Chunk.id).filter(
                    Chunk.document_id == root_document.id,
                    Chunk.status == "ready",
                ).first()
                if not has_active:
                    root_document.status = "processing_failed"
                    root_document.processing_status = "failed"
                    root_document.processing_error = job.error_message

            if job.crawl_id:
                crawl = db.query(WebsiteCrawl).filter(WebsiteCrawl.id == job.crawl_id).first()
                if crawl and crawl.status == "processing":
                    crawl.status = "failed"
                    crawl.error_summary = job.error_message
                    crawl.completed_at = datetime.utcnow()

            # Ensure website status remains ready if previous versions exist
            if job.website_id:
                ws = db.query(Website).filter(Website.id == job.website_id).first()
                if ws:
                    ws.crawl_status = "failed"
                    ws.status = "ready" if ws.active_crawl_id else "failed"

        db.commit()
    finally:
        db.close()

    return recovered_job_ids


def reconcile_message_reservations() -> List[int]:
    """Release only reservations beyond the conservative heartbeat-aware TTL."""
    db = SessionLocal()
    try:
        return reconcile_stale_message_reservations(db)
    finally:
        db.close()
