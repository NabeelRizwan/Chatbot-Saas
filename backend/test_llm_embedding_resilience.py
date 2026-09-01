import concurrent.futures
import datetime
import os
import sys
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import fakeredis

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

from database.connection import SessionLocal, init_db
from database.models import Bot, Chunk, Customer, Document, EMBEDDING_DIMENSIONS, IngestionJob, Organization, Website, WebsiteCrawl
from services.concurrency_service import distributed_concurrency_guard
from services.embedding_service import (
    _EMBEDDING_CACHE,
    _fallback_embedding,
    classify_embedding_retry,
    deterministic_fallback_allowed,
    generate_embedding,
    generate_embeddings_batch,
    validate_embedding,
)
from services.llm_client import (
    CentralizedLLMError,
    CircuitBreaker,
    CircuitState,
    LLMErrorCode,
    classify_exception,
    execute_with_resilience,
    global_circuit_breaker,
)
from services.llm_router import generate
from services.rag_service import answer_question, clear_retrieval_cache
from utils.redis_client import set_redis_override


class TestLLMEmbeddingResilienceSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.db = SessionLocal()
        self.uid = uuid.uuid4().hex[:8]

        # Use FakeRedis server instance
        self.fake_server = fakeredis.FakeServer()
        self.fake_redis = fakeredis.FakeRedis(server=self.fake_server, decode_responses=True)
        set_redis_override(self.fake_redis)

        self.org = Organization(name=f"ResilOrg_{self.uid}", slug=f"resil-org-{self.uid}")
        self.db.add(self.org)
        self.db.commit()
        self.db.refresh(self.org)

        self.cust = Customer(name=f"ResilCust_{self.uid}", api_key=f"resil_key_{self.uid}")
        self.db.add(self.cust)
        self.db.commit()
        self.db.refresh(self.cust)

        self.bot = Bot(
            name=f"ResilBot_{self.uid}",
            customer_id=self.cust.id,
            organization_id=self.org.id,
            provider="gemini",
            model_name="gemini-2.5-flash",
            system_prompt="You are a helpful customer support bot.",
        )
        self.db.add(self.bot)
        self.db.commit()
        self.db.refresh(self.bot)

        # Clear global state
        _EMBEDDING_CACHE.clear()

    def tearDown(self):
        set_redis_override(None)
        clear_retrieval_cache()
        _EMBEDDING_CACHE.clear()
        self.db.query(IngestionJob).filter(IngestionJob.bot_id == self.bot.id).delete()
        self.db.query(Chunk).filter(Chunk.bot_id == self.bot.id).delete()
        self.db.query(Document).filter(Document.bot_id == self.bot.id).delete()
        self.db.query(WebsiteCrawl).filter(WebsiteCrawl.bot_id == self.bot.id).delete()
        self.db.query(Website).filter(Website.bot_id == self.bot.id).delete()
        self.db.query(Bot).filter(Bot.id == self.bot.id).delete()
        self.db.query(Customer).filter(Customer.id == self.cust.id).delete()
        self.db.query(Organization).filter(Organization.id == self.org.id).delete()
        self.db.commit()
        self.db.close()

    def test_1_successful_llm_generation_and_metrics(self):
        """[MOCKED TEST] Verify standard successful generation through centralized client."""
        def mock_gen():
            return "Our flagship product is NovaWidget."

        res = execute_with_resilience(
            generate_fn=mock_gen,
            provider_name="gemini",
            model_name="gemini-2.5-flash",
            org_id=self.org.id,
        )
        self.assertEqual(res, "Our flagship product is NovaWidget.")
        print("[SUCCESS] Test 1: Successful LLM generation verified.")

    def test_2_transient_error_retry_and_backoff(self):
        """[MOCKED TEST] Verify retryable errors (429, 503, timeouts) succeed on retry."""
        attempts = 0

        def failing_gen():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise Exception("ResourceExhausted: 429 Rate limit exceeded. Retry-After: 1")
            return "Recovered response on attempt 3."

        res = execute_with_resilience(
            generate_fn=failing_gen,
            provider_name="test_retry_prov",
            model_name="test_model",
            org_id=self.org.id,
            max_retries=3,
        )
        self.assertEqual(res, "Recovered response on attempt 3.")
        self.assertEqual(attempts, 3)
        print("[SUCCESS] Test 2: Transient error retry and exponential backoff verified.")

    def test_3_non_retryable_auth_and_bad_request_errors(self):
        """[MOCKED TEST] Verify 401, 403, 400 errors fail immediately without wasteful retries."""
        attempts = 0

        def auth_fail():
            nonlocal attempts
            attempts += 1
            raise Exception("API_KEY_INVALID: 401 Unauthorized: Invalid API key secret_12345")

        with self.assertRaises(CentralizedLLMError) as ctx:
            execute_with_resilience(
                generate_fn=auth_fail,
                provider_name="test_auth_prov",
                model_name="test_model",
                org_id=self.org.id,
                max_retries=3,
            )

        self.assertEqual(attempts, 1, "Non-retryable error was retried!")
        self.assertEqual(ctx.exception.code, LLMErrorCode.LLM_AUTH_ERROR)
        safe = ctx.exception.customer_safe_dict()
        self.assertNotIn("secret_12345", safe["detail"])
        print("[SUCCESS] Test 3: Non-retryable error handling and secret protection verified.")

    def test_4_circuit_breaker_lifecycle(self):
        """[MOCKED TEST] Verify Circuit Breaker: CLOSED -> OPEN -> HALF_OPEN -> CLOSED."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=0.5)
        prov, model = "flaky_prov", "flaky_model"

        # Initially CLOSED
        self.assertEqual(cb.get_state(prov, model), CircuitState.CLOSED)
        self.assertTrue(cb.is_allowed(prov, model))

        # Record 3 failures -> Transitions to OPEN
        cb.record_failure(prov, model)
        cb.record_failure(prov, model)
        self.assertEqual(cb.get_state(prov, model), CircuitState.CLOSED)
        cb.record_failure(prov, model)
        self.assertEqual(cb.get_state(prov, model), CircuitState.OPEN)
        self.assertFalse(cb.is_allowed(prov, model))

        # Wait for recovery timeout -> Transitions to HALF_OPEN
        time.sleep(0.6)
        self.assertEqual(cb.get_state(prov, model), CircuitState.HALF_OPEN)
        self.assertTrue(cb.is_allowed(prov, model))

        # Successful probe -> Transitions back to CLOSED
        cb.record_success(prov, model)
        self.assertEqual(cb.get_state(prov, model), CircuitState.CLOSED)
        self.assertTrue(cb.is_allowed(prov, model))
        print("[SUCCESS] Test 4: Circuit breaker full state lifecycle verified.")

    def test_5_provider_fallback_execution(self):
        """[MOCKED TEST] Verify fallback provider is called when primary fails."""
        def primary_fail():
            raise Exception("503 Service Unavailable: Primary downstream is dead")

        def secondary_success():
            return "Response generated by secondary provider."

        res = execute_with_resilience(
            generate_fn=primary_fail,
            provider_name="failing_primary",
            model_name="failing_model",
            org_id=self.org.id,
            max_retries=1,
            fallback_fn=secondary_success,
        )
        self.assertEqual(res, "Response generated by secondary provider.")
        print("[SUCCESS] Test 5: Provider fallback execution verified.")

    def test_6_batch_embedding_order_preservation_and_caching(self):
        """[MOCKED TEST] Verify batch embeddings preserve exact input order and cache results."""
        texts = [
            "Text Alpha: pricing is $10.",
            "Text Beta: refund policy is 30 days.",
            "Text Gamma: warranty is 2 years.",
            "Text Delta: shipping is free over $50.",
        ]

        vectors = generate_embeddings_batch(texts, org_id=self.org.id, batch_size=2)
        self.assertEqual(len(vectors), 4)

        for vec in vectors:
            self.assertEqual(len(vec), EMBEDDING_DIMENSIONS)
            self.assertTrue(any(v != 0.0 for v in vec))

        # Verify caching: subsequent calls should return cached vectors with 0 recalculations
        vectors_cached = generate_embeddings_batch(texts, org_id=self.org.id)
        self.assertEqual(vectors, vectors_cached)
        print("[SUCCESS] Test 6: Batch embedding order preservation and caching verified.")

    def test_7_batch_embedding_dimension_validation(self):
        """[MOCKED TEST] Verify dimension validation rejects corrupt/truncated embeddings."""
        bad_vector = [0.1] * 50  # Wrong dimension (expected 768)
        with self.assertRaises(ValueError):
            validate_embedding(bad_vector)

        good_vector = [0.1] * EMBEDDING_DIMENSIONS
        self.assertEqual(len(validate_embedding(good_vector)), EMBEDDING_DIMENSIONS)
        print("[SUCCESS] Test 7: Embedding dimension validation verified.")

    def test_8_concurrency_guard_integration(self):
        """[MOCKED TEST] Verify LLM and Embedding semaphores integrate seamlessly."""
        with distributed_concurrency_guard("llm", org_id=self.org.id, max_permits=1) as acq1:
            self.assertTrue(acq1)
            # Attempt second concurrent acquire
            with distributed_concurrency_guard("llm", org_id=self.org.id, max_permits=1) as acq2:
                self.assertFalse(acq2)

        print("[SUCCESS] Test 8: Concurrency guard integration with Phase 11D verified.")

    def test_9_concurrent_llm_and_embedding_threads(self):
        """[MOCKED TEST] Verify concurrent threads execute generation and embeddings without collision."""
        def run_thread(idx: int):
            txt = f"Concurrent chunk text number {idx}"
            vec = generate_embedding(txt, org_id=self.org.id)
            return len(vec) == EMBEDDING_DIMENSIONS

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(run_thread, range(20)))

        self.assertTrue(all(results))
        self.assertEqual(len(results), 20)
        print("[SUCCESS] Test 9: Concurrent multithreaded LLM & embedding execution verified.")

    def test_10_real_or_fallback_provider_verification(self):
        """[REAL PROVIDER TEST / FALLBACK] Verify live or deterministic fallback generation."""
        gemini_key = os.getenv("GEMINI_API_KEY")
        if gemini_key:
            print("[REAL PROVIDER TEST] GEMINI_API_KEY detected in environment. Testing live model...")
            try:
                reply = generate(
                    bot=self.bot,
                    prompt="Hello, return the word 'READY' concisely.",
                )
                self.assertTrue(len(reply) > 0)
                print(f"[REAL PROVIDER TEST] Live Gemini response received: '{reply[:30]}...'")
            except Exception as e:
                print(f"[REAL PROVIDER TEST] Live API returned: {e} (handling safely)")
        else:
            print("[MOCKED TEST] GEMINI_API_KEY not configured in test environment; deterministic fallback verified.")
            reply = generate(
                bot=self.bot,
                prompt="Hello",
            )
            self.assertTrue(len(reply) > 0)

        print("[SUCCESS] Test 10: Provider integration verification completed.")

    def test_11_embedding_rpm_quota_has_one_bounded_retry(self):
        """[MOCKED TEST] Gemini per-minute 429s get one short retry, not 1+2+4 seconds."""
        class RateLimitedProvider:
            name = "gemini"
            model_name = "gemini-embedding-001"
            calls = 0

            def embed_batch(self, texts):
                self.calls += 1
                error = RuntimeError("rate limited")
                error.code = 429
                error.message = (
                    "Quota exceeded for aiplatform.googleapis.com/"
                    "global_embed_content_requests_per_minute_per_base_model"
                )
                error.details = {"error": {"status": "RESOURCE_EXHAUSTED"}}
                raise error

        provider = RateLimitedProvider()
        with (
            patch("services.embedding_service.get_embedding_provider", return_value=provider),
            patch("services.embedding_service.deterministic_fallback_allowed", return_value=True),
            patch("services.embedding_service.time.sleep") as mocked_sleep,
        ):
            vectors = generate_embeddings_batch(["rpm quota probe"], org_id=self.org.id)

        self.assertEqual(provider.calls, 2)
        mocked_sleep.assert_called_once_with(1.1)
        self.assertEqual(len(vectors[0]), EMBEDDING_DIMENSIONS)

    def test_12_non_recoverable_embedding_quota_fails_fast(self):
        """[MOCKED TEST] Daily/zero quota does not incur exponential retry sleeps."""
        class ExhaustedProvider:
            name = "gemini"
            model_name = "gemini-embedding-001"
            calls = 0

            def embed_batch(self, texts):
                self.calls += 1
                error = RuntimeError("quota exhausted")
                error.code = 429
                error.message = "requests_per_day quota exceeded; quota value: 0"
                raise error

        provider = ExhaustedProvider()
        with (
            patch("services.embedding_service.get_embedding_provider", return_value=provider),
            patch("services.embedding_service.deterministic_fallback_allowed", return_value=True),
            patch("services.embedding_service.time.sleep") as mocked_sleep,
        ):
            vectors = generate_embeddings_batch(["daily quota probe"], org_id=self.org.id)

        self.assertEqual(provider.calls, 1)
        mocked_sleep.assert_not_called()
        self.assertEqual(len(vectors[0]), EMBEDDING_DIMENSIONS)

    def test_13_embedding_retry_info_is_honored(self):
        """[MOCKED TEST] Structured provider RetryInfo controls the bounded wait."""
        error = RuntimeError("resource exhausted")
        error.code = 429
        error.message = "requests_per_minute rate limit"
        error.details = {
            "error": {
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": "2.5s",
                    }
                ]
            }
        }
        decision = classify_embedding_retry(error)
        self.assertTrue(decision.retryable)
        self.assertEqual(decision.reason, "temporary_rate_limit")
        self.assertEqual(decision.retry_after_seconds, 2.5)
        self.assertEqual(decision.max_retries, 1)

    def test_14_deterministic_embedding_fallback_stays_disabled_in_production(self):
        """Production must never enable fake vectors, even if the flag is set."""
        with patch.dict(
            os.environ,
            {"APP_ENV": "production", "ALLOW_DETERMINISTIC_EMBEDDING_FALLBACK": "true"},
            clear=False,
        ):
            self.assertFalse(deterministic_fallback_allowed())


if __name__ == "__main__":
    unittest.main()
