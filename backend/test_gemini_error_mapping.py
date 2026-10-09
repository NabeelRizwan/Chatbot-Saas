import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from google.genai import errors, types

from services.llm_client import CentralizedLLMError, classify_exception, execute_with_resilience
from services.providers.base_provider import ProviderError, ProviderErrorKind
from services.providers.gemini_provider import GeminiProvider


SECRET = "private-key-and-provider-payload"


def quota_error(quota_id, delay="20429s"):
    return errors.ClientError(429, {"error": {
        "message": SECRET,
        "details": [
            {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
                {"quotaId": quota_id, "description": SECRET, "quotaValue": "20"}
            ]},
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay},
        ],
    }})


class GeminiErrorMappingTests(unittest.TestCase):
    def setUp(self):
        self.provider = GeminiProvider()
        self.client = Mock()
        self.provider._client = Mock(return_value=self.client)
        self.arguments = dict(api_key=SECRET, model_name="configured-model", prompt="question",
                              system_instruction="instruction", temperature=0.37)

    def mapped(self, error, *, stream=False):
        method = self.client.models.generate_content_stream if stream else self.client.models.generate_content
        method.side_effect = error
        with self.assertRaises(ProviderError) as caught:
            if stream:
                list(self.provider.generate_stream(**self.arguments))
            else:
                self.provider.generate_with_metadata(**self.arguments)
        self.assertNotIn(SECRET, str(caught.exception))
        self.assertNotIn(SECRET, caught.exception.message)
        return caught.exception

    def test_sdk_daily_quota_stops_central_retries(self):
        error = quota_error("GenerateRequestsPerDayPerProjectPerModel-FreeTier")
        self.assertEqual(error.code, 429)
        self.assertFalse(hasattr(error, "status_code"))
        self.client.models.generate_content.side_effect = error
        with patch("services.llm_client.distributed_concurrency_guard", return_value=nullcontext(True)), \
                patch("services.llm_client.global_circuit_breaker") as breaker, \
                patch("services.llm_client.time.sleep") as sleep:
            breaker.is_allowed.return_value = True
            with self.assertRaises(CentralizedLLMError) as caught:
                execute_with_resilience(lambda: self.provider.generate_with_metadata(**self.arguments),
                                        "gemini", "configured-model", max_retries=3)
        self.assertFalse(caught.exception.retryable)
        self.assertEqual(caught.exception.status_code, 429)
        self.assertNotIn(SECRET, str(caught.exception))
        self.client.models.generate_content.assert_called_once()
        sleep.assert_not_called()

    def test_daily_quota_both_generation_paths(self):
        for stream in (False, True):
            with self.subTest(stream=stream):
                mapped = self.mapped(quota_error("GenerateRequestsPerDayPerProjectPerModel-FreeTier"), stream=stream)
                self.assertEqual(mapped.kind, ProviderErrorKind.QUOTA_EXHAUSTED)
                self.assertEqual(mapped.retry_after_seconds, 20429)
                self.assertFalse(classify_exception(mapped)[1])

    def test_minute_quota_is_retryable_and_rounds_delay_up(self):
        for stream in (False, True):
            with self.subTest(stream=stream):
                mapped = self.mapped(quota_error("GenerateRequestsPerMinutePerProjectPerModel", "1.25s"), stream=stream)
                self.assertEqual(mapped.kind, ProviderErrorKind.RATE_LIMIT)
                self.assertEqual(mapped.retry_after_seconds, 2)
                self.assertTrue(classify_exception(mapped)[1])

    def test_status_mapping_in_both_paths(self):
        cases = [(400, ProviderErrorKind.INVALID_REQUEST), (401, ProviderErrorKind.AUTHENTICATION),
                 (402, ProviderErrorKind.BILLING_RESTRICTION), (403, ProviderErrorKind.AUTHENTICATION),
                 (404, ProviderErrorKind.INVALID_MODEL), (408, ProviderErrorKind.TIMEOUT),
                 (429, ProviderErrorKind.RATE_LIMIT), (503, ProviderErrorKind.TEMPORARY),
                 (504, ProviderErrorKind.TIMEOUT)]
        for stream in (False, True):
            for status, kind in cases:
                with self.subTest(status=status, stream=stream):
                    error_class = errors.ServerError if status >= 500 else errors.ClientError
                    mapped = self.mapped(error_class(status, {"error": {"message": SECRET}}), stream=stream)
                    self.assertEqual((mapped.status_code, mapped.kind), (status, kind))

    def test_code_precedence_and_status_code_fallback(self):
        error = errors.ClientError(403, {})
        error.status_code = 429
        self.assertEqual(self.mapped(error).kind, ProviderErrorKind.AUTHENTICATION)
        for invalid_code in (None, "not-an-http-code", True, 0):
            with self.subTest(code=invalid_code):
                error.code = invalid_code
                self.assertEqual(self.mapped(error).kind, ProviderErrorKind.RATE_LIMIT)

    def test_raw_message_or_untyped_details_do_not_prove_daily_quota(self):
        for payload in (
            {"error": {"message": "daily quota exceeded " + SECRET}},
            {"error": {"details": [{"violations": [{"quotaId": "PerDay"}]}]}},
            {"error": {"details": [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                                      "violations": [{"description": "PerDay"}]}]}},
            {"error": {"details": None}},
            {"error": {"details": [None, "PerDay", {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                                                       "violations": "PerDay"}]}},
        ):
            with self.subTest(payload=payload):
                mapped = self.mapped(errors.ClientError(429, payload))
                self.assertEqual(mapped.kind, ProviderErrorKind.RATE_LIMIT)

    def test_direct_details_and_snake_case_quota_metric(self):
        payload = {"details": [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                                 "violations": [{"quota_metric": "service/requests_per_day"}]}]}
        self.assertEqual(self.mapped(errors.ClientError(429, payload)).kind, ProviderErrorKind.QUOTA_EXHAUSTED)

    def test_invalid_retry_info_is_ignored(self):
        for delay in (None, -1, "-1s", "NaNs", "Infinitys", "1e10s", "315576000001s", "12", {"seconds": 3}):
            with self.subTest(delay=delay):
                mapped = self.mapped(quota_error("GenerateRequestsPerMinute", delay))
                self.assertIsNone(mapped.retry_after_seconds)

    def test_retry_after_header_and_retry_info_use_larger_delay(self):
        error = quota_error("GenerateRequestsPerMinute", "2.5s")
        error.response = httpx.Response(429, headers={"Retry-After": "7"})
        self.assertEqual(self.mapped(error).retry_after_seconds, 7)
        error.response = httpx.Response(429, headers={"Retry-After": "NaN"})
        self.assertEqual(self.mapped(error).retry_after_seconds, 3)

    def test_partial_stream_error_never_restarts_and_duplicates_text(self):
        def partial():
            yield SimpleNamespace(text="first part")
            raise quota_error("GenerateRequestsPerMinute", "1s")
        self.client.models.generate_content_stream.return_value = partial()
        stream = self.provider.generate_stream(**self.arguments)
        self.assertEqual(next(stream), "first part")
        with self.assertRaises(ProviderError) as caught:
            next(stream)
        self.assertEqual(caught.exception.kind, ProviderErrorKind.RATE_LIMIT)
        self.client.models.generate_content_stream.assert_called_once()

    def test_transport_errors_do_not_return_payload(self):
        for stream in (False, True):
            for error, kind in ((RuntimeError(SECRET), ProviderErrorKind.UNAVAILABLE),
                                (TimeoutError("timeout " + SECRET), ProviderErrorKind.TIMEOUT),
                                (TimeoutError(), ProviderErrorKind.TIMEOUT),
                                (httpx.ReadTimeout(""), ProviderErrorKind.TIMEOUT)):
                with self.subTest(stream=stream, kind=kind):
                    self.assertEqual(self.mapped(error, stream=stream).kind, kind)

    def test_missing_key_is_authentication_in_both_paths(self):
        for stream in (False, True):
            with self.subTest(stream=stream), self.assertRaises(ProviderError) as caught:
                arguments = dict(self.arguments, api_key="")
                if stream:
                    list(self.provider.generate_stream(**arguments))
                else:
                    self.provider.generate_with_metadata(**arguments)
            self.assertEqual(caught.exception.kind, ProviderErrorKind.AUTHENTICATION)
        self.provider._client.assert_not_called()

    def test_success_preserves_generation_settings_usage_and_stream(self):
        self.client.models.generate_content.return_value = SimpleNamespace(
            text="answer", usage_metadata=SimpleNamespace(prompt_token_count=12, candidates_token_count=4),
            candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)])
        result = self.provider.generate_with_metadata(**self.arguments)
        self.assertEqual((result.text, result.model, result.usage.total_tokens, result.finish_reason),
                         ("answer", "configured-model", 16, "STOP"))
        self.client.models.generate_content_stream.return_value = iter([SimpleNamespace(text="a"), SimpleNamespace(text="b")])
        self.assertEqual(list(self.provider.generate_stream(**self.arguments)), ["a", "b"])
        for method in (self.client.models.generate_content, self.client.models.generate_content_stream):
            kwargs = method.call_args.kwargs
            self.assertEqual((kwargs["model"], kwargs["contents"]), ("configured-model", "question"))
            self.assertEqual((kwargs["config"].temperature, kwargs["config"].system_instruction), (0.37, "instruction"))


if __name__ == "__main__":
    unittest.main()
