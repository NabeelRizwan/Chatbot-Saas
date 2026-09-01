import asyncio
import datetime
import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import BackgroundTasks

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

from database.connection import SessionLocal, init_db
from database.models import Bot, Chunk, Customer, Document, IngestionJob, Organization, Website, WebsiteCrawl
from services.document_processing_service import UPLOAD_DIR, process_document, remove_unreferenced_upload
from services.embedding_service import (
    EmbeddingProviderUnavailable,
    generate_embedding,
    generate_embeddings_batch,
)
from services.firecrawl_service import CrawlAuditReport, FirecrawlError, Page
from services.queue_service import QueueUnavailableError, cancel_job, enqueue_ingestion_job
from services.rag_service import clear_retrieval_cache, retrieve_relevant_chunks
from workers.embedding_worker import execute_document_job
from workers.crawl_worker import execute_crawl_job
from workers.maintenance_worker import recover_stale_jobs
from workers.worker import redispatch_stale_queued_jobs
import fakeredis
import fakeredis.aioredis
from utils.redis_client import set_redis_override


class TestPhaseDIngestionLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.fake_redis = fakeredis.FakeRedis()
        cls.fake_async_redis = fakeredis.aioredis.FakeRedis()
        set_redis_override(cls.fake_redis, cls.fake_async_redis)

    @classmethod
    def tearDownClass(cls):
        set_redis_override(None, None)

    def setUp(self):
        self.db = SessionLocal()
        self.uid = uuid.uuid4().hex[:10]
        self.org = Organization(name=f"Phase D {self.uid}", slug=f"phase-d-{self.uid}")
        self.customer = Customer(name=f"Phase D {self.uid}", api_key=f"phase_d_{self.uid}")
        self.db.add_all([self.org, self.customer])
        self.db.commit()
        self.bot = Bot(
            name=f"Phase D Bot {self.uid}",
            customer_id=self.customer.id,
            organization_id=self.org.id,
        )
        self.db.add(self.bot)
        self.db.commit()
        clear_retrieval_cache(self.bot.id)

    def tearDown(self):
        self.db.rollback()
        self.db.query(IngestionJob).filter(IngestionJob.bot_id == self.bot.id).delete()
        self.db.query(Chunk).filter(Chunk.bot_id == self.bot.id).delete()
        self.db.query(Document).filter(Document.bot_id == self.bot.id).delete()
        self.db.query(WebsiteCrawl).filter(WebsiteCrawl.bot_id == self.bot.id).delete()
        self.db.query(Website).filter(Website.bot_id == self.bot.id).delete()
        self.db.query(Bot).filter(Bot.id == self.bot.id).delete()
        self.db.query(Customer).filter(Customer.id == self.customer.id).delete()
        self.db.query(Organization).filter(Organization.id == self.org.id).delete()
        self.db.commit()
        self.db.close()
        clear_retrieval_cache(self.bot.id)

    def _document(self, *, source_type="text", url=None, raw_text="durable active knowledge"):
        document = Document(
            bot_id=self.bot.id,
            organization_id=self.org.id,
            filename=f"source-{uuid.uuid4().hex[:8]}",
            source_type=source_type,
            source_url=url,
            raw_text=raw_text,
            title="Phase D source",
            status="staging",
            processing_status="pending",
        )
        self.db.add(document)
        self.db.commit()
        return document

    def test_arq_dispatch_is_real_and_production_background_is_rejected(self):
        document = self._document()
        pool = MagicMock()
        pool.enqueue_job = AsyncMock(return_value=object())
        pool.aclose = AsyncMock()
        with patch.dict(
            os.environ,
            {"APP_ENV": "production", "INGESTION_QUEUE_MODE": "arq", "ARQ_QUEUE_NAME": "ingestion"},
        ), patch("services.queue_service.get_redis_pool", AsyncMock(return_value=pool)):
            job = enqueue_ingestion_job(
                self.db,
                self.bot.id,
                self.org.id,
                document.id,
                job_type="document_upload",
            )
        pool.enqueue_job.assert_awaited_once_with(
            "document_task",
            job.job_id,
            self.bot.id,
            self.org.id,
            document.id,
            _job_id=job.job_id,
            _queue_name="ingestion",
        )
        pool.aclose.assert_awaited_once()
        self.assertEqual(job.arq_job_id, job.job_id)
        self.assertEqual(job.status, "queued")
        job.last_heartbeat = datetime.datetime.utcnow() - datetime.timedelta(minutes=5)
        self.db.commit()
        repair_pool = MagicMock()
        repair_pool.enqueue_job = AsyncMock(return_value=None)
        repaired = asyncio.run(redispatch_stale_queued_jobs(repair_pool, max_age_seconds=60))
        self.assertEqual(repaired, [job.job_id])
        repair_pool.enqueue_job.assert_awaited_once_with(
            "document_task",
            job.job_id,
            self.bot.id,
            self.org.id,
            document.id,
            _job_id=job.job_id,
            _queue_name="ingestion",
        )

        blocked_document = self._document(raw_text="must not run in API process")
        background = BackgroundTasks()
        with patch.dict(
            os.environ,
            {"APP_ENV": "production", "INGESTION_QUEUE_MODE": "background"},
        ):
            with self.assertRaises(QueueUnavailableError):
                enqueue_ingestion_job(
                    self.db,
                    self.bot.id,
                    self.org.id,
                    blocked_document.id,
                    background_tasks=background,
                )
        self.assertEqual(background.tasks, [])
        failed = self.db.query(IngestionJob).filter(IngestionJob.document_id == blocked_document.id).one()
        self.assertEqual(failed.error_code, "QUEUE_UNAVAILABLE")

    def test_atomic_recrawl_failure_and_missing_page_retirement(self):
        root_url = f"https://phase-d-{self.uid}.example"
        root = self._document(source_type="website", url=root_url, raw_text="")
        first_pages = [
            Page(url=root_url, title="Home v1", markdown="Active version one durable pricing is 10 credits."),
            Page(url=f"{root_url}/removed", title="Removed", markdown="This page exists only in version one."),
        ]
        first_audit = CrawlAuditReport(
            seed_url=root_url,
            discovered_urls=4,
            eligible_urls=3,
            crawled_urls=2,
            stored_documents=2,
            duplicate_urls_removed=1,
            max_depth_reached=1,
            skipped_urls={f"{root_url}/login": "disallowed_path_auth"},
        )
        with patch("services.document_processing_service.crawl_website", return_value=(first_pages, first_audit)):
            process_document(self.db, root.id)

        website = self.db.query(Website).filter(Website.root_url == root_url).one()
        first_active = website.active_crawl_id
        removed = self.db.query(Document).filter(Document.source_url == f"{root_url}/removed").one()
        self.assertEqual(removed.status, "ready")

        second_pages = [
            Page(url=root_url, title="Home v2", markdown="Replacement version two durable pricing is 20 credits."),
        ]
        second_audit = CrawlAuditReport(
            seed_url=root_url,
            discovered_urls=2,
            eligible_urls=1,
            crawled_urls=1,
            stored_documents=1,
            max_depth_reached=0,
        )
        from services import document_processing_service as processing_service

        original_embed = processing_service._embed_in_cancellable_batches
        observed_during_staging = []

        def observe_active_snapshot(*args, **kwargs):
            worker_db = args[0]
            current_website = (
                worker_db.query(Website)
                .filter(Website.id == website.id)
                .populate_existing()
                .one()
            )
            ready_contents = [
                chunk.content
                for chunk in worker_db.query(Chunk).filter(
                    Chunk.website_id == website.id,
                    Chunk.status == "ready",
                )
            ]
            observed_during_staging.append((current_website.active_crawl_id, ready_contents))
            return original_embed(*args, **kwargs)

        with patch(
            "services.document_processing_service.crawl_website",
            return_value=(second_pages, second_audit),
        ), patch(
            "services.document_processing_service._embed_in_cancellable_batches",
            side_effect=observe_active_snapshot,
        ):
            process_document(self.db, root.id)

        self.db.refresh(website)
        self.db.refresh(removed)
        self.assertTrue(observed_during_staging)
        self.assertTrue(all(active_id == first_active for active_id, _ in observed_during_staging))
        self.assertTrue(
            any("version one" in content for _, contents in observed_during_staging for content in contents)
        )
        self.assertNotEqual(website.active_crawl_id, first_active)
        self.assertEqual(self.db.get(WebsiteCrawl, first_active).status, "superseded")
        self.assertEqual(removed.status, "stale")
        active_chunks = self.db.query(Chunk).filter(Chunk.website_id == website.id, Chunk.status == "ready").all()
        self.assertTrue(active_chunks)
        self.assertTrue(all(chunk.crawl_id == website.active_crawl_id for chunk in active_chunks))
        active_crawl = self.db.get(WebsiteCrawl, website.active_crawl_id)
        self.assertEqual(active_crawl.pages_discovered, 2)
        self.assertEqual(active_crawl.pages_eligible, 1)
        self.assertEqual(active_crawl.pages_crawled, 1)
        self.assertIn("coverage_manifest", active_crawl.audit_metadata)

        promoted_before_failure = website.active_crawl_id
        failed_candidate = enqueue_ingestion_job(
            self.db,
            self.bot.id,
            self.org.id,
            root.id,
            job_type="crawl",
            website_id=website.id,
        )
        with patch(
            "services.document_processing_service.crawl_website",
            side_effect=FirecrawlError("provider unavailable", status_code=502),
        ):
            failed_worker_result = execute_crawl_job(
                failed_candidate.job_id,
                self.bot.id,
                self.org.id,
                root.id,
            )
        self.db.refresh(website)
        self.db.refresh(root)
        self.db.refresh(failed_candidate)
        self.assertEqual(failed_worker_result["status"], "failed")
        self.assertEqual(failed_candidate.status, "failed")
        self.assertEqual(root.status, "ready")
        self.assertEqual(website.active_crawl_id, promoted_before_failure)
        self.assertEqual(
            self.db.query(WebsiteCrawl)
            .filter(WebsiteCrawl.website_id == website.id)
            .order_by(WebsiteCrawl.version.desc())
            .first()
            .status,
            "failed",
        )

        cancel_candidate = enqueue_ingestion_job(
            self.db,
            self.bot.id,
            self.org.id,
            root.id,
            job_type="crawl",
            website_id=website.id,
        )
        original_embed = processing_service._embed_in_cancellable_batches

        def cancel_during_embedding(*args, **kwargs):
            cancel_job(self.db, cancel_candidate.job_id, self.bot.id, self.org.id)
            return original_embed(*args, **kwargs)

        with patch(
            "services.document_processing_service.crawl_website",
            return_value=([Page(url=root_url, title="Cancelled", markdown="Must never promote")], second_audit),
        ), patch(
            "services.document_processing_service._embed_in_cancellable_batches",
            side_effect=cancel_during_embedding,
        ):
            cancelled = execute_crawl_job(
                cancel_candidate.job_id,
                self.bot.id,
                self.org.id,
                root.id,
            )
        self.db.refresh(website)
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(website.active_crawl_id, promoted_before_failure)

    def test_staging_and_cross_tenant_chunks_are_not_retrievable(self):
        document = self._document(raw_text="Active alpha contract is available now.")
        process_document(self.db, document.id)
        staging_vector = generate_embedding("UNPROMOTED_SECRET_8472")
        self.db.add(
            Chunk(
                document_id=document.id,
                bot_id=self.bot.id,
                organization_id=self.org.id,
                ingestion_job_id="partial_job",
                chunk_index=999,
                content="UNPROMOTED_SECRET_8472",
                embedding=staging_vector,
                status="staging",
                embedding_provider="deterministic",
                embedding_model="deterministic-hash-v1",
            )
        )
        other_org = Organization(name=f"Other {self.uid}", slug=f"other-{self.uid}")
        other_customer = Customer(name=f"Other {self.uid}", api_key=f"other_{self.uid}")
        self.db.add_all([other_org, other_customer])
        self.db.commit()
        other_bot = Bot(name="Other Bot", organization_id=other_org.id, customer_id=other_customer.id)
        self.db.add(other_bot)
        self.db.commit()
        other_doc = Document(
            bot_id=other_bot.id,
            organization_id=other_org.id,
            filename="other",
            source_type="text",
            raw_text="CROSS_TENANT_SECRET_9921",
            title="other",
            status="ready",
            processing_status="completed",
        )
        self.db.add(other_doc)
        self.db.flush()
        self.db.add(
            Chunk(
                document_id=other_doc.id,
                bot_id=other_bot.id,
                organization_id=other_org.id,
                content="CROSS_TENANT_SECRET_9921",
                embedding=generate_embedding("CROSS_TENANT_SECRET_9921"),
                status="ready",
            )
        )
        self.db.commit()
        retrieved = retrieve_relevant_chunks(self.db, self.bot.id, "UNPROMOTED_SECRET_8472 CROSS_TENANT_SECRET_9921")
        contents = " ".join(item["chunk"].content for item in retrieved)
        self.assertNotIn("UNPROMOTED_SECRET_8472", contents)
        self.assertNotIn("CROSS_TENANT_SECRET_9921", contents)

        self.db.query(Chunk).filter(Chunk.bot_id == other_bot.id).delete()
        self.db.query(Document).filter(Document.bot_id == other_bot.id).delete()
        self.db.delete(other_bot)
        self.db.delete(other_customer)
        self.db.delete(other_org)
        self.db.commit()

    def test_cancel_embedding_failure_retry_and_stale_recovery_are_safe(self):
        document = self._document(raw_text="Stable original knowledge remains retrievable.")
        process_document(self.db, document.id)
        original_ready_ids = {
            chunk.id for chunk in self.db.query(Chunk).filter(Chunk.document_id == document.id, Chunk.status == "ready")
        }
        document.raw_text = "Replacement that must fail embeddings."
        self.db.commit()
        with patch("services.document_processing_service.generate_embeddings_batch", side_effect=RuntimeError("provider failed")):
            failed_result = process_document(self.db, document.id)
        self.assertEqual(failed_result.status, "ready")
        still_ready_ids = {
            chunk.id for chunk in self.db.query(Chunk).filter(Chunk.document_id == document.id, Chunk.status == "ready")
        }
        self.assertEqual(still_ready_ids, original_ready_ids)

        queued = enqueue_ingestion_job(self.db, self.bot.id, self.org.id, document.id, job_type="document_upload")
        self.assertTrue(cancel_job(self.db, queued.job_id, self.bot.id, self.org.id))
        cancelled_result = execute_document_job(queued.job_id, self.bot.id, self.org.id, document.id)
        self.assertEqual(cancelled_result["status"], "cancelled")
        self.assertEqual(
            {chunk.id for chunk in self.db.query(Chunk).filter(Chunk.document_id == document.id, Chunk.status == "ready")},
            original_ready_ids,
        )

        retry_document = self._document(raw_text="Retry-safe knowledge creates one active chunk set.")
        retry_job = enqueue_ingestion_job(
            self.db,
            self.bot.id,
            self.org.id,
            retry_document.id,
            job_type="document_upload",
        )
        with patch(
            "services.document_processing_service.generate_embeddings_batch",
            side_effect=RuntimeError("temporary provider failure"),
        ):
            first_attempt = execute_document_job(
                retry_job.job_id,
                self.bot.id,
                self.org.id,
                retry_document.id,
            )
        self.assertEqual(first_attempt["status"], "failed")
        self.db.refresh(retry_job)
        retry_job.status = "queued"
        retry_job.current_stage = "queued"
        retry_job.progress_percent = 0
        retry_job.completed_at = None
        self.db.commit()
        second_attempt = execute_document_job(
            retry_job.job_id,
            self.bot.id,
            self.org.id,
            retry_document.id,
        )
        self.assertEqual(second_attempt["status"], "ready")
        self.db.refresh(retry_document)
        retry_ready = self.db.query(Chunk).filter(
            Chunk.document_id == retry_document.id,
            Chunk.status == "ready",
        ).count()
        self.assertEqual(retry_ready, retry_document.chunk_count)
        self.assertEqual(
            self.db.query(Chunk).filter(Chunk.ingestion_job_id == retry_job.job_id).count(),
            0,
        )

        stale_time = datetime.datetime.utcnow() - datetime.timedelta(hours=1)
        stale_job = IngestionJob(
            job_id=f"stale_{self.uid}",
            bot_id=self.bot.id,
            organization_id=self.org.id,
            document_id=document.id,
            status="embedding",
            current_stage="embedding",
            last_heartbeat=stale_time,
            created_at=stale_time,
            updated_at=stale_time,
        )
        self.db.add(stale_job)
        self.db.commit()
        recovered = recover_stale_jobs(max_age_seconds=60)
        self.assertIn(stale_job.job_id, recovered)
        self.db.refresh(stale_job)
        self.assertEqual(stale_job.error_code, "WORKER_TIMEOUT")
        self.assertEqual(
            {chunk.id for chunk in self.db.query(Chunk).filter(Chunk.document_id == document.id, Chunk.status == "ready")},
            original_ready_ids,
        )

    def test_local_upload_is_removed_only_after_final_reference(self):
        target_dir = UPLOAD_DIR / str(self.bot.id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"phase-d-{self.uid}.txt"
        target.write_text("temporary upload", encoding="utf-8")
        first = self._document()
        second = self._document()
        first.file_path = str(target)
        second.file_path = str(target)
        self.db.commit()
        self.db.delete(first)
        self.db.commit()
        self.assertFalse(remove_unreferenced_upload(self.db, str(target)))
        self.assertTrue(target.exists())
        self.db.delete(second)
        self.db.commit()
        self.assertTrue(remove_unreferenced_upload(self.db, str(target)))
        self.assertFalse(target.exists())

    def test_production_embedding_failure_never_creates_fake_vectors(self):
        with patch.dict(
            os.environ,
            {
                "APP_ENV": "production",
                "ALLOW_DETERMINISTIC_EMBEDDING_FALLBACK": "true",
            },
        ), patch(
            "services.embedding_service.get_embedding_provider",
            side_effect=EmbeddingProviderUnavailable("provider unavailable"),
        ):
            with self.assertRaises(EmbeddingProviderUnavailable):
                generate_embeddings_batch([f"uncached production text {self.uid}"])


if __name__ == "__main__":
    unittest.main()
