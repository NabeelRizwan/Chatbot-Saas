import concurrent.futures
import datetime
import os
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

from database.connection import SessionLocal, init_db
from database.models import Bot, Chunk, Customer, Document, IngestionJob, Organization, Website, WebsiteCrawl
from services.crawl4ai_service import Page
from services.queue_service import cancel_job, enqueue_ingestion_job, get_job_status
from services.rag_service import answer_question, clear_retrieval_cache, retrieve_relevant_chunks
from workers.crawl_worker import execute_crawl_job
from workers.embedding_worker import execute_document_job
from workers.job_models import JobStatus, can_transition, sanitize_customer_error
from workers.maintenance_worker import recover_stale_jobs


class TestArqQueueSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.db = SessionLocal()
        import uuid
        self.uid = uuid.uuid4().hex[:8]

        self.org_a = Organization(name=f"QueueOrgA_{self.uid}", slug=f"queue-org-a-{self.uid}")
        self.org_b = Organization(name=f"QueueOrgB_{self.uid}", slug=f"queue-org-b-{self.uid}")
        self.db.add_all([self.org_a, self.org_b])
        self.db.commit()
        self.db.refresh(self.org_a)
        self.db.refresh(self.org_b)

        self.cust_a = Customer(name=f"QueueCustA_{self.uid}", api_key=f"q_key_a_{self.uid}")
        self.cust_b = Customer(name=f"QueueCustB_{self.uid}", api_key=f"q_key_b_{self.uid}")
        self.db.add_all([self.cust_a, self.cust_b])
        self.db.commit()
        self.db.refresh(self.cust_a)
        self.db.refresh(self.cust_b)

        self.bot_a = Bot(
            name=f"QueueBotA_{self.uid}",
            customer_id=self.cust_a.id,
            organization_id=self.org_a.id,
            system_prompt="You are Bot A.",
        )
        self.bot_b = Bot(
            name=f"QueueBotB_{self.uid}",
            customer_id=self.cust_b.id,
            organization_id=self.org_b.id,
            system_prompt="You are Bot B.",
        )
        self.db.add_all([self.bot_a, self.bot_b])
        self.db.commit()
        self.db.refresh(self.bot_a)
        self.db.refresh(self.bot_b)

    def tearDown(self):
        clear_retrieval_cache()
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

    def test_1_job_state_transitions_validation(self):
        """Verify legal and illegal state transitions in Job State Machine."""
        self.assertTrue(can_transition("queued", "crawling"))
        self.assertTrue(can_transition("queued", "processing"))
        self.assertTrue(can_transition("crawling", "processing"))
        self.assertTrue(can_transition("processing", "embedding"))
        self.assertTrue(can_transition("embedding", "validating"))
        self.assertTrue(can_transition("validating", "ready"))
        self.assertTrue(can_transition("crawling", "failed"))
        self.assertTrue(can_transition("processing", "cancelled"))

        # Illegal transitions
        self.assertFalse(can_transition("crawling", "embedding"))  # Must go through processing
        self.assertFalse(can_transition("ready", "processing"))
        self.assertFalse(can_transition("invalid_state", "ready"))

        print("[SUCCESS] Job state transitions verified.")

    def test_2_enqueue_and_worker_execution_to_ready(self):
        """Verify enqueue creates IngestionJob, worker processes it to READY state."""
        pages = [
            Page(
                url="https://novastore.com/products",
                title="NovaStore Products",
                markdown="# NovaStore\nNovaWidget costs $49 with instant delivery.",
                status="success",
            )
        ]

        doc = Document(
            bot_id=self.bot_a.id,
            organization_id=self.org_a.id,
            source_type="website",
            source_url="https://novastore.com/products",
            filename="novastore-products",
            title="NovaStore Products",
            processing_status="pending",
        )
        self.db.add(doc)
        self.db.commit()

        # Enqueue job
        job = enqueue_ingestion_job(
            db=self.db,
            bot_id=self.bot_a.id,
            organization_id=self.org_a.id,
            document_id=doc.id,
            job_type="crawl",
        )
        self.assertIsNotNone(job.job_id)
        self.assertEqual(job.status, "queued")

        # Worker execution
        with patch("services.document_processing_service.crawl_website", return_value=pages):
            res = execute_crawl_job(job.job_id, self.bot_a.id, self.org_a.id, doc.id)
            self.assertEqual(res["status"], "ready")

        # Verify job updated in DB
        self.db.refresh(job)
        self.assertEqual(job.status, "ready")
        self.assertEqual(job.progress_percent, 100)
        self.assertTrue(job.chunks_created > 0)
        self.assertIsNotNone(job.completed_at)

        print("[SUCCESS] Enqueue and Worker execution to READY verified.")

    def test_3_idempotent_job_submission(self):
        """Verify submitting the same job multiple times returns the active job without duplicates."""
        doc = Document(
            bot_id=self.bot_a.id,
            organization_id=self.org_a.id,
            source_type="website",
            source_url="https://novastore.com/faq",
            filename="novastore-faq",
            title="NovaStore FAQ",
            processing_status="pending",
        )
        self.db.add(doc)
        self.db.commit()

        job1 = enqueue_ingestion_job(
            db=self.db,
            bot_id=self.bot_a.id,
            organization_id=self.org_a.id,
            document_id=doc.id,
            job_type="crawl",
        )
        job2 = enqueue_ingestion_job(
            db=self.db,
            bot_id=self.bot_a.id,
            organization_id=self.org_a.id,
            document_id=doc.id,
            job_type="crawl",
        )

        self.assertEqual(job1.job_id, job2.job_id, "Idempotent submission created duplicate job!")
        job_count = self.db.query(IngestionJob).filter(IngestionJob.document_id == doc.id).count()
        self.assertEqual(job_count, 1)

        print("[SUCCESS] Idempotent job submission verified.")

    def test_4_tenant_boundary_worker_rejection(self):
        """Verify Tenant A worker cannot process Tenant B document."""
        doc_b = Document(
            bot_id=self.bot_b.id,
            organization_id=self.org_b.id,
            source_type="website",
            source_url="https://tenant-b.com",
            filename="tenant-b-doc",
            title="Tenant B",
            processing_status="pending",
        )
        self.db.add(doc_b)
        self.db.commit()

        # Malicious job attempting to run Bot A context against Bot B doc
        job = IngestionJob(
            job_id="malicious_job_test",
            bot_id=self.bot_a.id,
            organization_id=self.org_a.id,
            document_id=doc_b.id,
            status="queued",
            last_heartbeat=datetime.datetime.utcnow(),
        )
        self.db.add(job)
        self.db.commit()

        res = execute_crawl_job("malicious_job_test", self.bot_a.id, self.org_a.id, doc_b.id)
        self.assertEqual(res["status"], "failed")
        self.assertEqual(res["error_code"], "TENANT_MISMATCH")

        self.db.refresh(job)
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.error_code, "TENANT_MISMATCH")

        print("[SUCCESS] Tenant boundary worker rejection verified.")

    def test_5_stale_job_recovery_on_worker_crash(self):
        """Verify maintenance worker detects and safely marks crashed/stale jobs as failed."""
        stale_time = datetime.datetime.utcnow() - datetime.timedelta(minutes=30)
        crashed_job = IngestionJob(
            job_id="crashed_job_test",
            bot_id=self.bot_a.id,
            organization_id=self.org_a.id,
            status="crawling",
            current_stage="crawling",
            progress_percent=25,
            last_heartbeat=stale_time,
            created_at=stale_time,
            updated_at=stale_time,
        )
        self.db.add(crashed_job)
        self.db.commit()

        recovered = recover_stale_jobs(max_age_seconds=600)
        self.assertIn("crashed_job_test", recovered)

        self.db.refresh(crashed_job)
        self.assertEqual(crashed_job.status, "failed")
        self.assertEqual(crashed_job.error_code, "WORKER_TIMEOUT")

        print("[SUCCESS] Stale job recovery after worker crash verified.")

    def test_6_chat_unaffected_during_active_crawl_job(self):
        """Verify chat continues answering using existing knowledge while a crawl job runs."""
        # Seed initial ready knowledge
        v1_doc = Document(
            bot_id=self.bot_a.id,
            organization_id=self.org_a.id,
            filename="seeded-v1",
            source_type="text",
            raw_text="NovaCloud subscription is $20 per month.",
            title="NovaCloud Pricing",
            processing_status="completed",
            status="ready",
        )
        self.db.add(v1_doc)
        self.db.commit()
        from services.document_processing_service import process_document
        process_document(self.db, v1_doc.id)

        # Create active crawl job for new page
        new_doc = Document(
            bot_id=self.bot_a.id,
            organization_id=self.org_a.id,
            source_type="website",
            source_url="https://novacloud.com/new-feature",
            filename="new-feature",
            title="New Feature",
            processing_status="pending",
        )
        self.db.add(new_doc)
        self.db.commit()

        active_job = enqueue_ingestion_job(
            db=self.db,
            bot_id=self.bot_a.id,
            organization_id=self.org_a.id,
            document_id=new_doc.id,
            job_type="crawl",
        )

        # While job is in queued/crawling state, perform chat
        with patch("services.rag_service.generate", return_value="NovaCloud costs $20 per month."):
            reply, sources, chunks = answer_question(
                db=self.db,
                bot=self.bot_a,
                question="How much does NovaCloud cost?",
            )
            self.assertIn("20", reply)
            self.assertTrue(len(chunks) > 0)

        print("[SUCCESS] Chat functions seamlessly while background crawl job is queued/running.")


if __name__ == "__main__":
    unittest.main()
