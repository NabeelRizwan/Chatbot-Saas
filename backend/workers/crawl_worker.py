from datetime import datetime
from typing import Any, Dict

from database.connection import SessionLocal
from database.models import Bot, Document, IngestionJob
from services.document_processing_service import process_document
from workers.job_models import sanitize_customer_error, transition_job_state


def execute_crawl_job(job_id: str, bot_id: int, organization_id: int | None, document_id: int) -> Dict[str, Any]:
    """
    Worker handler for durable website crawl jobs.
    Validates tenant scope, enforces the state machine atomically, and orchestrates existing Crawl4AI ingestion.
    """
    db = SessionLocal()
    try:
        job = db.query(IngestionJob).filter(IngestionJob.job_id == job_id).first()
        if not job:
            return {"status": "error", "message": f"Job {job_id} not found."}

        # Check if already cancelled or finished
        if job.status in ("cancelled", "ready", "failed"):
            if job.status == "cancelled" and job.current_stage == "cancelling":
                from services.queue_service import acknowledge_job_cancellation
                acknowledge_job_cancellation(db, job_id)
            return {"status": job.status, "message": f"Job is already in terminal state: {job.status}"}

        if (
            organization_id is None
            or job.bot_id != bot_id
            or job.organization_id != organization_id
            or job.document_id != document_id
        ):
            transition_job_state(
                db, job_id, "failed", stage="failed",
                error_code="TENANT_MISMATCH", error_message="Job scope does not match worker authorization."
            )
            return {"status": "failed", "error_code": "TENANT_MISMATCH"}

        # 1. Tenant Boundary Validation
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            transition_job_state(
                db, job_id, "failed", stage="failed",
                error_code="NOT_FOUND", error_message=f"Document {document_id} not found."
            )
            return {"status": "failed", "error_code": "NOT_FOUND"}

        if doc.bot_id != bot_id:
            transition_job_state(
                db, job_id, "failed", stage="failed",
                error_code="TENANT_MISMATCH", error_message="Document bot_id does not match job authorization."
            )
            return {"status": "failed", "error_code": "TENANT_MISMATCH"}

        if doc.organization_id != organization_id:
            transition_job_state(
                db, job_id, "failed", stage="failed",
                error_code="TENANT_MISMATCH", error_message="Document organization_id does not match job authorization."
            )
            return {"status": "failed", "error_code": "TENANT_MISMATCH"}

        bot = db.query(Bot).filter(Bot.id == bot_id).first()
        if not bot or bot.organization_id != organization_id:
            transition_job_state(
                db, job_id, "failed", stage="failed",
                error_code="TENANT_MISMATCH", error_message="Bot organization_id does not match job authorization."
            )
            return {"status": "failed", "error_code": "TENANT_MISMATCH"}

        # 2. State: CRAWLING
        transition_job_state(db, job_id, "crawling", stage="crawling", progress_percent=20)

        # Check if cancelled mid-flight
        db.refresh(job)
        if job.status == "cancelled":
            from services.queue_service import acknowledge_job_cancellation
            acknowledge_job_cancellation(db, job_id)
            return {"status": "cancelled", "message": "Job cancelled."}

        # 3. State: PROCESSING
        transition_job_state(db, job_id, "processing", stage="processing", progress_percent=50)

        # Execute existing production processing (handles Crawl4AI, hashing, chunking, embeddings, zero-downtime)
        processed_doc = process_document(db, document_id, job_id=job_id)

        # Check if cancelled mid-flight
        db.refresh(job)
        if job.status == "cancelled":
            from services.queue_service import acknowledge_job_cancellation
            acknowledge_job_cancellation(db, job_id)
            return {"status": "cancelled", "message": "Job cancelled."}
        if job.status == "failed":
            return {
                "status": "failed",
                "error_code": job.error_code,
                "error_message": job.error_message,
            }
        if job.status == "ready":
            return {
                "status": "ready",
                "document_id": processed_doc.id,
                "chunks_created": job.chunks_created,
            }

        # 4. State: VALIDATING
        transition_job_state(db, job_id, "validating", stage="validating", progress_percent=85)

        # 5. State: READY or FAILED based on document processing status
        if processed_doc.status in ("ready", "completed") or processed_doc.processing_status == "completed":
            transition_job_state(
                db,
                job_id,
                "ready",
                stage="ready",
                progress_percent=100,
                documents_created=1,
                chunks_created=processed_doc.chunk_count or 0,
                embeddings_created=processed_doc.chunk_count or 0,
            )
            return {
                "status": "ready",
                "document_id": processed_doc.id,
                "chunks_created": processed_doc.chunk_count,
            }
        else:
            err_code, safe_msg = sanitize_customer_error(
                Exception(processed_doc.processing_error or "Crawl processing failed")
            )
            transition_job_state(
                db,
                job_id,
                "failed",
                stage="failed",
                error_code=err_code,
                error_message=safe_msg,
            )
            return {"status": "failed", "error_code": err_code, "error_message": safe_msg}

    except Exception as exc:
        err_code, safe_msg = sanitize_customer_error(exc)
        transition_job_state(
            db,
            job_id,
            "failed",
            stage="failed",
            error_code=err_code,
            error_message=safe_msg,
        )
        return {"status": "failed", "error_code": err_code, "error_message": safe_msg}
    finally:
        db.close()
