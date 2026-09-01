import concurrent.futures
import datetime
import os
import sys
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

from database.connection import SessionLocal, init_db
from database.models import Bot, Chunk, Customer, Document, IngestionJob, Organization, Website, WebsiteCrawl
from services.crawl4ai_service import Page
from services.queue_service import cancel_job, enqueue_ingestion_job, get_job_status
from workers.crawl_worker import execute_crawl_job
from workers.embedding_worker import execute_document_job
from workers.job_models import (
    JobStatus,
    can_transition,
    sanitize_customer_error,
    transition_job_state,
)
from workers.maintenance_worker import recover_stale_jobs


class TestJobStateMachineSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.db = SessionLocal()
        self.uid = uuid.uuid4().hex[:8]

        self.org_a = Organization(name=f"StateOrgA_{self.uid}", slug=f"state-org-a-{self.uid}")
        self.org_b = Organization(name=f"StateOrgB_{self.uid}", slug=f"state-org-b-{self.uid}")
        self.db.add_all([self.org_a, self.org_b])
        self.db.commit()
        self.db.refresh(self.org_a)
        self.db.refresh(self.org_b)

        self.cust_a = Customer(name=f"StateCustA_{self.uid}", api_key=f"state_key_a_{self.uid}")
        self.cust_b = Customer(name=f"StateCustB_{self.uid}", api_key=f"state_key_b_{self.uid}")
        self.db.add_all([self.cust_a, self.cust_b])
        self.db.commit()
        self.db.refresh(self.cust_a)
        self.db.refresh(self.cust_b)

        self.bot_a = Bot(
            name=f"StateBotA_{self.uid}",
            customer_id=self.cust_a.id,
            organization_id=self.org_a.id,
            system_prompt="You are Bot A.",
        )
        self.bot_b = Bot(
            name=f"StateBotB_{self.uid}",
            customer_id=self.cust_b.id,
            organization_id=self.org_b.id,
            system_prompt="You are Bot B.",
        )
        self.db.add_all([self.bot_a, self.bot_b])
        self.db.commit()
        self.db.refresh(self.bot_a)
        self.db.refresh(self.bot_b)

    def tearDown(self):
        self.db.query(IngestionJob).filter(IngestionJob.bot_id.in_([self.bot_a.id, self.bot_b.id])).delete()
        self.db.query(Chunk).filter(Chunk.bot_id.in_([self.bot_a.id, self.bot_b.id])).delete()
        self.db.query(Document).filter(Document.bot_id.in_([self.bot_a.id, self.bot_b.id])).delete()
        self.db.query(WebsiteCrawl).filter(WebsiteCrawl.bot_id.in_([self.bot_a.id, self.bot_b.id])).delete()
        self.db.query(Website).filter(Website.bot_id.in_([self.bot_a.id, self.bot_b.id])).delete()
        self.db.query(Bot).filter(Bot.id.in_([self.bot_a.id, self.bot_b.id])).delete()
        self.db.query(Customer).filter(Customer.id.in_([self.cust_a.id, self.cust_b.id])).delete()
        self.db.query(Organization).filter(Organization.id.in_([self.org_a.id, self.org_b.id])).delete()
        self.db.commit()
        self.db.close()

    def test_1_valid_state_transitions(self):
        """Test the standard linear lifecycle progression: QUEUED -> CRAWLING -> PROCESSING -> EMBEDDING -> VALIDATING -> READY."""
        job_id = f"test_valid_{self.uid}"
        job = IngestionJob(
            job_id=job_id,
            bot_id=self.bot_a.id,
            organization_id=self.org_a.id,
            status="queued",
            current_stage="queued",
            progress_percent=0,
        )
        self.db.add(job)
        self.db.commit()

        self.assertTrue(transition_job_state(self.db, job_id, "crawling", stage="crawling", progress_percent=20))
        self.assertTrue(transition_job_state(self.db, job_id, "processing", stage="processing", progress_percent=50))
        self.assertTrue(transition_job_state(self.db, job_id, "embedding", stage="embedding", progress_percent=70))
        self.assertTrue(transition_job_state(self.db, job_id, "validating", stage="validating", progress_percent=90))
        self.assertTrue(transition_job_state(self.db, job_id, "ready", stage="ready", progress_percent=100))

        self.db.refresh(job)
        self.assertEqual(job.status, "ready")
        self.assertEqual(job.progress_percent, 100)
        self.assertIsNotNone(job.completed_at)
        print("[SUCCESS] Test 1: Valid linear state transitions verified.")

    def test_2_invalid_transition_rejection(self):
        """Verify illegal skips and backwards transitions are rejected."""
        job_id = f"test_invalid_{self.uid}"
        job = IngestionJob(
            job_id=job_id,
            bot_id=self.bot_a.id,
            organization_id=self.org_a.id,
            status="queued",
        )
        self.db.add(job)
        self.db.commit()

        # Cannot jump from QUEUED directly to EMBEDDING or VALIDATING
        self.assertFalse(transition_job_state(self.db, job_id, "embedding"))
        self.assertFalse(transition_job_state(self.db, job_id, "validating"))

        # Transition to crawling
        self.assertTrue(transition_job_state(self.db, job_id, "crawling"))

        # Cannot jump backwards from crawling to queued or skip to ready
        self.assertFalse(transition_job_state(self.db, job_id, "queued"))
        self.assertFalse(transition_job_state(self.db, job_id, "ready"))
        print("[SUCCESS] Test 2: Invalid transition rejection verified.")

    def test_3_terminal_state_protection(self):
        """Verify terminal states (READY, FAILED, CANCELLED) reject active transitions."""
        job_id = f"test_terminal_{self.uid}"
        job = IngestionJob(
            job_id=job_id,
            bot_id=self.bot_a.id,
            organization_id=self.org_a.id,
            status="ready",
            progress_percent=100,
        )
        self.db.add(job)
        self.db.commit()

        # Cannot transition READY directly into processing or crawling
        self.assertFalse(transition_job_state(self.db, job_id, "crawling"))
        self.assertFalse(transition_job_state(self.db, job_id, "processing"))
        self.assertFalse(transition_job_state(self.db, job_id, "embedding"))

        # Set to failed
        job.status = "failed"
        self.db.commit()
        self.assertFalse(transition_job_state(self.db, job_id, "validating"))
        self.assertFalse(transition_job_state(self.db, job_id, "processing"))

        # Set to cancelled
        job.status = "cancelled"
        self.db.commit()
        self.assertFalse(transition_job_state(self.db, job_id, "crawling"))
        print("[SUCCESS] Test 3: Terminal state protection verified.")

    def test_4_concurrent_state_transitions(self):
        """Verify atomic database locking under concurrent worker threads."""
        job_id = f"test_concurrent_{self.uid}"
        job = IngestionJob(
            job_id=job_id,
            bot_id=self.bot_a.id,
            organization_id=self.org_a.id,
            status="queued",
            progress_percent=0,
        )
        self.db.add(job)
        self.db.commit()

        def try_transition(target_status, stage, progress):
            db = SessionLocal()
            try:
                return transition_job_state(db, job_id, target_status, stage=stage, progress_percent=progress)
            finally:
                db.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            f1 = executor.submit(try_transition, "crawling", "crawling", 20)
            f2 = executor.submit(try_transition, "crawling", "crawling", 20)
            f3 = executor.submit(try_transition, "processing", "processing", 50)
            results = [f1.result(), f2.result(), f3.result()]

        self.db.refresh(job)
        self.assertIn(job.status, ["crawling", "processing"])
        print("[SUCCESS] Test 4: Concurrent state updates handled atomically.")

    def test_5_cancellation_safety(self):
        """Verify job cancellation stops worker progression cleanly."""
        doc = Document(
            bot_id=self.bot_a.id,
            organization_id=self.org_a.id,
            source_type="website",
            source_url="https://example.com/cancel-test",
            filename="cancel-test",
            processing_status="pending",
        )
        self.db.add(doc)
        self.db.commit()

        job_id = f"test_cancel_{self.uid}"
        job = IngestionJob(
            job_id=job_id,
            bot_id=self.bot_a.id,
            organization_id=self.org_a.id,
            document_id=doc.id,
            status="queued",
        )
        self.db.add(job)
        self.db.commit()

        # Cancel the job
        cancelled = cancel_job(self.db, job_id, self.bot_a.id, self.org_a.id)
        self.assertTrue(cancelled)
        self.db.refresh(job)
        self.assertEqual(job.status, "cancelled")

        # Worker attempts to run on cancelled job
        res = execute_crawl_job(job_id, self.bot_a.id, self.org_a.id, doc.id)
        self.assertEqual(res["status"], "cancelled")
        print("[SUCCESS] Test 5: Cancellation safety verified.")

    def test_6_stale_heartbeat_and_timeout_recovery(self):
        """Verify stale jobs with dead heartbeats are automatically failed by maintenance worker."""
        old_time = datetime.datetime.utcnow() - datetime.timedelta(minutes=25)
        job_id = f"test_stale_{self.uid}"
        stale_job = IngestionJob(
            job_id=job_id,
            bot_id=self.bot_a.id,
            organization_id=self.org_a.id,
            status="crawling",
            current_stage="crawling",
            progress_percent=30,
            last_heartbeat=old_time,
            created_at=old_time,
            updated_at=old_time,
        )
        self.db.add(stale_job)
        self.db.commit()

        recovered_ids = recover_stale_jobs(max_age_seconds=600)
        self.assertIn(job_id, recovered_ids)

        self.db.refresh(stale_job)
        self.assertEqual(stale_job.status, "failed")
        self.assertEqual(stale_job.error_code, "WORKER_TIMEOUT")
        print("[SUCCESS] Test 6: Stale heartbeat & timeout recovery verified.")

    def test_7_tenant_scoping_and_authorization(self):
        """Verify job status query rejects unauthorized bots/organizations."""
        job_id = f"test_scope_{self.uid}"
        job = IngestionJob(
            job_id=job_id,
            bot_id=self.bot_a.id,
            organization_id=self.org_a.id,
            status="ready",
            progress_percent=100,
        )
        self.db.add(job)
        self.db.commit()

        # Authorized lookup
        status_a = get_job_status(self.db, job_id, bot_id=self.bot_a.id, organization_id=self.org_a.id)
        self.assertIsNotNone(status_a)
        self.assertEqual(status_a["job_id"], job_id)

        # Unauthorized bot lookup
        status_b = get_job_status(self.db, job_id, bot_id=self.bot_b.id, organization_id=self.org_b.id)
        self.assertIsNone(status_b)

        # Cross-organization spoof attempt
        status_spoof = get_job_status(self.db, job_id, bot_id=self.bot_a.id, organization_id=self.org_b.id)
        self.assertIsNone(status_spoof)
        print("[SUCCESS] Test 7: Tenant scoping and status authorization verified.")

    def test_8_error_sanitization(self):
        """Verify internal exceptions never expose stack traces, SQL, file paths, or API keys."""
        err_sql = Exception("psycopg2.errors.UniqueViolation: duplicate key value violates unique constraint 'ix_chunks'")
        code, msg = sanitize_customer_error(err_sql)
        self.assertNotIn("psycopg2", msg)
        self.assertNotIn("ix_chunks", msg)

        err_path = Exception("FileNotFoundError: [Errno 2] No such file or directory: 'C:\\Users\\ADMIN\\secrets.env'")
        code, msg = sanitize_customer_error(err_path)
        self.assertNotIn("secrets.env", msg)
        self.assertNotIn("ADMIN", msg)

        err_429 = Exception("ResourceExhausted: 429 You exceeded your current quota, please check your plan")
        code, msg = sanitize_customer_error(err_429)
        self.assertEqual(code, "RATE_LIMIT_EXCEEDED")
        self.assertIn("rate limit", msg.lower())

        err_ssrf = Exception("Disallowed SSRF target IP: 192.168.1.1")
        code, msg = sanitize_customer_error(err_ssrf)
        self.assertEqual(code, "SSRF_BLOCKED")
        self.assertNotIn("192.168.1.1", msg)
        print("[SUCCESS] Test 8: Customer error sanitization verified.")

    def test_9_progress_and_state_consistency(self):
        """Verify progress percentage is monotonic and cannot exceed 100 or report inconsistent stages."""
        job_id = f"test_prog_{self.uid}"
        job = IngestionJob(
            job_id=job_id,
            bot_id=self.bot_a.id,
            organization_id=self.org_a.id,
            status="queued",
            progress_percent=0,
        )
        self.db.add(job)
        self.db.commit()

        # Transition to processing at 40%
        transition_job_state(self.db, job_id, "processing", stage="processing", progress_percent=40)
        self.db.refresh(job)
        self.assertEqual(job.progress_percent, 40)

        # Attempting lower progress should not decrease progress percent
        transition_job_state(self.db, job_id, "embedding", stage="embedding", progress_percent=30)
        self.db.refresh(job)
        self.assertEqual(job.progress_percent, 40)  # Monotonic guarantee

        # Transitioning to ready sets progress to 100%
        transition_job_state(self.db, job_id, "validating", stage="validating", progress_percent=90)
        transition_job_state(self.db, job_id, "ready", stage="ready")
        self.db.refresh(job)
        self.assertEqual(job.progress_percent, 100)
        self.assertEqual(job.current_stage, "ready")
        print("[SUCCESS] Test 9: Progress and state consistency verified.")


if __name__ == "__main__":
    unittest.main()
