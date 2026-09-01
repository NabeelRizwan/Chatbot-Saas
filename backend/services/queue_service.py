import asyncio
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from database.models import Document, IngestionJob, Website, WebsiteCrawl
from workers.crawl_worker import execute_crawl_job
from workers.embedding_worker import execute_document_job


class QueueUnavailableError(RuntimeError):
    """The durable job exists, but production dispatch could not be completed."""


def _is_production() -> bool:
    return (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "development").lower() in {
        "production",
        "prod",
    }


def get_queue_mode() -> str:
    configured = (os.getenv("INGESTION_QUEUE_MODE") or "").lower().strip()
    if configured:
        return configured
    return "arq" if _is_production() else "background"


async def get_redis_pool() -> ArqRedis:
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    timeout = float(os.getenv("QUEUE_CONNECT_TIMEOUT_SECONDS", "5"))
    return await asyncio.wait_for(
        create_pool(RedisSettings.from_dsn(redis_url)),
        timeout=timeout,
    )


async def _close_pool(pool: ArqRedis) -> None:
    close = getattr(pool, "aclose", None) or getattr(pool, "close", None)
    if not close:
        return
    result = close()
    if asyncio.iscoroutine(result):
        await result


async def _dispatch_to_arq(job: IngestionJob) -> None:
    pool = await get_redis_pool()
    try:
        function_name = "crawl_task" if job.job_type in {"crawl", "recrawl"} else "document_task"
        await pool.enqueue_job(
            function_name,
            job.job_id,
            job.bot_id,
            job.organization_id,
            job.document_id,
            _job_id=job.arq_job_id or job.job_id,
            _queue_name=os.getenv("ARQ_QUEUE_NAME", "ingestion"),
        )
    finally:
        await _close_pool(pool)


def _run_async(coroutine) -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(coroutine)
        return
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="arq-dispatch") as executor:
        executor.submit(asyncio.run, coroutine).result()


def _mark_dispatch_failed(db: Session, job: IngestionJob, message: str) -> None:
    job.status = "failed"
    job.current_stage = "dispatch_failed"
    job.error_code = "QUEUE_UNAVAILABLE"
    job.error_message = message
    job.completed_at = datetime.utcnow()
    job.last_heartbeat = datetime.utcnow()
    db.commit()


