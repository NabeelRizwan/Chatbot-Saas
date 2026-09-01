from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Set

from sqlalchemy.orm import Session


class JobStatus(str, Enum):
    QUEUED = "queued"
    CRAWLING = "crawling"
    PROCESSING = "processing"
    EMBEDDING = "embedding"
    VALIDATING = "validating"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"


VALID_TRANSITIONS: Dict[JobStatus, Set[JobStatus]] = {
    JobStatus.QUEUED: {JobStatus.CRAWLING, JobStatus.PROCESSING, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.CRAWLING: {JobStatus.PROCESSING, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.PROCESSING: {JobStatus.EMBEDDING, JobStatus.VALIDATING, JobStatus.READY, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.EMBEDDING: {JobStatus.VALIDATING, JobStatus.READY, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.VALIDATING: {JobStatus.READY, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.READY: {JobStatus.QUEUED},  # Allowed on recrawl/reindex
    JobStatus.FAILED: {JobStatus.QUEUED},  # Allowed on retry
    JobStatus.CANCELLED: {JobStatus.QUEUED},  # Allowed on retry
}


def can_transition(current_status: str, next_status: str) -> bool:
    try:
        curr = JobStatus(current_status.lower().strip())
        nxt = JobStatus(next_status.lower().strip())
    except ValueError:
        return False
    return nxt in VALID_TRANSITIONS.get(curr, set())


def transition_job_state(
    db: Session,
    job_id: str,
    next_status: JobStatus | str,
    stage: Optional[str] = None,
    progress_percent: Optional[int] = None,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    chunks_created: Optional[int] = None,
    embeddings_created: Optional[int] = None,
    pages_discovered: Optional[int] = None,
    pages_crawled: Optional[int] = None,
    pages_failed: Optional[int] = None,
    documents_created: Optional[int] = None,
) -> bool:
    """
    Atomically validates and transitions an IngestionJob to a new state.
    Rejects invalid state transitions and prevents terminal state corruption.
    """
    from database.models import IngestionJob

    job = db.query(IngestionJob).filter(IngestionJob.job_id == job_id).with_for_update().first()
    if not job:
        return False

    next_status_str = next_status.value if isinstance(next_status, JobStatus) else str(next_status).lower().strip()

    if not can_transition(job.status, next_status_str):
        return False

    job.status = next_status_str
    if job.started_at is None and next_status_str in {"crawling", "processing", "embedding", "validating"}:
        job.started_at = datetime.utcnow()
    if stage:
        job.current_stage = stage
    if progress_percent is not None:
        if next_status_str == "queued":
            job.progress_percent = 0
        else:
            job.progress_percent = max(job.progress_percent, min(100, progress_percent))

    if chunks_created is not None:
        job.chunks_created = chunks_created
    if embeddings_created is not None:
        job.embeddings_created = embeddings_created
    if pages_discovered is not None:
        job.pages_discovered = pages_discovered
    if pages_crawled is not None:
        job.pages_crawled = pages_crawled
    if pages_failed is not None:
        job.pages_failed = pages_failed
    if documents_created is not None:
        job.documents_created = documents_created

    job.last_heartbeat = datetime.utcnow()
    job.updated_at = datetime.utcnow()

    if next_status_str in ("ready", "failed", "cancelled"):
        job.completed_at = datetime.utcnow()
        if next_status_str == "ready":
            job.progress_percent = 100

    if error_code:
        job.error_code = error_code
    if error_message:
        job.error_message = error_message

    db.commit()
    return True


def sanitize_customer_error(exc: Exception, default_message: str = "Ingestion processing encountered an error.") -> tuple[str, str]:
    """
    Sanitize internal exception details so stack traces and sensitive infra
    paths are never exposed to customers.

    Returns:
        (error_code, safe_customer_message)
    """
    msg = str(exc).lower()
    if getattr(exc, "status_code", None) == 402 or "current plan" in msg:
        return "PLAN_QUOTA_EXCEEDED", "The staged knowledge version exceeds the current document or logical storage plan limit. The previous active version was preserved."
    if "429" in msg or "quota" in msg or "rate limit" in msg:
        return "RATE_LIMIT_EXCEEDED", "AI provider rate limit reached. The job will be retried."
    elif "timeout" in msg or "timed out" in msg:
        return "TIMEOUT", "The website or AI provider took too long to respond. The job will be retried."
    elif "ssrf" in msg or "forbidden_host" in msg or "private ip" in msg:
        return "SSRF_BLOCKED", "The requested URL targets an internal or disallowed network address."
    elif "503" in msg or "service unavailable" in msg or "connect" in msg:
        return "SERVICE_UNAVAILABLE", "The target website was temporarily unavailable (503 Service Unavailable)."
    elif "404" in msg or "not found" in msg:
        return "NOT_FOUND", "The requested website or document could not be found (404 Not Found)."
    elif "tenant_mismatch" in msg:
        return "TENANT_MISMATCH", "Unauthorized tenant boundary access detected."
    elif "cancelled" in msg:
        return "CANCELLED", "Job was cancelled by user."
    return "INTERNAL_PROCESSING_ERROR", default_message
