"""Live Firecrawl job submitted through Redis and consumed by ARQ."""

from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ["REDIS_URL"] = "redis://127.0.0.1:6379/0"
os.environ["INGESTION_QUEUE_MODE"] = "arq"
os.environ["ARQ_QUEUE_NAME"] = "ingestion"
os.environ["ALLOW_DETERMINISTIC_EMBEDDING_FALLBACK"] = "false"

from database.connection import SessionLocal  # noqa: E402
from database.models import (  # noqa: E402
    Bot, Chunk, Customer, Document, IngestionJob, Organization, Website, WebsiteCrawl,
)
from services.queue_service import enqueue_ingestion_job  # noqa: E402


def enqueue(target_url: str) -> str:
    suffix = uuid.uuid4().hex[:10]
    db = SessionLocal()
    try:
        org = Organization(name=f"Phase I Firecrawl {suffix}", slug=f"phase-i-firecrawl-{suffix}")
        customer = Customer(name=f"Phase I Firecrawl {suffix}", api_key=f"phase_i_fc_{suffix}")
        db.add_all([org, customer])
        db.commit()
        db.refresh(org)
        db.refresh(customer)
        bot = Bot(
            name=f"Phase I Firecrawl Bot {suffix}",
            customer_id=customer.id,
            organization_id=org.id,
            provider="gemini",
            model_name="gemini-2.5-flash",
            status="active",
        )
        db.add(bot)
        db.commit()
        db.refresh(bot)
        document = Document(
            bot_id=bot.id,
            organization_id=org.id,
            filename="phase-i-live-website",
            title=target_url,
            source_type="website",
            source_url=target_url,
            raw_text="",
            logical_size_bytes=0,
            processing_status="pending",
            status="staging",
            metadata_json={"phase": "I", "crawler": "firecrawl"},
        )
        db.add(document)
        db.commit()
        db.refresh(document)
        job = enqueue_ingestion_job(
            db=db,
            bot_id=bot.id,
            organization_id=org.id,
            document_id=document.id,
            job_type="crawl",
        )
        print(f"JOB_ID={job.job_id}")
        print("ENQUEUED", {"status": job.status, "bot_id": bot.id, "document_id": document.id})
        return job.job_id
    finally:
        db.close()


def poll(job_id: str) -> None:
    db = SessionLocal()
    job = db.query(IngestionJob).filter(IngestionJob.job_id == job_id).one()
    bot_id = job.bot_id
    organization_id = job.organization_id
    observed = []
    try:
        deadline = time.monotonic() + 360
        while time.monotonic() < deadline:
            db.expire_all()
            current = db.query(IngestionJob).filter(IngestionJob.job_id == job_id).one()
            state = (current.status, current.current_stage)
            if not observed or state != observed[-1]:
                observed.append(state)
                print("STATE", state)
            if current.status in {"ready", "failed", "cancelled"}:
                break
            time.sleep(2)
        else:
            raise AssertionError("Timed out waiting for Firecrawl ARQ job")

        assert current.status == "ready", {
            "status": current.status,
            "error_code": current.error_code,
            "error_message": current.error_message,
        }
        website = db.query(Website).filter(Website.bot_id == bot_id).one()
        active = db.query(WebsiteCrawl).filter(WebsiteCrawl.id == website.active_crawl_id).one()
        documents = db.query(Document).filter(
            Document.bot_id == bot_id,
            Document.status == "ready",
        ).all()
        chunks = db.query(Chunk).filter(Chunk.bot_id == bot_id, Chunk.status == "ready").all()
        providers = sorted({chunk.embedding_provider for chunk in chunks})
        models = sorted({chunk.embedding_model for chunk in chunks})
        audit = active.audit_metadata or {}
        assert len(documents) >= 2, "Firecrawl did not return multiple pages"
        assert chunks
        assert active.status == "ready"
        assert current.documents_created == len(documents)
        assert "deterministic" not in providers
        assert audit.get("stored_documents") == len(documents)
        print(
            "PASS live_firecrawl_arq",
            {
                "states": observed,
                "pages_discovered": active.pages_discovered,
                "pages_eligible": active.pages_eligible,
                "pages_crawled": active.pages_crawled,
                "documents": len(documents),
                "chunks": len(chunks),
                "embedding_providers": providers,
                "embedding_models": models,
                "active_version": active.version,
                "crawler": "firecrawl",
            },
        )
    finally:
        db.query(Chunk).filter(Chunk.bot_id == bot_id).delete(synchronize_session=False)
        db.query(IngestionJob).filter(IngestionJob.bot_id == bot_id).delete(synchronize_session=False)
        db.query(Document).filter(Document.bot_id == bot_id).delete(synchronize_session=False)
        db.query(WebsiteCrawl).filter(WebsiteCrawl.bot_id == bot_id).delete(synchronize_session=False)
        db.query(Website).filter(Website.bot_id == bot_id).delete(synchronize_session=False)
        bot = db.query(Bot).filter(Bot.id == bot_id).one()
        customer_id = bot.customer_id
        db.delete(bot)
        db.query(Customer).filter(Customer.id == customer_id).delete(synchronize_session=False)
        db.query(Organization).filter(Organization.id == organization_id).delete(synchronize_session=False)
        db.commit()
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in {"enqueue", "poll"}:
        raise SystemExit("Usage: test_phase_i_live_firecrawl_arq.py enqueue <url> | poll <job_id>")
    if sys.argv[1] == "enqueue":
        enqueue(sys.argv[2])
    else:
        poll(sys.argv[2])