def enqueue_ingestion_job(
    db: Session,
    bot_id: int,
    organization_id: Optional[int],
    document_id: int,
    job_type: str = "crawl",
    website_id: Optional[int] = None,
    crawl_id: Optional[int] = None,
    background_tasks: Optional[BackgroundTasks] = None,
) -> IngestionJob:
    """Create one durable logical job and dispatch it through the configured executor."""
    if organization_id is None:
        raise ValueError("organization_id is required for tenant ingestion jobs")

    locked_document = (
        db.query(Document)
        .filter(
            Document.id == document_id,
            Document.bot_id == bot_id,
            Document.organization_id == organization_id,
        )
        .with_for_update()
        .first()
    )
    if not locked_document:
        raise ValueError("Document does not match the ingestion tenant scope")

    existing_job = (
        db.query(IngestionJob)
        .filter(
            IngestionJob.bot_id == bot_id,
            IngestionJob.organization_id == organization_id,
            IngestionJob.document_id == document_id,
            IngestionJob.status.in_(["queued", "crawling", "processing", "embedding", "validating"]),
        )
        .order_by(IngestionJob.created_at.desc())
        .first()
    )
    if existing_job:
        db.commit()
        if existing_job.status == "queued" and get_queue_mode() == "arq":
            try:
                _run_async(_dispatch_to_arq(existing_job))
            except Exception as exc:
                raise QueueUnavailableError("Unable to confirm ingestion job dispatch to Redis/ARQ") from exc
        return existing_job

    job_uuid = f"job_{uuid.uuid4().hex[:16]}"
    job = IngestionJob(
        job_id=job_uuid,
        arq_job_id=job_uuid,
        bot_id=bot_id,
        organization_id=organization_id,
        document_id=document_id,
        website_id=website_id,
        crawl_id=crawl_id,
        job_type=job_type,
        status="queued",
        current_stage="queued",
        progress_percent=0,
        last_heartbeat=datetime.utcnow(),
        audit_metadata={},
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    mode = get_queue_mode()
    if mode == "arq":
        try:
            _run_async(_dispatch_to_arq(job))
        except Exception as exc:
            _mark_dispatch_failed(
                db,
                job,
                "The ingestion queue is unavailable. Verify Redis and the ARQ worker configuration.",
            )
            raise QueueUnavailableError("Unable to dispatch ingestion job to Redis/ARQ") from exc
        return job

    if mode != "background":
        _mark_dispatch_failed(db, job, "INGESTION_QUEUE_MODE must be 'arq' or 'background'.")
        raise QueueUnavailableError("Invalid ingestion queue mode")
    if _is_production():
        _mark_dispatch_failed(db, job, "In-process BackgroundTasks are disabled in production.")
        raise QueueUnavailableError("Production ingestion requires Redis/ARQ")

    if background_tasks:
        handler = execute_crawl_job if job_type in {"crawl", "recrawl"} else execute_document_job
        background_tasks.add_task(handler, job_uuid, bot_id, organization_id, document_id)
    return job


def get_job_status(
    db: Session,
    job_id: str,
    bot_id: int,
    organization_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    job = db.query(IngestionJob).filter(IngestionJob.job_id == job_id).first()
    if not job or job.bot_id != bot_id:
        return None
    if organization_id is None or job.organization_id != organization_id:
        return None
    return serialize_customer_job(db, job)


RETRYABLE_ERROR_CODES = {
    "QUEUE_UNAVAILABLE",
    "RATE_LIMIT_EXCEEDED",
    "SERVICE_UNAVAILABLE",
    "TIMEOUT",
    "WORKER_TIMEOUT",
}
ACTIVE_JOB_STATUSES = {"queued", "crawling", "processing", "embedding", "validating"}


def _safe_url(value: object) -> str:
    if not isinstance(value, str):
        return ""
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return ""
        sensitive = {"token", "key", "api_key", "apikey", "password", "secret", "signature", "sig"}
        query = urlencode([(key, val) for key, val in parse_qsl(parsed.query) if key.lower() not in sensitive])
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))
    except Exception:
        return ""


def _safe_url_reason(reason: object, *, failed: bool) -> str:
    value = str(reason or "").lower()
    mappings = [
        ("external_domain", "External domain"),
        ("depth", "Depth limit reached"),
        ("max_pages", "Crawl page limit reached"),
        ("limit", "Crawl limit reached"),
        ("extension", "Unsupported file type"),
        ("auth", "Excluded sign-in or account path"),
        ("cart", "Excluded cart or checkout path"),
        ("session", "Excluded session-specific URL"),
        ("robots", "Blocked by site crawl policy"),
        ("404", "Page was not found"),
        ("403", "Page access was denied"),
        ("429", "Page request was rate limited"),
        ("timeout", "Page request timed out"),
    ]
    for marker, label in mappings:
        if marker in value:
            return label
    return "Page crawl failed" if failed else "URL was not eligible for this crawl"


