"""Real Redis + separate ARQ worker + real embedding provider acceptance proof."""

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

from redis import Redis  # noqa: E402

from database.connection import SessionLocal  # noqa: E402
from database.models import Bot, Chunk, Customer, Document, IngestionJob, Organization  # noqa: E402
from services.queue_service import enqueue_ingestion_job  # noqa: E402
from workers.worker import WORKER_HEARTBEAT_KEY  # noqa: E402


def main() -> None:
    redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    assert redis.ping() is True
    heartbeat = redis.get(WORKER_HEARTBEAT_KEY)
    assert heartbeat, "Separate ARQ worker heartbeat is absent"

    suffix = uuid.uuid4().hex[:10]
    db = SessionLocal()
    org = customer = bot = document = job = None
    try:
        org = Organization(name=f"Phase I ARQ {suffix}", slug=f"phase-i-arq-{suffix}")
        customer = Customer(name=f"Phase I ARQ {suffix}", api_key=f"phase_i_arq_{suffix}")
        db.add_all([org, customer])
        db.commit()
        db.refresh(org)
        db.refresh(customer)

        bot = Bot(
            name=f"Phase I ARQ Bot {suffix}",
            customer_id=customer.id,
            organization_id=org.id,
            provider="gemini",
            model_name="gemini-2.5-flash",
            system_prompt="Answer from the indexed acceptance facts.",
            status="active",
        )
        db.add(bot)
        db.commit()
        db.refresh(bot)

        document = Document(
            bot_id=bot.id,
            organization_id=org.id,
            filename="phase-i-live-arq.txt",
            title="Phase I Live ARQ Facts",
            source_type="text",
            raw_text=(
                "The Atlas Support plan costs 49 dollars per month. "
                "It includes priority email support and a two-hour response target. "
                "Customers can subscribe at https://example.com/atlas-support."
            ),
            logical_size_bytes=180,
            processing_status="pending",
            status="staging",
            metadata_json={"phase": "I", "proof": "real_arq"},
        )
        db.add(document)
        db.commit()
        db.refresh(document)

        job = enqueue_ingestion_job(
            db=db,
            bot_id=bot.id,
            organization_id=org.id,
            document_id=document.id,
            job_type="document_upload",
        )
        job_id = job.job_id
        print("ENQUEUED", {"job_id": job_id, "status": job.status})

        deadline = time.monotonic() + 180
        observed = []
        while time.monotonic() < deadline:
            db.expire_all()
            current = db.query(IngestionJob).filter(IngestionJob.job_id == job_id).one()
            state = (current.status, current.current_stage)
            if not observed or observed[-1] != state:
                observed.append(state)
                print("STATE", state)
            if current.status in {"ready", "failed", "cancelled"}:
                break
            time.sleep(1)
        else:
            raise AssertionError("Timed out waiting for separate ARQ worker")

        assert current.status == "ready", {
            "status": current.status,
            "error_code": current.error_code,
            "error_message": current.error_message,
        }
        chunks = db.query(Chunk).filter(Chunk.document_id == document.id).all()
        assert chunks
        providers = sorted({chunk.embedding_provider for chunk in chunks})
        models = sorted({chunk.embedding_model for chunk in chunks})
        assert "deterministic" not in providers
        assert all(len(chunk.embedding) == 768 for chunk in chunks)
        print(
            "PASS real_redis_arq_embedding",
            {
                "states": observed,
                "chunks": len(chunks),
                "providers": providers,
                "models": models,
                "worker_heartbeat": bool(redis.get(WORKER_HEARTBEAT_KEY)),
            },
        )
    finally:
        if bot is not None:
            db.query(Chunk).filter(Chunk.bot_id == bot.id).delete(synchronize_session=False)
            db.query(IngestionJob).filter(IngestionJob.bot_id == bot.id).delete(synchronize_session=False)
            db.query(Document).filter(Document.bot_id == bot.id).delete(synchronize_session=False)
            db.delete(bot)
        if customer is not None:
            db.delete(customer)
        if org is not None:
            db.delete(org)
        db.commit()
        db.close()
        redis.close()


if __name__ == "__main__":
    main()
