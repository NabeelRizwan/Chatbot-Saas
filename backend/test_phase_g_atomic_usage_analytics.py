import concurrent.futures
import os
import sys
import uuid
import unittest
from datetime import datetime
from unittest.mock import patch

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from fastapi import HTTPException

from database.connection import SessionLocal, init_db
from database.models import (
    Bot,
    Chunk,
    ConversationMessage,
    ConversationSession,
    Customer,
    Document,
    MessageUsageReservation,
    Organization,
    Plan,
    Subscription,
    UsageDaily,
    UsageMonthly,
    Website,
    WebsiteCrawl,
)
from services.analytics_service import get_organization_analytics_details
from services.document_processing_service import process_document
from services.firecrawl_service import CrawlAuditReport, Page
from services.usage_service import (
    consume_message_quota,
    current_month,
    ensure_can_create_bot,
    release_message_quota,
    reserve_message_quota,
    get_usage_summary,
)


class TestPhaseGAtomicUsageAndTruthfulAnalytics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.uid = uuid.uuid4().hex[:10]
        self.db = SessionLocal()
        self.org = Organization(name=f"Phase G {self.uid}", slug=f"phase-g-{self.uid}")
        self.customer = Customer(name=f"Phase G {self.uid}", api_key=f"phase_g_{self.uid}")
        self.plan = Plan(
            code=f"phase-g-{self.uid}",
            name="Phase G Test",
            monthly_price_cents=0,
            limits_json={
                "monthly_messages": 3,
                "max_bots": 2,
                "max_documents": 2,
                "storage_bytes": 10_000_000,
                "team_members": 2,
            },
        )
        self.db.add_all([self.org, self.customer, self.plan])
        self.db.commit()
        self.org_id = self.org.id
        self.customer_id = self.customer.id
        self.subscription = Subscription(
            organization_id=self.org.id,
            plan_id=self.plan.id,
            status="active",
            current_period_start=datetime.utcnow(),
        )
        self.db.add(self.subscription)
        self.db.commit()

    def tearDown(self):
        self.db.rollback()
        org_id = self.org.id
        bot_ids = [row[0] for row in self.db.query(Bot.id).filter(Bot.organization_id == org_id).all()]
        if bot_ids:
            self.db.query(ConversationMessage).filter(ConversationMessage.organization_id == org_id).delete(synchronize_session=False)
            self.db.query(ConversationSession).filter(ConversationSession.organization_id == org_id).delete(synchronize_session=False)
            self.db.query(Chunk).filter(Chunk.organization_id == org_id).delete(synchronize_session=False)
            self.db.query(Document).filter(Document.organization_id == org_id).delete(synchronize_session=False)
            self.db.query(WebsiteCrawl).filter(WebsiteCrawl.organization_id == org_id).delete(synchronize_session=False)
            self.db.query(Website).filter(Website.organization_id == org_id).delete(synchronize_session=False)
            self.db.query(Bot).filter(Bot.organization_id == org_id).delete(synchronize_session=False)
        self.db.query(MessageUsageReservation).filter(MessageUsageReservation.organization_id == org_id).delete(synchronize_session=False)
        self.db.query(UsageDaily).filter(UsageDaily.organization_id == org_id).delete(synchronize_session=False)
        self.db.query(UsageMonthly).filter(UsageMonthly.organization_id == org_id).delete(synchronize_session=False)
        self.db.query(Subscription).filter(Subscription.organization_id == org_id).delete(synchronize_session=False)
        self.db.query(Plan).filter(Plan.id == self.plan.id).delete(synchronize_session=False)
        self.db.query(Organization).filter(Organization.id == org_id).delete(synchronize_session=False)
        self.db.query(Customer).filter(Customer.id == self.customer.id).delete(synchronize_session=False)
        self.db.commit()
        self.db.close()

    def _reserve_and_consume(self, key: str) -> bool:
        db = SessionLocal()
        try:
            reservation = reserve_message_quota(
                db, self.org_id, idempotency_key=key, channel="test"
            )
            return consume_message_quota(db, self.org_id, reservation)
        except HTTPException as exc:
            self.assertEqual(exc.status_code, 402)
            return False
        finally:
            db.close()

    def test_a_message_limit_is_atomic_under_concurrency(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(self._reserve_and_consume, [f"turn-{i}" for i in range(8)]))
        self.assertEqual(sum(results), 3)
        self.db.expire_all()
        monthly = self.db.query(UsageMonthly).filter(
            UsageMonthly.organization_id == self.org.id,
            UsageMonthly.month == current_month(),
        ).one()
        self.assertEqual(monthly.messages_sent, 3)

    def test_b_c_same_turn_is_once_and_failed_turn_is_free(self):
        key = reserve_message_quota(self.db, self.org.id, idempotency_key="same-turn", channel="widget")
        self.assertTrue(consume_message_quota(self.db, self.org.id, key))
        self.assertFalse(consume_message_quota(self.db, self.org.id, key))
        failed = reserve_message_quota(self.db, self.org.id, idempotency_key="failed-turn", channel="widget")
        self.assertTrue(release_message_quota(self.db, self.org.id, failed))
        monthly = self.db.query(UsageMonthly).filter(
            UsageMonthly.organization_id == self.org.id,
            UsageMonthly.month == current_month(),
        ).one()
        self.assertEqual(monthly.messages_sent, 1)

    def test_d_bot_limit_is_atomic_under_concurrency(self):
        def create(index: int) -> bool:
            db = SessionLocal()
            try:
                ensure_can_create_bot(db, self.org_id)
                db.add(Bot(
                    name=f"Concurrent {index}",
                    customer_id=self.customer_id,
                    organization_id=self.org_id,
                ))
                db.commit()
                return True
            except HTTPException as exc:
                db.rollback()
                self.assertEqual(exc.status_code, 402)
                return False
            finally:
                db.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(create, range(6)))
        self.assertEqual(sum(results), 2)
        self.assertEqual(self.db.query(Bot).filter(Bot.organization_id == self.org.id).count(), 2)

    def test_e_f_crawl_quota_rejects_whole_staged_version_and_keeps_old(self):
        bot = Bot(name="Crawl", customer_id=self.customer.id, organization_id=self.org.id)
        self.db.add(bot)
        self.db.flush()
        unrelated = Document(
            bot_id=bot.id,
            organization_id=self.org.id,
            filename="unrelated",
            source_type="text",
            raw_text="existing",
            logical_size_bytes=8,
            status="ready",
            processing_status="completed",
        )
        root_url = f"https://phase-g-{self.uid}.example"
        root = Document(
            bot_id=bot.id,
            organization_id=self.org.id,
            filename="root",
            source_type="website",
            source_url=root_url,
            raw_text="",
            logical_size_bytes=0,
            status="staging",
            processing_status="pending",
        )
        self.db.add_all([unrelated, root])
        self.db.commit()
        first_audit = CrawlAuditReport(
            seed_url=root_url, discovered_urls=1, eligible_urls=1,
            crawled_urls=1, stored_documents=1,
        )
        with patch(
            "services.document_processing_service.crawl_website",
            return_value=([Page(url=root_url, title="v1", markdown="old active knowledge")], first_audit),
        ):
            first = process_document(self.db, root.id)
        self.assertEqual(first.status, "ready")
        website = self.db.query(Website).filter(Website.root_url == root_url).one()
        old_crawl_id = website.active_crawl_id

        second_pages = [
            Page(url=root_url, title="v2", markdown="replacement root"),
            Page(url=f"{root_url}/extra", title="extra", markdown="replacement extra"),
        ]
        second_audit = CrawlAuditReport(
            seed_url=root_url, discovered_urls=2, eligible_urls=2,
            crawled_urls=2, stored_documents=2,
        )
        with patch(
            "services.document_processing_service.crawl_website",
            return_value=(second_pages, second_audit),
        ):
            failed = process_document(self.db, root.id)
        self.db.refresh(website)
        self.db.refresh(root)
        self.assertEqual(failed.status, "ready")
        self.assertEqual(website.active_crawl_id, old_crawl_id)
        self.assertEqual(root.raw_text, "old active knowledge")
        self.assertEqual(
            self.db.query(WebsiteCrawl).filter(WebsiteCrawl.website_id == website.id)
            .order_by(WebsiteCrawl.version.desc()).first().status,
            "failed",
        )
        self.assertEqual(
            self.db.query(Document).filter(
                Document.organization_id == self.org.id, Document.status == "ready"
            ).count(),
            2,
        )

    def test_g_concurrent_usage_is_tenant_isolated(self):
        other = Organization(name=f"Other {self.uid}", slug=f"other-phase-g-{self.uid}")
        self.db.add(other)
        self.db.flush()
        other_id = other.id
        self.db.add(Subscription(
            organization_id=other_id,
            plan_id=self.plan.id,
            status="active",
            current_period_start=datetime.utcnow(),
        ))
        self.db.commit()

        def consume_for(payload: tuple[int, str]) -> bool:
            org_id, key = payload
            db = SessionLocal()
            try:
                reservation = reserve_message_quota(
                    db, org_id, idempotency_key=key, channel="tenant-isolation"
                )
                return consume_message_quota(db, org_id, reservation)
            except HTTPException:
                return False
            finally:
                db.close()

        payloads = [
            *((self.org_id, f"primary-{index}") for index in range(4)),
            *((other_id, f"other-{index}") for index in range(4)),
        ]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(consume_for, payloads))
        self.assertEqual(sum(results[:4]), 3)
        self.assertEqual(sum(results[4:]), 3)
        for org_id in (self.org_id, other_id):
            monthly = self.db.query(UsageMonthly).filter(
                UsageMonthly.organization_id == org_id,
                UsageMonthly.month == current_month(),
            ).one()
            self.assertEqual(monthly.messages_sent, 3)

        self.db.query(MessageUsageReservation).filter(MessageUsageReservation.organization_id == other_id).delete(synchronize_session=False)
        self.db.query(UsageDaily).filter(UsageDaily.organization_id == other_id).delete(synchronize_session=False)
        self.db.query(UsageMonthly).filter(UsageMonthly.organization_id == other_id).delete(synchronize_session=False)
        self.db.query(Subscription).filter(Subscription.organization_id == other_id).delete(synchronize_session=False)
        self.db.query(Organization).filter(Organization.id == other_id).delete(synchronize_session=False)
        self.db.commit()

    def test_usage_contract_marks_unreliable_provider_metering_unknown(self):
        summary = get_usage_summary(self.db, self.org_id)
        self.assertEqual(summary["current_plan"], self.plan.code)
        self.assertEqual(summary["usage"]["messages_used"], 0)
        self.assertEqual(summary["usage"]["bots_used"], 0)
        self.assertEqual(summary["usage"]["documents_used"], 0)
        self.assertEqual(summary["usage"]["knowledge_resources_reserved"], 0)
        self.assertEqual(summary["usage"]["logical_storage_bytes"], 0)
        self.assertIsNone(summary["usage"]["provider_tokens"])
        self.assertIsNone(summary["usage"]["embedding_usage"])
        self.assertEqual(summary["metering"]["provider_tokens"], "unavailable")

    def test_h_to_o_analytics_are_measured_and_explicit(self):
        bot = Bot(name="Analytics", customer_id=self.customer.id, organization_id=self.org.id)
        self.db.add(bot)
        self.db.flush()
        session = ConversationSession(
            bot_id=bot.id,
            organization_id=self.org.id,
            session_id=f"session-{self.uid}",
            channel="widget",
        )
        self.db.add(session)
        self.db.flush()
        questions = [
            ("How do I return this?", False, True, True),
            ("How do I return this?", False, True, True),
            ("Where is my invoice?", True, True, False),
        ]
        for index, (question, fallback, attempted, hit) in enumerate(questions):
            self.db.add(ConversationMessage(
                conversation_session_id=session.id,
                bot_id=bot.id,
                organization_id=self.org.id,
                session_id=session.session_id,
                client_turn_id=f"analytics-{index}",
                user_message=question,
                assistant_response="answer",
                status="success",
                is_fallback=fallback,
                retrieval_attempted=attempted,
                had_knowledge_hit=hit,
            ))
        self.db.commit()
        result = get_organization_analytics_details(self.db, self.org.id)
        self.assertEqual(result["summary"]["chat_sessions"], 1)
        self.assertNotIn("unique_visitors", result["summary"])
        self.assertNotIn("resolution_rate", result["summary"])
        self.assertEqual(result["insights"]["top_questions"][0], {
            "question": "How do I return this?", "count": 2,
        })
        self.assertEqual(result["insights"]["frequent_unanswered_questions"][0]["question"], "Where is my invoice?")
        self.assertNotIn("suggested_improvements", result["insights"])
        self.assertIn("largest_knowledge_sources", result)
        self.assertEqual(result["summary"]["retrieval_attempt_rate"], 100.0)
        self.assertAlmostEqual(result["summary"]["evidence_found_rate"], 200 / 3)
        self.assertEqual(result["window"]["label"], "Last 30 days")
        self.assertEqual(result["trends"]["window"], "Last 7 days")

    def test_h_zero_state_has_no_fake_resolution_metric(self):
        result = get_organization_analytics_details(self.db, self.org.id)
        self.assertEqual(result["summary"]["chat_sessions"], 0)
        self.assertNotIn("resolution_rate", result["summary"])
        self.assertEqual(result["summary"]["evidence_found_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