def _crawl_coverage(job: IngestionJob, crawl: WebsiteCrawl | None) -> dict[str, Any] | None:
    audit = (crawl.audit_metadata if crawl else job.audit_metadata) or {}
    is_crawl = job.job_type in {"crawl", "recrawl"} or crawl is not None
    if not is_crawl:
        return None
    skipped = audit.get("skipped_urls") if isinstance(audit.get("skipped_urls"), dict) else {}
    failed = audit.get("failed_urls") if isinstance(audit.get("failed_urls"), dict) else {}
    url_results = [
        {"url": safe_url, "result": "skipped", "reason": _safe_url_reason(reason, failed=False)}
        for url, reason in skipped.items()
        if (safe_url := _safe_url(url))
    ] + [
        {"url": safe_url, "result": "failed", "reason": _safe_url_reason(reason, failed=True)}
        for url, reason in failed.items()
        if (safe_url := _safe_url(url))
    ]
    discovered = int(crawl.pages_discovered if crawl else job.pages_discovered or 0)
    eligible = int(crawl.pages_eligible if crawl else audit.get("eligible_urls") or 0)
    crawled = int(crawl.pages_crawled if crawl else job.pages_crawled or 0)
    indexed = int(audit.get("stored_documents") or job.documents_created or 0)
    measured_coverage = crawl.coverage_percent if crawl and eligible > 0 else None
    return {
        "discovered": discovered,
        "eligible": eligible,
        "crawled": crawled,
        "indexed": indexed,
        "skipped": int(crawl.pages_skipped if crawl else len(skipped)),
        "failed": int(crawl.pages_failed if crawl else len(failed)),
        "duplicates": int(crawl.duplicate_urls_removed if crawl else audit.get("duplicate_urls_removed") or 0),
        "maximum_depth": int(crawl.max_depth_reached if crawl else audit.get("max_depth_reached") or 0),
        "coverage_percent": float(measured_coverage) if measured_coverage is not None else None,
        "documents": indexed,
        "chunks": int(crawl.chunks_created if crawl else job.chunks_created or 0),
        "url_results": url_results,
    }


def serialize_customer_job(db: Session, job: IngestionJob) -> Dict[str, Any]:
    document = db.query(Document).filter(Document.id == job.document_id).first() if job.document_id else None
    website = db.query(Website).filter(Website.id == job.website_id).first() if job.website_id else None
    crawl = db.query(WebsiteCrawl).filter(WebsiteCrawl.id == job.crawl_id).first() if job.crawl_id else None
    active_crawl = (
        db.query(WebsiteCrawl).filter(WebsiteCrawl.id == website.active_crawl_id).first()
        if website and website.active_crawl_id else None
    )
    status = job.status
    if status == "queued" and job.current_stage == "retry_wait":
        status = "retrying"
    elif status == "cancelled" and job.current_stage == "cancelling":
        status = "cancelling"
    source_name = (document.title or document.filename) if document else (website.domain if website else "Knowledge source")
    source_url = _safe_url(document.source_url if document else (website.root_url if website else None)) or None
    safe_errors = {
        "PLAN_QUOTA_EXCEEDED": "The crawl was not activated because it would exceed your plan. Your existing knowledge remains active.",
        "QUEUE_UNAVAILABLE": "The ingestion queue is unavailable. Try again after worker readiness is restored.",
        "RATE_LIMIT_EXCEEDED": "The provider rate limit was reached. This job can be retried.",
        "SERVICE_UNAVAILABLE": "A required provider was temporarily unavailable. This job can be retried.",
        "TIMEOUT": "A website or provider took too long to respond. This job can be retried.",
        "WORKER_TIMEOUT": "The worker stopped reporting progress. This job can be retried safely.",
        "SSRF_BLOCKED": "The requested URL targets a disallowed network address.",
        "NOT_FOUND": "The requested website or document could not be found.",
        "TENANT_MISMATCH": "The knowledge operation was not authorized for this workspace.",
        "CANCELLED": "The knowledge operation was cancelled.",
        "INTERNAL_PROCESSING_ERROR": "Knowledge processing encountered an error.",
    }
    return {
        "job_id": job.job_id,
        "bot_id": job.bot_id,
        "source_name": source_name,
        "source_url": source_url,
        "ingestion_type": "website" if job.job_type in {"crawl", "recrawl"} else "upload",
        "status": status,
        "stage": status if status in {"retrying", "cancelling"} else job.current_stage,
        # Internal milestone numbers are not measured completion percentages.
        "progress_percent": 100 if job.status == "ready" else None,
        "attempt_number": max(1, int(job.attempt_count or 0)),
        "retryable": job.status == "failed" and job.error_code in RETRYABLE_ERROR_CODES,
        "cancellable": job.status in ACTIVE_JOB_STATUSES,
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "error_code": job.error_code,
        "error_message": safe_errors.get(job.error_code, "Knowledge processing encountered an error.") if job.error_code else None,
        "crawl_coverage": _crawl_coverage(job, crawl),
        "active_version": active_crawl.version if active_crawl else None,
        "candidate_version": crawl.version if crawl else None,
        "version_state": crawl.status if crawl else ("active" if job.status == "ready" else None),
        "chunks_created": job.chunks_created,
    }


