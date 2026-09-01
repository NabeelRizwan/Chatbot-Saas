import asyncio
import contextlib
import os
from datetime import datetime, timedelta
from typing import Any, Dict
from arq import Retry, cron
from arq.connections import RedisSettings

from database.connection import SessionLocal
from database.models import IngestionJob
from workers.crawl_worker import execute_crawl_job
from workers.embedding_worker import execute_document_job
from workers.maintenance_worker import recover_stale_jobs, reconcile_message_reservations


WORKER_HEARTBEAT_KEY = "chatbot-saas:ingestion-worker:heartbeat"


async def _worker_heartbeat(ctx: Dict[str, Any]) -> None:
    interval = max(5, int(os.getenv("WORKER_HEARTBEAT_INTERVAL", "15")))
    ttl = max(interval * 3, int(os.getenv("WORKER_HEARTBEAT_TTL", "60")))
    while True:
        await ctx["redis"].set(WORKER_HEARTBEAT_KEY, datetime.utcnow().isoformat(), ex=ttl)
        await asyncio.sleep(interval)


async def crawl_task(ctx: Dict[str, Any], job_id: str, bot_id: int, organization_id: int | None, document_id: int) -> Dict[str, Any]:
    """ARQ task for website crawling."""
    _record_attempt(job_id, int(ctx.get("job_try") or 1))
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None, execute_crawl_job, job_id, bot_id, organization_id, document_id
    )
    _retry_transient_result(ctx, job_id, result)
    return result


async def document_task(ctx: Dict[str, Any], job_id: str, bot_id: int, organization_id: int | None, document_id: int) -> Dict[str, Any]:
    """ARQ task for document parsing & embedding."""
    _record_attempt(job_id, int(ctx.get("job_try") or 1))
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None, execute_document_job, job_id, bot_id, organization_id, document_id
    )
    _retry_transient_result(ctx, job_id, result)
    return result


def _record_attempt(job_id: str, attempt: int) -> None:
    db = SessionLocal()
    try:
        job = db.query(IngestionJob).filter(IngestionJob.job_id == job_id).first()
        if job:
            job.attempt_count = max(int(job.attempt_count or 0), attempt)
        db.commit()
    finally:
        db.close()


def _retry_transient_result(ctx: Dict[str, Any], job_id: str, result: Dict[str, Any]) -> None:
    retryable_codes = {"RATE_LIMIT_EXCEEDED", "TIMEOUT", "SERVICE_UNAVAILABLE"}
    if result.get("status") != "failed" or result.get("error_code") not in retryable_codes:
        return
    attempt = int(ctx.get("job_try") or 1)
    max_tries = int(os.getenv("WORKER_MAX_TRIES", "3"))
    if attempt >= max_tries:
        return
    db = SessionLocal()
    try:
        job = db.query(IngestionJob).filter(IngestionJob.job_id == job_id).with_for_update().first()
        if not job or job.status == "cancelled":
            return
        job.status = "queued"
        job.current_stage = "retry_wait"
        job.progress_percent = 0
        job.completed_at = None
        job.attempt_count = attempt
        db.commit()
    finally:
        db.close()
    raise Retry(defer=min(60, 2 ** attempt))


async def maintenance_task(ctx: Dict[str, Any]) -> list[str]:
    """ARQ periodic maintenance task for stale job recovery."""
    redispatched = await redispatch_stale_queued_jobs(ctx["redis"])
    loop = asyncio.get_running_loop()
    recovered = await loop.run_in_executor(None, recover_stale_jobs)
    released = await loop.run_in_executor(None, reconcile_message_reservations)
    return (
        [f"redispatched:{job_id}" for job_id in redispatched]
        + recovered
        + [f"released-reservation:{reservation_id}" for reservation_id in released]
    )


async def redispatch_stale_queued_jobs(redis, max_age_seconds: int = 60) -> list[str]:
    """Repair the durable-commit/Redis-dispatch crash window using ARQ job IDs."""
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(seconds=max_age_seconds)
        jobs = (
            db.query(IngestionJob)
            .filter(
                IngestionJob.status == "queued",
                IngestionJob.last_heartbeat < cutoff,
            )
            .all()
        )
        payloads = [
            (job.job_id, job.job_type, job.bot_id, job.organization_id, job.document_id)
            for job in jobs
            if job.document_id is not None
        ]
    finally:
        db.close()

    redispatched: list[str] = []
    for job_id, job_type, bot_id, organization_id, document_id in payloads:
        function_name = "crawl_task" if job_type in {"crawl", "recrawl"} else "document_task"
        await redis.enqueue_job(
            function_name,
            job_id,
            bot_id,
            organization_id,
            document_id,
            _job_id=job_id,
            _queue_name=os.getenv("ARQ_QUEUE_NAME", "ingestion"),
        )
        redispatched.append(job_id)

    if redispatched:
        db = SessionLocal()
        try:
            db.query(IngestionJob).filter(IngestionJob.job_id.in_(redispatched)).update(
                {"last_heartbeat": datetime.utcnow(), "updated_at": datetime.utcnow()},
                synchronize_session=False,
            )
            db.commit()
        finally:
            db.close()
    return redispatched


async def startup(ctx: Dict[str, Any]) -> None:
    await ctx["redis"].set(
        WORKER_HEARTBEAT_KEY,
        datetime.utcnow().isoformat(),
        ex=max(60, int(os.getenv("WORKER_HEARTBEAT_TTL", "60"))),
    )
    ctx["worker_heartbeat_task"] = asyncio.create_task(_worker_heartbeat(ctx))
    print("[ARQ WORKER] Worker process initialized and ready for jobs.")


async def shutdown(ctx: Dict[str, Any]) -> None:
    task = ctx.get("worker_heartbeat_task")
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    print("[ARQ WORKER] Worker process shutting down gracefully.")


class WorkerSettings:
    """Configuration settings for ARQ worker process."""
    redis_settings = RedisSettings.from_dsn(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    functions = [crawl_task, document_task]
    cron_jobs = [cron(maintenance_task, minute=set(range(0, 60, 5)), run_at_startup=True)]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = int(os.getenv("WORKER_MAX_JOBS", "10"))
    job_timeout = int(os.getenv("WORKER_JOB_TIMEOUT", "1800"))  # 30 mins
    max_tries = int(os.getenv("WORKER_MAX_TRIES", "3"))
    retry_jobs = True
    keep_result = int(os.getenv("WORKER_KEEP_RESULT_SECONDS", "3600"))
    health_check_interval = int(os.getenv("WORKER_HEALTHCHECK_INTERVAL", "30"))
    queue_name = os.getenv("ARQ_QUEUE_NAME", "ingestion")
