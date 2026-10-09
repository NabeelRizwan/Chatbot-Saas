import unittest
from contextlib import nullcontext
from unittest.mock import Mock, patch

from services.llm_client import CentralizedLLMError, LLMErrorCode, execute_with_resilience
from services.providers.base_provider import ProviderError, ProviderErrorKind


class LLMRetryWaitBudgetTests(unittest.TestCase):
    def setUp(self):
        patches = {
            "guard": patch("services.llm_client.distributed_concurrency_guard", return_value=nullcontext(True)),
            "breaker": patch("services.llm_client.global_circuit_breaker"),
            "sleep": patch("services.llm_client.time.sleep"),
            "jitter": patch("services.llm_client.random.uniform", return_value=0.2),
            "max_wait": patch("services.llm_client.LLM_BACKOFF_MAX", 10.0),
            "base_wait": patch("services.llm_client.LLM_BACKOFF_BASE", 1.0),
        }
        for name, patcher in patches.items():
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        self.breaker.is_allowed.return_value = True

    def test_long_rate_limit_returns_retryable_failure_without_sleep_or_second_call(self):
        error = ProviderError("Provider rate limited.", status_code=429,
                              kind=ProviderErrorKind.RATE_LIMIT, retry_after_seconds=20429)
        generate = Mock(side_effect=[error, "must not be generated"])
        fallback = Mock(return_value="must not switch providers")
        with self.assertRaises(CentralizedLLMError) as caught:
            execute_with_resilience(generate, "gemini", "configured-model", max_retries=3,
                                    fallback_fn=fallback)
        self.assertEqual(caught.exception.code, LLMErrorCode.LLM_RATE_LIMITED)
        self.assertEqual(caught.exception.status_code, 429)
        self.assertTrue(caught.exception.retryable)
        self.assertIs(caught.exception.__cause__, error)
        self.assertEqual(error.retry_after_seconds, 20429)
        generate.assert_called_once()
        fallback.assert_not_called()
        self.sleep.assert_not_called()
        self.breaker.record_failure.assert_called_once_with("gemini", "configured-model")

    def test_long_server_retry_hint_also_returns_immediately(self):
        generate = Mock(side_effect=ProviderError("Provider unavailable.", status_code=503,
                        kind=ProviderErrorKind.TEMPORARY, retry_after_seconds=11))
        with self.assertRaises(CentralizedLLMError) as caught:
            execute_with_resilience(generate, "other-provider", "model", max_retries=1)
        self.assertEqual(caught.exception.code, LLMErrorCode.LLM_PROVIDER_UNAVAILABLE)
        self.assertTrue(caught.exception.retryable)
        generate.assert_called_once()
        self.sleep.assert_not_called()

    def test_short_retry_hint_waits_at_least_provider_delay_then_succeeds(self):
        generate = Mock(side_effect=[ProviderError("Rate limited.", status_code=429,
                        kind=ProviderErrorKind.RATE_LIMIT, retry_after_seconds=7), "answer"])
        self.assertEqual(execute_with_resilience(generate, "gemini", "model", max_retries=1), "answer")
        self.assertEqual(generate.call_count, 2)
        self.sleep.assert_called_once_with(7.0)
        self.breaker.record_success.assert_called_once_with("gemini", "model")

    def test_hint_at_budget_boundary_still_retries(self):
        generate = Mock(side_effect=[ProviderError("Rate limited.", status_code=429,
                        kind=ProviderErrorKind.RATE_LIMIT, retry_after_seconds=10), "answer"])
        self.assertEqual(execute_with_resilience(generate, "gemini", "model", max_retries=1), "answer")
        self.sleep.assert_called_once_with(10.0)

    def test_missing_retry_hint_keeps_existing_backoff(self):
        generate = Mock(side_effect=[ProviderError("Unavailable.", status_code=503,
                        kind=ProviderErrorKind.TEMPORARY), "answer"])
        self.assertEqual(execute_with_resilience(generate, "gemini", "model", max_retries=1), "answer")
        self.sleep.assert_called_once_with(1.2)

    def test_fractional_hint_above_wait_budget_is_not_truncated_into_retry(self):
        generate = Mock(side_effect=ProviderError("Rate limited.", status_code=429,
                        kind=ProviderErrorKind.RATE_LIMIT, retry_after_seconds=10.5))
        with self.assertRaises(CentralizedLLMError):
            execute_with_resilience(generate, "other-provider", "model")
        generate.assert_called_once()
        self.sleep.assert_not_called()

    def test_fractional_retry_hint_rounds_up_never_before_provider_minimum(self):
        generate = Mock(side_effect=[ProviderError("Rate limited.", status_code=429,
                        kind=ProviderErrorKind.RATE_LIMIT, retry_after_seconds=2.1), "answer"])
        self.assertEqual(execute_with_resilience(generate, "other-provider", "model"), "answer")
        self.sleep.assert_called_once_with(3.0)


if __name__ == "__main__":
    unittest.main()
