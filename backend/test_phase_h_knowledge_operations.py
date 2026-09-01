import asyncio
import datetime
import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import BackgroundTasks

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

from database.connection import SessionLocal, init_db
from database.models import (
    Bot, Customer, Document, IngestionJob, MessageUsageReservation, Organization,
    UsageDaily, UsageMonthly, Website, WebsiteCrawl,
)
from services.health_service import liveness_status, readiness_status
from services.queue_service import (
    acknowledge_job_cancellation, cancel_job, get_job_status, retry_job,
)
from services.usage_service import (
    consume_message_quota, current_month, message_reservation_ttl_seconds,
    reconcile_stale_message_reservations, release_message_quota, reserve_message_quota,
)
from utils.redis_client import set_redis_override
from workers.job_models import transition_job_state
from workers.maintenance_worker import recover_stale_jobs
from workers.worker import WORKER_HEARTBEAT_KEY, shutdown, startup


class TestPhaseHKnowledgeOperations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.db = SessionLocal()
        uid = uuid.uuid4().hex[:10]
        self.org = Organization(name=f"Phase H {uid}", slug=f"phase-h-{uid}")
        self.other_org = Organization(name=f"Phase H other {uid}", slug=f"phase-h-other-{uid}")
        self.customer = Customer(name=f"Phase H {uid}", api_key=f"phase_h_{uid}")
        self.db.add_all([self.org, self.other_org, self.customer])
        self.db.commit()
        self.bot = Bot(name=f"Phase H Bot {uid}", customer_id=self.customer.id, organization_id=self.org.id)
        self.db.add(self.bot)
        self.db.commit()

    def tearDown(self):
        self.db.rollback()
        self.db.query(MessageUsageReservation).filter(
            MessageUsageReservation.organization_id.in_([self.org.id, self.other_org.id])
        ).delete(synchronize_session=False)
        self.db.query(IngestionJob).filter(IngestionJob.bot_id == self.bot.id).delete(synchronize_session=False)
        self.db.query(Document).filter(Document.bot_id == self.bot.id).delete(synchronize_session=False)
        self.db.query(WebsiteCrawl).filter(WebsiteCrawl.bot_id == self.bot.id).delete(synchronize_session=False)
        self.db.query(Website).filter(Website.bot_id == self.bot.id).delete(synchronize_session=False)
        self.db.query(UsageMonthly).filter(UsageMonthly.organization_id.in_([self.org.id, self.other_org.id])).delete(synchronize_session=False)
        self.db.query(UsageDaily).filter(UsageDaily.organization_id.in_([self.org.id, self.other_org.id])).delete(synchronize_session=False)
        self.db.query(Bot).filter(Bot.id == self.bot.id).delete()
        self.db.query(Customer).filter(Customer.id == self.customer.id).delete()
        self.db.query(Organization).filter(Organization.id.in_([self.org.id, self.other_org.id])).delete(synchronize_session=False)
        self.db.commit()
        self.db.close()
        set_redis_override(None, None)

    def _document(self, source_type="txt", url=None):
        document = Document(
            bot_id=self.bot.id, organization_id=self.org.id, filename="customer-source.txt",
            source_type=source_type, source_url=url, raw_text="phase h", status="staging",
            processing_status="pending",
        )
        self.db.add(document)
        self.db.commit()
        return document

    def test_customer_job_contract_and_measured_coverage_are_safe(self):
        url = "https://example.com/docs"
        document = self._document("website", url)
        website = Website(bot_id=self.bot.id, organization_id=self.org.id, root_url=url, domain="example.com")
        self.db.add(website); self.db.flush()
        crawl = WebsiteCrawl(
            website_id=website.id, bot_id=self.bot.id, organization_id=self.org.id, version=2,
            pages_discovered=8, pages_eligible=6, pages_crawled=5, pages_skipped=1, pages_failed=1,
            duplicate_urls_removed=1, max_depth_reached=2, coverage_percent=66.67, chunks_created=12,
            status="failed", audit_metadata={
                "stored_documents": 4,
                "skipped_urls": {"https://example.com/login?token=secret": "disallowed_path_auth"},
                "failed_urls": {"https://example.com/broken?api_key=secret": "requests.ConnectionError api-key-secret"},
            },
        )
        self.db.add(crawl); self.db.flush()
        website.active_crawl_id = crawl.id
        job = IngestionJob(
            job_id=f"job_{uuid.uuid4().hex}", organization_id=self.org.id, bot_id=self.bot.id,
            website_id=website.id, crawl_id=crawl.id, document_id=document.id, job_type="recrawl",
            status="failed", current_stage="failed", error_code="PLAN_QUOTA_EXCEEDED",
            error_message="postgres secrets /srv/app/.env", attempt_count=2,
        )
        self.db.add(job); self.db.commit()
        response = get_job_status(self.db, job.job_id, self.bot.id, self.org.id)
        self.assertEqual(response["stage"], "failed")
        self.assertEqual(response["attempt_number"], 2)
        self.assertNotIn("organization_id", response)
        self.assertNotIn("audit_metadata", response)
        self.assertNotIn("postgres", response["error_message"])
        coverage = response["crawl_coverage"]
        self.assertEqual((coverage["discovered"], coverage["eligible"], coverage["crawled"], coverage["indexed"]), (8, 6, 5, 4))
        self.assertEqual(coverage["coverage_percent"], 66.67)
        rendered = repr(coverage["url_results"])
        self.assertNotIn("secret", rendered)
        self.assertIn("Excluded sign-in", rendered)
        self.assertIn("Page crawl failed", rendered)

    def test_retry_is_same_logical_job_and_idempotent(self):
        document = self._document()
        job = IngestionJob(
            job_id=f"job_{uuid.uuid4().hex}", organization_id=self.org.id, bot_id=self.bot.id,
            document_id=document.id, job_type="document_upload", status="failed", current_stage="failed",
            error_code="TIMEOUT", attempt_count=1,
        )
        self.db.add(job); self.db.commit()
        background = BackgroundTasks()
        with patch.dict(os.environ, {"APP_ENV": "development", "INGESTION_QUEUE_MODE": "background"}):
            first = retry_job(self.db, job.job_id, self.bot.id, self.org.id, background)
            second = retry_job(self.db, job.job_id, self.bot.id, self.org.id, background)
        self.assertEqual(first.job_id, second.job_id)
        self.assertEqual(len(background.tasks), 1)
        self.assertEqual(self.db.query(IngestionJob).filter(IngestionJob.job_id == job.job_id).count(), 1)
        self.assertEqual(first.status, "queued")

    def test_running_cancellation_is_acknowledged_and_cannot_promote(self):
        document = self._document()
        job = IngestionJob(
            job_id=f"job_{uuid.uuid4().hex}", organization_id=self.org.id, bot_id=self.bot.id,
            document_id=document.id, status="processing", current_stage="processing",
        )
        self.db.add(job); self.db.commit()
        self.assertTrue(cancel_job(self.db, job.job_id, self.bot.id, self.org.id))
        self.assertEqual(get_job_status(self.db, job.job_id, self.bot.id, self.org.id)["status"], "cancelling")
        self.assertFalse(transition_job_state(self.db, job.job_id, "ready"))
        self.assertTrue(acknowledge_job_cancellation(self.db, job.job_id))
        result = get_job_status(self.db, job.job_id, self.bot.id, self.org.id)
        self.assertEqual(result["status"], "cancelled")
        self.assertIsNotNone(result["completed_at"])

    def test_abandoned_cancellation_is_finalized_by_maintenance(self):
        document = self._document()
        old = datetime.datetime.utcnow() - datetime.timedelta(hours=1)
        job = IngestionJob(
            job_id=f"job_{uuid.uuid4().hex}", organization_id=self.org.id, bot_id=self.bot.id,
            document_id=document.id, status="cancelled", current_stage="cancelling",
            cancellation_requested_at=old, last_heartbeat=old, updated_at=old,
        )
        self.db.add(job); self.db.commit()
        self.assertIn(job.job_id, recover_stale_jobs(max_age_seconds=900))
        self.db.refresh(job)
        self.assertEqual(job.current_stage, "cancelled")
        self.assertIsNotNone(job.completed_at)

    def test_reservation_reaper_fresh_settled_tenant_and_idempotency_cases(self):
        fresh = reserve_message_quota(self.db, self.org.id, idempotency_key="fresh", channel="test")
        consumed = reserve_message_quota(self.db, self.org.id, idempotency_key="consumed", channel="test")
        released = reserve_message_quota(self.db, self.org.id, idempotency_key="released", channel="test")
        stale = reserve_message_quota(self.db, self.org.id, idempotency_key="stale", channel="test")
        other = reserve_message_quota(self.db, self.other_org.id, idempotency_key="other-stale", channel="test")
        consume_message_quota(self.db, self.org.id, consumed)
        release_message_quota(self.db, self.org.id, released)
        now = datetime.datetime.utcnow()
        old = now - datetime.timedelta(seconds=message_reservation_ttl_seconds() + 5)
        self.db.query(MessageUsageReservation).filter(
            MessageUsageReservation.idempotency_key.in_(["stale", "other-stale"])
        ).update({"last_heartbeat_at": old, "expires_at": old}, synchronize_session=False)
        self.db.commit()
        before_usage = self.db.query(UsageMonthly).filter(UsageMonthly.organization_id == self.org.id, UsageMonthly.month == current_month()).one().messages_sent
        changed = reconcile_stale_message_reservations(self.db, now=now, organization_id=self.org.id)
        self.assertEqual(len(changed), 1)
        statuses = {row.idempotency_key: row.status for row in self.db.query(MessageUsageReservation).all()}
        self.assertEqual(statuses["fresh"], "reserved")
        self.assertEqual(statuses["consumed"], "consumed")
        self.assertEqual(statuses["released"], "released")
        self.assertEqual(statuses["stale"], "released")
        self.assertEqual(statuses["other-stale"], "reserved")
        self.assertEqual(reconcile_stale_message_reservations(self.db, now=now, organization_id=self.org.id), [])
        after_usage = self.db.query(UsageMonthly).filter(UsageMonthly.organization_id == self.org.id, UsageMonthly.month == current_month()).one().messages_sent
        self.assertEqual(before_usage, after_usage)

    def test_liveness_and_dependency_readiness_are_truthful(self):
        self.assertEqual(liveness_status(), {"status": "alive"})
        with patch("services.health_service.engine.connect", side_effect=RuntimeError("db down")):
            ready, payload = readiness_status()
        self.assertFalse(ready)
        self.assertEqual(payload["dependencies"]["database"], "unavailable")

        redis = MagicMock()
        redis.ping.return_value = True
        redis.get.return_value = None
        set_redis_override(redis)
        with patch.dict(os.environ, {"APP_ENV": "production", "INGESTION_QUEUE_MODE": "arq"}):
            ready, payload = readiness_status()
        self.assertFalse(ready)
        self.assertEqual(payload["dependencies"]["worker"], "unavailable")
        redis.get.return_value = "heartbeat"
        with patch.dict(os.environ, {"APP_ENV": "production", "INGESTION_QUEUE_MODE": "arq"}):
            ready, payload = readiness_status()
        self.assertTrue(ready)

    def test_worker_heartbeat_is_published(self):
        class AsyncRedis:
            def __init__(self): self.values = {}
            async def set(self, key, value, ex=None): self.values[key] = (value, ex)
        redis = AsyncRedis(); ctx = {"redis": redis}
        async def exercise():
            await startup(ctx)
            self.assertIn(WORKER_HEARTBEAT_KEY, redis.values)
            await shutdown(ctx)
        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
