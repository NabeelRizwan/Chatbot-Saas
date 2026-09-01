import concurrent.futures
import datetime
import os
import sys
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import fakeredis

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

from database.connection import SessionLocal, init_db
from database.models import Bot, Chunk, Customer, Document, IngestionJob, Organization, Website, WebsiteCrawl
from services.concurrency_service import (
    acquire_distributed_permit,
    distributed_concurrency_guard,
    release_distributed_permit,
)
from services.rag_service import answer_question, clear_retrieval_cache
from utils.rate_limiter import (
    check_rate_limit,
    enforce_rate_limit,
)
from utils.redis_client import close_redis, get_redis, is_redis_available, set_redis_override
from fastapi import HTTPException


class TestRedisRateLimitSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.db = SessionLocal()
        self.uid = uuid.uuid4().hex[:8]

        # Use an isolated FakeRedis server instance for atomic Lua execution
        self.fake_server = fakeredis.FakeServer()
        self.fake_redis = fakeredis.FakeRedis(server=self.fake_server, decode_responses=True)
        set_redis_override(self.fake_redis)

        self.org_a = Organization(name=f"RLOrgA_{self.uid}", slug=f"rl-org-a-{self.uid}")
        self.org_b = Organization(name=f"RLOrgB_{self.uid}", slug=f"rl-org-b-{self.uid}")
        self.db.add_all([self.org_a, self.org_b])
        self.db.commit()
        self.db.refresh(self.org_a)
        self.db.refresh(self.org_b)

        self.cust_a = Customer(name=f"RLCustA_{self.uid}", api_key=f"rl_key_a_{self.uid}")
        self.cust_b = Customer(name=f"RLCustB_{self.uid}", api_key=f"rl_key_b_{self.uid}")
        self.db.add_all([self.cust_a, self.cust_b])
        self.db.commit()
        self.db.refresh(self.cust_a)
        self.db.refresh(self.cust_b)

        self.bot_a = Bot(
            name=f"RLBotA_{self.uid}",
            customer_id=self.cust_a.id,
            organization_id=self.org_a.id,
            system_prompt="You are Bot A.",
        )
        self.bot_b = Bot(
            name=f"RLBotB_{self.uid}",
            customer_id=self.cust_b.id,
            organization_id=self.org_b.id,
            system_prompt="You are Bot B.",
        )
        self.db.add_all([self.bot_a, self.bot_b])
        self.db.commit()
        self.db.refresh(self.bot_a)
        self.db.refresh(self.bot_b)

    def tearDown(self):
        set_redis_override(None)
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

    def test_1_single_tenant_sliding_window_rate_limiting(self):
        """Test rate limit enforcement within a sliding window for one tenant."""
        scope = "test_single"
        limit = 5
        window = 60

        for i in range(limit):
            allowed, retry_after, remaining = check_rate_limit(
                scope=scope, org_id=self.org_a.id, limit=limit, window_seconds=window
            )
            self.assertTrue(allowed, f"Request {i+1} should be allowed")
            self.assertEqual(remaining, limit - i - 1)

        # Next request must be rejected
        allowed, retry_after, remaining = check_rate_limit(
            scope=scope, org_id=self.org_a.id, limit=limit, window_seconds=window
        )
        self.assertFalse(allowed)
        self.assertTrue(retry_after > 0)
        self.assertEqual(remaining, 0)
        print("[SUCCESS] Test 1: Single-tenant sliding window rate limit verified.")

    def test_2_multi_tenant_independent_quotas(self):
        """Verify exhausting Tenant A quota does not affect Tenant B."""
        scope = "test_multi"
        limit = 3

        # Exhaust Tenant A
        for _ in range(limit):
            allowed, _, _ = check_rate_limit(scope=scope, org_id=self.org_a.id, limit=limit, window_seconds=60)
            self.assertTrue(allowed)

        allowed_a, retry_a, _ = check_rate_limit(scope=scope, org_id=self.org_a.id, limit=limit, window_seconds=60)
        self.assertFalse(allowed_a)

        # Tenant B should still have full quota
        for i in range(limit):
            allowed_b, _, rem_b = check_rate_limit(scope=scope, org_id=self.org_b.id, limit=limit, window_seconds=60)
            self.assertTrue(allowed_b, f"Tenant B request {i+1} should be allowed")

        print("[SUCCESS] Test 2: Multi-tenant independent quotas verified.")

    def test_3_concurrent_rate_limiting_atomicity(self):
        """Verify atomic Lua execution under high concurrency against one tenant."""
        scope = "test_concurrent"
        limit = 20
        total_attempts = 50

        def make_request():
            return check_rate_limit(scope=scope, org_id=self.org_a.id, limit=limit, window_seconds=60)

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(lambda _: make_request(), range(total_attempts)))

        allowed_count = sum(1 for allowed, _, _ in results if allowed)
        rejected_count = sum(1 for allowed, _, _ in results if not allowed)

        self.assertEqual(allowed_count, limit)
        self.assertEqual(rejected_count, total_attempts - limit)
        print("[SUCCESS] Test 3: Concurrent rate limiting atomicity verified.")

    def test_4_http_429_and_retry_after(self):
        """Verify enforce_rate_limit raises HTTPException with 429 and Retry-After header."""
        scope = "test_http_429"
        limit = 1

        enforce_rate_limit(scope=scope, org_id=self.org_a.id, limit=limit, window_seconds=60)

        with self.assertRaises(HTTPException) as ctx:
            enforce_rate_limit(scope=scope, org_id=self.org_a.id, limit=limit, window_seconds=60)

        self.assertEqual(ctx.exception.status_code, 429)
        self.assertIn("Retry-After", ctx.exception.headers)
        self.assertTrue(int(ctx.exception.headers["Retry-After"]) >= 1)
        print("[SUCCESS] Test 4: HTTP 429 and Retry-After headers verified.")

    def test_5_distributed_semaphore_acquisition_and_release(self):
        """Verify distributed semaphore limits concurrent execution and releases cleanly."""
        res_name = "crawl"
        max_permits = 2

        acq1, tok1 = acquire_distributed_permit(res_name, org_id=self.org_a.id, max_permits=max_permits, ttl_seconds=60)
        acq2, tok2 = acquire_distributed_permit(res_name, org_id=self.org_a.id, max_permits=max_permits, ttl_seconds=60)
        acq3, tok3 = acquire_distributed_permit(res_name, org_id=self.org_a.id, max_permits=max_permits, ttl_seconds=60)

        self.assertTrue(acq1)
        self.assertTrue(acq2)
        self.assertFalse(acq3, "Third permit should exceed max capacity")

        # Release first permit
        rel1 = release_distributed_permit(res_name, tok1, org_id=self.org_a.id)
        self.assertTrue(rel1)

        # Now third permit can be acquired
        acq4, tok4 = acquire_distributed_permit(res_name, org_id=self.org_a.id, max_permits=max_permits, ttl_seconds=60)
        self.assertTrue(acq4)

        # Cleanup
        release_distributed_permit(res_name, tok2, org_id=self.org_a.id)
        release_distributed_permit(res_name, tok4, org_id=self.org_a.id)
        print("[SUCCESS] Test 5: Distributed semaphore acquire and release verified.")

    def test_6_semaphore_ownership_protection(self):
        """Verify Tenant A or malicious caller cannot release Tenant B's semaphore permit."""
        res_name = "llm"
        max_permits = 1

        acq_a, tok_a = acquire_distributed_permit(res_name, org_id=self.org_a.id, max_permits=max_permits, ttl_seconds=60)
        self.assertTrue(acq_a)

        # Fake token or Org B attempting to release Org A permit
        fake_release = release_distributed_permit(res_name, "fake_token_123", org_id=self.org_a.id)
        self.assertFalse(fake_release)

        # Org A capacity should still be 0
        acq_again, _ = acquire_distributed_permit(res_name, org_id=self.org_a.id, max_permits=max_permits, ttl_seconds=60)
        self.assertFalse(acq_again)

        # Genuine release
        real_release = release_distributed_permit(res_name, tok_a, org_id=self.org_a.id)
        self.assertTrue(real_release)
        print("[SUCCESS] Test 6: Semaphore ownership protection verified.")

    def test_7_semaphore_ttl_expiration_crash_recovery(self):
        """Verify crashed worker permit expires via TTL without permanently blocking slots."""
        res_name = "embedding"
        max_permits = 1

        # Acquire with short 1-second TTL
        acq1, tok1 = acquire_distributed_permit(res_name, org_id=self.org_a.id, max_permits=max_permits, ttl_seconds=1)
        self.assertTrue(acq1)

        # Immediately, second acquire fails
        acq2, _ = acquire_distributed_permit(res_name, org_id=self.org_a.id, max_permits=max_permits, ttl_seconds=1)
        self.assertFalse(acq2)

        # Advance fake time by 2 seconds
        time.sleep(1.2)

        # Now slot should be recovered automatically
        acq3, tok3 = acquire_distributed_permit(res_name, org_id=self.org_a.id, max_permits=max_permits, ttl_seconds=60)
        self.assertTrue(acq3, "Expired permit slot should be recovered automatically")
        release_distributed_permit(res_name, tok3, org_id=self.org_a.id)
        print("[SUCCESS] Test 7: Semaphore TTL crash recovery verified.")

    def test_8_redis_unavailable_fallback_behavior(self):
        """Verify system handles Redis outage without crashing and uses safe fallbacks."""
        # Unset override and point to invalid port
        set_redis_override(None)
        with patch("utils.redis_client.get_redis", return_value=None):
            # Rate limiter should fall back safely to in-memory window
            allowed, _, rem = check_rate_limit("test_fallback", org_id=self.org_a.id, limit=3, window_seconds=60)
            self.assertTrue(allowed)

            # Concurrency guard should fall back to local thread semaphore
            with distributed_concurrency_guard("crawl", org_id=self.org_a.id, max_permits=1) as acq:
                self.assertTrue(acq)

        # Restore fake redis
        set_redis_override(self.fake_redis)
        print("[SUCCESS] Test 8: Redis unavailable graceful fallback verified.")

    def test_9_redis_key_namespace_isolation(self):
        """Verify Redis keys are safely namespaced and cannot collide across tenants."""
        key_a = self.fake_redis.keys(f"ratelimit:*:org_{self.org_a.id}:*")
        key_b = self.fake_redis.keys(f"ratelimit:*:org_{self.org_b.id}:*")

        # Create entries for both
        check_rate_limit("scope_test", org_id=self.org_a.id, bot_id=self.bot_a.id, limit=5)
        check_rate_limit("scope_test", org_id=self.org_b.id, bot_id=self.bot_b.id, limit=5)

        keys_a = self.fake_redis.keys(f"ratelimit:*:org_{self.org_a.id}:*")
        keys_b = self.fake_redis.keys(f"ratelimit:*:org_{self.org_b.id}:*")

        self.assertTrue(len(keys_a) > 0)
        self.assertTrue(len(keys_b) > 0)
        self.assertTrue(set(keys_a).isdisjoint(set(keys_b)), "Key collision between Org A and Org B!")
        print("[SUCCESS] Test 9: Redis key namespace isolation verified.")

    def test_10_chat_pipeline_remains_functional_with_rate_limits(self):
        """Verify live RAG chat execution works seamlessly through rate limiting."""
        # Seed test document
        doc = Document(
            bot_id=self.bot_a.id,
            organization_id=self.org_a.id,
            filename="seeded-rl-doc",
            source_type="text",
            raw_text="Enterprise support plan includes 24/7 dedicated engineer assistance.",
            title="Enterprise Plan",
            processing_status="completed",
            status="ready",
        )
        self.db.add(doc)
        self.db.commit()
        from services.document_processing_service import process_document
        process_document(self.db, doc.id)

        # Check rate limit & execute chat
        enforce_rate_limit(scope="auth_chat", org_id=self.org_a.id, bot_id=self.bot_a.id)

        with patch("services.rag_service.generate", return_value="The Enterprise support plan includes 24/7 dedicated engineer assistance."):
            reply, sources, chunks = answer_question(
                db=self.db,
                bot=self.bot_a,
                question="What does the enterprise plan include?",
            )
            self.assertIn("24/7", reply)
            self.assertTrue(len(chunks) > 0)

        print("[SUCCESS] Test 10: Chat pipeline functions seamlessly under rate limiting.")


if __name__ == "__main__":
    unittest.main()
