import asyncio
import os
import random
import sys
import time
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from fastapi import HTTPException
from database.connection import SessionLocal, engine, get_pool_status
from database.models import (
    Bot,
    Chunk,
    Document,
    IngestionJob,
    Organization,
    OrganizationMembership,
    User,
    Website,
    WebsiteCrawl,
)
from services.auth_service import hash_password
from services.document_processing_service import process_document
from services.embedding_service import generate_embedding, generate_embeddings_batch
from services.firecrawl_service import (
    CrawlAuditReport,
    crawl_website_with_audit,
    is_url_eligible_for_crawl,
    normalize_crawl_url,
)
from services.llm_client import CentralizedLLMError, LLMErrorCode, classify_exception, execute_with_resilience
from services.queue_service import enqueue_ingestion_job, get_job_status
from services.rag_service import clear_retrieval_cache
from utils.rate_limiter import check_rate_limit
from workers.crawl_worker import execute_crawl_job
from workers.job_models import sanitize_customer_error, transition_job_state

import fakeredis
import fakeredis.aioredis
from utils.redis_client import set_redis_override


class TestPhase11ResilienceAndReliability(unittest.TestCase):
    """
    Phase 11-D, 11-E, 11-F, 11-G, 11-H, 11-L, 11-M:
    Production SaaS Resilience, Queue Reliability, LLM/Embedding Backoff,
    DB Pool Recovery, and Disaster Recovery Test Suite.
    """

    @classmethod
    def setUpClass(cls):
        cls.fake_redis = fakeredis.FakeRedis()
        cls.fake_async_redis = fakeredis.aioredis.FakeRedis()
        set_redis_override(cls.fake_redis, cls.fake_async_redis)

    @classmethod
    def tearDownClass(cls):
        set_redis_override(None, None)

    def setUp(self):
        self.db = SessionLocal()
        self.ts = int(time.time() * 1000) % 1000000 + random.randint(1000, 9999)
        self.org_id = 60000 + (self.ts % 10000)
        self.bot_id = 70000 + (self.ts % 10000)

        self.org = Organization(id=self.org_id, name="Resilience Test Org", slug=f"resilience-org-{self.ts}")
        self.bot = Bot(id=self.bot_id, organization_id=self.org_id, name="Resilience Test Bot")
        self.db.merge(self.org)
        self.db.merge(self.bot)
        self.db.commit()

    def tearDown(self):
        try:
            self.db.query(IngestionJob).filter(IngestionJob.bot_id == self.bot_id).delete()
            self.db.query(Chunk).filter(Chunk.bot_id == self.bot_id).delete()
            self.db.query(Document).filter(Document.bot_id == self.bot_id).delete()
            self.db.query(WebsiteCrawl).filter(WebsiteCrawl.bot_id == self.bot_id).delete()
            self.db.query(Website).filter(Website.bot_id == self.bot_id).delete()
            self.db.query(Bot).filter(Bot.id == self.bot_id).delete()
            self.db.query(Organization).filter(Organization.id == self.org_id).delete()
            self.db.commit()
        except Exception:
            self.db.rollback()
        finally:
            self.db.close()

    # =========================================================================
    # 1. CRAWL JOB IDEMPOTENCY & DUPLICATE SUBMISSION DEFENSE (Phase 11-D)
    # =========================================================================
    def test_01_crawl_job_idempotency(self):
        """Validates that concurrent submissions of the same document do not create duplicate jobs."""
        doc = Document(
            bot_id=self.bot_id,
            organization_id=self.org_id,
            source_type="website",
            filename="idempotency-test-doc",
            title="Idempotency Test",
            source_url="https://example.com/idempotent",
            status="ready",
            processing_status="completed",
        )
        self.db.add(doc)
        self.db.commit()
        self.db.refresh(doc)

        # Enqueue first job
        job1 = enqueue_ingestion_job(
            db=self.db,
            bot_id=self.bot_id,
            organization_id=self.org_id,
            document_id=doc.id,
            job_type="crawl",
        )
        self.assertIsNotNone(job1)
        self.assertEqual(job1.status, "queued")

        # Enqueue second job for SAME document while job1 is active
        job2 = enqueue_ingestion_job(
            db=self.db,
            bot_id=self.bot_id,
            organization_id=self.org_id,
            document_id=doc.id,
            job_type="crawl",
        )
        # Must return the SAME job instance without creating a duplicate record
        self.assertEqual(job1.id, job2.id)
        self.assertEqual(job1.job_id, job2.job_id)

        # Confirm DB has exactly 1 job
        jobs_count = self.db.query(IngestionJob).filter(
            IngestionJob.bot_id == self.bot_id,
            IngestionJob.document_id == doc.id,
        ).count()
        self.assertEqual(jobs_count, 1)

    # =========================================================================
    # 2. JOB STATE MACHINE DETERMINISTIC TRANSITIONS (Phase 11-F)
    # =========================================================================
    def test_02_job_state_machine_transitions(self):
        """Validates that jobs transition through valid, deterministic states with progress updates."""
        job = IngestionJob(
            job_id=f"job_statemachine_{self.ts}",
            bot_id=self.bot_id,
            organization_id=self.org_id,
            status="queued",
            current_stage="queued",
            progress_percent=0,
            last_heartbeat=datetime.utcnow(),
        )
        self.db.add(job)
        self.db.commit()

        # Step 1: Transition to crawling
        transition_job_state(self.db, job.job_id, "crawling", stage="crawling", progress_percent=25)
        self.db.refresh(job)
        self.assertEqual(job.status, "crawling")
        self.assertEqual(job.progress_percent, 25)

        # Step 2: Transition to processing
        transition_job_state(self.db, job.job_id, "processing", stage="processing", progress_percent=60)
        self.db.refresh(job)
        self.assertEqual(job.status, "processing")
        self.assertEqual(job.progress_percent, 60)

        # Step 3: Transition to ready (terminal success)
        transition_job_state(self.db, job.job_id, "ready", stage="ready", progress_percent=100)
        self.db.refresh(job)
        self.assertEqual(job.status, "ready")
        self.assertEqual(job.progress_percent, 100)
        self.assertIsNotNone(job.completed_at)

    # =========================================================================
    # 3. WORKER CRASH & ORPHANED JOB RECOVERY (Phase 11-F)
    # =========================================================================
    def test_03_worker_crash_handling(self):
        """Validates that if a worker crashes, the job error can be captured cleanly."""
        doc = Document(
            bot_id=self.bot_id,
            organization_id=self.org_id,
            source_type="website",
            filename="crash-test-doc",
            title="Crash Test",
            source_url="https://example.com/crash",
            status="ready",
            processing_status="completed",
        )
        self.db.add(doc)
        self.db.commit()
        self.db.refresh(doc)

        job_uuid = f"job_crash_{self.ts}"
        job = IngestionJob(
            job_id=job_uuid,
            bot_id=self.bot_id,
            organization_id=self.org_id,
            document_id=doc.id,
            job_type="crawl",
            status="crawling",
            current_stage="crawling",
            progress_percent=20,
            last_heartbeat=datetime.utcnow(),
        )
        self.db.add(job)
        self.db.commit()

        # Simulate unexpected exception during processing
        with patch("workers.crawl_worker.process_document", side_effect=RuntimeError("Simulated worker Out-Of-Memory")):
            res = execute_crawl_job(job_uuid, self.bot_id, self.org_id, doc.id)
            self.assertEqual(res.get("status"), "failed")

        # Confirm job state transitioned to failed
        self.db.refresh(job)
        self.assertEqual(job.status, "failed")

        # Confirm job error sanitizer handles raw exceptions cleanly
        err_code, safe_msg = sanitize_customer_error(RuntimeError("Simulated worker Out-Of-Memory"))
        self.assertEqual(err_code, "INTERNAL_PROCESSING_ERROR")
        self.assertNotIn("Out-Of-Memory", safe_msg, "Internal stack trace/OOM details must be masked from customers")

    # =========================================================================
    # 4. LLM & EMBEDDING BOUNDED RETRY & ERROR CLASSIFICATION (Phase 11-G)
    # =========================================================================
    def test_04_llm_error_classification_and_backoff(self):
        """Validates that provider errors (429, 503, timeouts) are classified into retryable customer-safe error codes."""
        code, retryable, status, _ = classify_exception(Exception("429 Resource has been exhausted (rate limit)"))
        self.assertEqual(code, LLMErrorCode.LLM_RATE_LIMITED)
        self.assertTrue(retryable)
        self.assertEqual(status, 429)

        code_503, retryable_503, status_503, _ = classify_exception(Exception("503 Service Unavailable"))
        self.assertEqual(code_503, LLMErrorCode.LLM_PROVIDER_UNAVAILABLE)
        self.assertTrue(retryable_503)
        self.assertEqual(status_503, 503)

        code_auth, retryable_auth, status_auth, _ = classify_exception(Exception("401 Invalid API Key"))
        self.assertEqual(code_auth, LLMErrorCode.LLM_AUTH_ERROR)
        self.assertFalse(retryable_auth)
        self.assertEqual(status_auth, 401)

    def test_05_llm_bounded_retry_and_resilience(self):
        """Validates execute_with_resilience retries transient errors and succeeds upon recovery."""
        call_count = 0

        def flaky_llm():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("503 Service Unavailable")
            return "Resilient grounded answer after transient 503"

        with patch("services.llm_client.LLM_BACKOFF_BASE", 0.01):
            result = execute_with_resilience(
                flaky_llm,
                provider_name="gemini",
                model_name="gemini-2.5-flash",
                org_id=self.org_id,
                max_retries=2,
            )
        self.assertEqual(result, "Resilient grounded answer after transient 503")
        self.assertEqual(call_count, 2)

    # =========================================================================
    # 5. DATABASE CONNECTION POOL RECOVERY AFTER ROLLBACK (Phase 11-E)
    # =========================================================================
    def test_06_database_pool_recovery_after_error(self):
        """Validates that a failed transaction is rolled back and the connection returns to the pool cleanly."""
        initial_status = get_pool_status()

        # Execute deliberate SQL syntax failure in a session
        err_session = SessionLocal()
        try:
            from sqlalchemy import text
            err_session.execute(text("SELECT * FROM non_existent_table_for_testing_pool_safety"))
            err_session.commit()
        except Exception:
            err_session.rollback()
        finally:
            err_session.close()

        # Verify pool recovers immediately for subsequent valid query
        valid_session = SessionLocal()
        try:
            bot = valid_session.query(Bot).filter(Bot.id == self.bot_id).first()
            self.assertIsNotNone(bot)
        finally:
            valid_session.close()

        recovered_status = get_pool_status()
        self.assertEqual(recovered_status.get("checkedout", 0), 0, "No leaked connections allowed in pool")

    # =========================================================================
    # 6. REDIS RATE LIMITING IN-MEMORY FALLBACK (Phase 11-F)
    # =========================================================================
    def test_07_rate_limiter_in_memory_fallback(self):
        """Validates that when Redis is disconnected, rate limiting seamlessly falls back to in-memory sliding window."""
        # Force Redis override to None to simulate Redis outage
        set_redis_override(None, None)

        allowed, retry_after, remaining = check_rate_limit(
            scope="public_chat",
            org_id=self.org_id,
            bot_id=self.bot_id,
            client_id="client_fallback_1",
            limit=5,
            window_seconds=10,
        )
        self.assertTrue(allowed, "In-memory fallback must allow request within limit")

        # Exceed limit
        for _ in range(5):
            check_rate_limit(
                scope="public_chat",
                org_id=self.org_id,
                bot_id=self.bot_id,
                client_id="client_fallback_1",
                limit=5,
                window_seconds=10,
            )

        # 7th request must be blocked
        blocked, retry_after, _ = check_rate_limit(
            scope="public_chat",
            org_id=self.org_id,
            bot_id=self.bot_id,
            client_id="client_fallback_1",
            limit=5,
            window_seconds=10,
        )
        self.assertFalse(blocked, "In-memory fallback must enforce rate limit when threshold exceeded")
        self.assertGreaterEqual(retry_after, 1)

        # Restore fake redis
        set_redis_override(self.fake_redis, self.fake_async_redis)

    # =========================================================================
    # 7. URL NORMALIZATION & TRACKING STRIPPING (Phase 11-D)
    # =========================================================================
    def test_08_url_normalization_and_disallowed_paths(self):
        """Validates that tracking parameters, hash fragments, and disallowed paths are handled correctly."""
        raw_url = "https://example.com/products/item-123?utm_source=google&gclid=ABC123xyz#specifications"
        normalized = normalize_crawl_url(raw_url)
        self.assertEqual(normalized, "https://example.com/products/item-123")

        # Cart and Login URLs must be ineligible
        eligible_cart, reason_cart = is_url_eligible_for_crawl("https://example.com/checkout/cart", "example.com")
        self.assertFalse(eligible_cart)
        self.assertIn("cart", reason_cart)

        eligible_login, reason_login = is_url_eligible_for_crawl("https://example.com/user/login", "example.com")
        self.assertFalse(eligible_login)
        self.assertEqual(reason_login, "disallowed_path_auth")

        # External domain must be ineligible
        eligible_ext, reason_ext = is_url_eligible_for_crawl("https://external-tracker.com/pixel", "example.com")
        self.assertFalse(eligible_ext)
        self.assertEqual(reason_ext, "external_domain")


if __name__ == "__main__":
    unittest.main()