def list_job_statuses(db: Session, bot_id: int, organization_id: int, limit: int = 25) -> list[Dict[str, Any]]:
    jobs = db.query(IngestionJob).filter(
        IngestionJob.bot_id == bot_id,
        IngestionJob.organization_id == organization_id,
    ).order_by(IngestionJob.created_at.desc()).limit(max(1, min(limit, 100))).all()
    return [serialize_customer_job(db, job) for job in jobs]


def retry_job(
    db: Session,
    job_id: str,
    bot_id: int,
    organization_id: int,
    background_tasks: Optional[BackgroundTasks] = None,
) -> IngestionJob | None:
    job = db.query(IngestionJob).filter(IngestionJob.job_id == job_id).with_for_update().first()
    if not job or job.bot_id != bot_id or job.organization_id != organization_id:
        return None
    if job.status in ACTIVE_JOB_STATUSES:
        db.commit()
        return job
    if job.status != "failed" or job.error_code not in RETRYABLE_ERROR_CODES or not job.document_id:
        db.rollback()
        return None
    next_attempt = max(1, int(job.attempt_count or 0) + 1)
    job.status = "queued"
    job.current_stage = "retry_wait"
    job.progress_percent = 0
    job.started_at = None
    job.completed_at = None
    job.error_code = None
    job.error_message = None
    job.cancellation_requested_at = None
    job.attempt_count = next_attempt
    job.arq_job_id = f"{job.job_id}_manual_{next_attempt}"
    job.last_heartbeat = datetime.utcnow()
    db.commit()
    mode = get_queue_mode()
    if mode == "arq":
        try:
            _run_async(_dispatch_to_arq(job))
        except Exception as exc:
            _mark_dispatch_failed(db, job, "The ingestion queue is unavailable. Retry after worker readiness is restored.")
            raise QueueUnavailableError("Unable to dispatch retry to Redis/ARQ") from exc
    elif mode == "background" and not _is_production() and background_tasks:
        handler = execute_crawl_job if job.job_type in {"crawl", "recrawl"} else execute_document_job
        background_tasks.add_task(handler, job.job_id, job.bot_id, job.organization_id, job.document_id)
    else:
        _mark_dispatch_failed(db, job, "The ingestion queue is unavailable for retry.")
        raise QueueUnavailableError("Retry requires a configured executor")
    return job


def cancel_job(
    db: Session,
    job_id: str,
    bot_id: int,
    organization_id: Optional[int] = None,
) -> bool:
    job = db.query(IngestionJob).filter(IngestionJob.job_id == job_id).with_for_update().first()
    if not job or job.bot_id != bot_id:
        return False
    if organization_id is None or job.organization_id != organization_id:
        return False
    if job.status in ("queued", "crawling", "processing", "embedding", "validating"):
        was_queued = job.status == "queued"
        job.status = "cancelled"
        job.current_stage = "cancelled" if was_queued else "cancelling"
        job.cancellation_requested_at = datetime.utcnow()
        job.completed_at = datetime.utcnow() if was_queued else None
        job.last_heartbeat = datetime.utcnow()
        db.commit()
        return True
    db.rollback()
    return False


def acknowledge_job_cancellation(db: Session, job_id: str) -> bool:
    job = db.query(IngestionJob).filter(IngestionJob.job_id == job_id).with_for_update().first()
    if not job or job.status != "cancelled":
        db.rollback()
        return False
    job.current_stage = "cancelled"
    job.completed_at = datetime.utcnow()
    job.last_heartbeat = datetime.utcnow()
    db.commit()
    return True
