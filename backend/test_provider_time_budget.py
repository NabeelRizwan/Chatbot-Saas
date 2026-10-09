import unittest
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from google import genai
from google.genai import types
from openai import APITimeoutError, InternalServerError

from services.llm_client import CentralizedLLMError, LLMErrorCode, execute_with_resilience
from services.providers.base_provider import (
    ProviderError, ProviderErrorKind, auxiliary_budget, generation_deadline, generation_timeout,
)
from services.providers.claude_provider import ClaudeProvider
from services.providers.gemini_provider import GeminiProvider
from services.providers.grok_provider import GrokProvider
from services.providers.openai_provider import OpenAIProvider


class RetryBudgetTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.held = False

        @contextmanager
        def guard(*args, **kwargs):
            self.held = True
            try:
                yield True
            finally:
                self.held = False

        patches = {
            "guard": patch("services.llm_client.distributed_concurrency_guard", side_effect=guard),
            "breaker": patch("services.llm_client.global_circuit_breaker"),
            "clock": patch("services.llm_client.time.monotonic", side_effect=lambda: self.now),
            "sleep": patch("services.llm_client.time.sleep", side_effect=self.advance),
            "jitter": patch("services.llm_client.random.uniform", return_value=0.2),
            "budget": patch("services.llm_client.LLM_TIMEOUT", 30.0),
            "max_wait": patch("services.llm_client.LLM_BACKOFF_MAX", 10.0),
            "base_wait": patch("services.llm_client.LLM_BACKOFF_BASE", 1.0),
        }
        for name, patcher in patches.items():
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        self.breaker.is_allowed.return_value = True

    def advance(self, seconds):
        self.assertTrue(self.held, "Permit must remain owned during calls and retry waits")
        self.now += seconds

    def timed_out(self, provider, elapsed):
        self.assertTrue(self.held)
        timeout = generation_timeout(20.0, minimum=10.0 if provider == "gemini" else 0.001)
        self.advance(elapsed if elapsed is not None else timeout)
        raise ProviderError("Provider timed out.", status_code=504, kind=ProviderErrorKind.TIMEOUT)

    def test_twenty_second_gemini_timeout_has_no_unusable_second_attempt(self):
        generate = Mock(side_effect=lambda: self.timed_out("gemini", 20.0))
        fallback = Mock()
        with self.assertRaises(CentralizedLLMError) as caught:
            execute_with_resilience(generate, "gemini", "selected-model", max_retries=3,
                                    fallback_fn=fallback)
        self.assertEqual((caught.exception.code, caught.exception.status_code), (LLMErrorCode.LLM_TIMEOUT, 504))
        self.assertTrue(caught.exception.retryable)
        generate.assert_called_once()
        fallback.assert_not_called()
        self.sleep.assert_not_called()
        self.assertEqual(self.now, 120.0)
        self.assertFalse(self.held)
        self.assertIsNone(generation_deadline.get())

    def test_fast_transient_retries_selected_model_without_extra_success_call(self):
        timeouts = []
        def generate():
            timeouts.append(generation_timeout(20.0, minimum=10.0))
            self.assertEqual(generation_deadline.get(), 130.0)
            self.advance(3.0)
            if len(timeouts) == 1:
                raise ProviderError("Temporarily unavailable.", status_code=503, kind=ProviderErrorKind.TEMPORARY)
            return "supported answer"
        self.assertEqual(execute_with_resilience(generate, "gemini", "selected-model"), "supported answer")
        self.assertEqual(timeouts, [20.0, 20.0])
        self.sleep.assert_called_once_with(1.2)
        self.breaker.record_success.assert_called_once_with("gemini", "selected-model")
        self.assertIsNone(generation_deadline.get())

    def test_later_gemini_attempt_receives_only_remaining_budget(self):
        timeouts = []
        def generate():
            timeouts.append(generation_timeout(20.0, minimum=10.0))
            return self.timed_out("gemini", 12.0 if len(timeouts) == 1 else None)
        with self.assertRaises(CentralizedLLMError):
            execute_with_resilience(generate, "gemini", "model", max_retries=3)
        self.assertEqual(len(timeouts), 2)
        self.assertAlmostEqual(timeouts[1], 16.8)
        self.assertAlmostEqual(self.now, 130.0)
        self.sleep.assert_called_once_with(1.2)

    def test_openai_can_use_short_remaining_attempt_and_stops_at_budget(self):
        timeouts = []
        def generate():
            timeouts.append(generation_timeout(20.0))
            return self.timed_out("openai", None)
        with self.assertRaises(CentralizedLLMError):
            execute_with_resilience(generate, "openai", "model", max_retries=3)
        self.assertEqual(len(timeouts), 2)
        self.assertAlmostEqual(timeouts[1], 8.8)
        self.assertAlmostEqual(self.now, 130.0)

    def test_required_retry_delay_is_not_shortened_to_fit(self):
        def generate():
            self.advance(15.0)
            raise ProviderError("Rate limited.", status_code=429, kind=ProviderErrorKind.RATE_LIMIT,
                                retry_after_seconds=7)
        generate = Mock(side_effect=generate)
        with self.assertRaises(CentralizedLLMError) as caught:
            execute_with_resilience(generate, "gemini", "model")
        self.assertEqual(caught.exception.code, LLMErrorCode.LLM_RATE_LIMITED)
        generate.assert_called_once()
        self.sleep.assert_not_called()

    def test_overslept_backoff_does_not_start_another_call(self):
        generate = Mock(side_effect=ProviderError("Unavailable.", status_code=503, kind=ProviderErrorKind.TEMPORARY))
        self.sleep.side_effect = lambda _: self.advance(40)
        with self.assertRaises(CentralizedLLMError):
            execute_with_resilience(generate, "gemini", "model")
        generate.assert_called_once()
        self.assertFalse(self.held)
        self.assertIsNone(generation_deadline.get())

    def test_budget_uses_monotonic_clock_and_success_has_no_wait(self):
        with patch("services.llm_client.time.time", side_effect=AssertionError("Wall clock used")):
            self.assertEqual(execute_with_resilience(lambda: "answer", "openai", "model"), "answer")
        self.sleep.assert_not_called()

    def test_inherited_budget_cannot_be_extended_and_is_restored(self):
        token = generation_deadline.set(112.0)
        try:
            self.assertEqual(execute_with_resilience(lambda: str(generation_deadline.get()), "gemini", "model"), "112.0")
            self.assertEqual(generation_deadline.get(), 112.0)
        finally:
            generation_deadline.reset(token)

    def test_expired_budget_fails_before_any_provider_call(self):
        generate = Mock()
        token = generation_deadline.set(99.0)
        try:
            with self.assertRaises(CentralizedLLMError) as caught:
                execute_with_resilience(generate, "openai", "model")
            self.assertEqual(caught.exception.code, LLMErrorCode.LLM_TIMEOUT)
        finally:
            generation_deadline.reset(token)
        generate.assert_not_called()
        self.breaker.record_failure.assert_not_called()

    def test_non_retryable_failure_releases_permit_and_request_context(self):
        generate = Mock(side_effect=ProviderError("Invalid credential.", status_code=401,
                                                kind=ProviderErrorKind.AUTHENTICATION))
        with self.assertRaises(CentralizedLLMError):
            execute_with_resilience(generate, "gemini", "model")
        generate.assert_called_once()
        self.assertFalse(self.held)
        self.assertIsNone(generation_deadline.get())


class AdapterBudgetTests(unittest.TestCase):
    def setUp(self):
        self.arguments = dict(api_key="fake-key", model_name="selected-model", prompt="question",
                              system_instruction="instruction", temperature=0.37)
        self.clock = patch("services.providers.base_provider.time.monotonic", return_value=100.0)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    @contextmanager
    def transport(self, provider_type):
        provider = provider_type()
        client = Mock()
        if provider_type is ClaudeProvider:
            client.post.return_value = httpx.Response(200, json={"content": [{"text": "answer"}],
                                                               "usage": {"input_tokens": 3, "output_tokens": 2}})
            with patch("services.providers.claude_provider.httpx.Client", return_value=nullcontext(client)):
                yield provider, client.post
        else:
            provider._client = Mock(return_value=client)
            if provider_type is GeminiProvider:
                method = client.models.generate_content
                method.return_value = SimpleNamespace(text="answer", usage_metadata=None, candidates=[])
            elif provider_type is OpenAIProvider:
                method = client.responses.create
                method.return_value = SimpleNamespace(output_text="answer", usage=None)
            else:
                method = client.chat.completions.create
                method.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="answer"))], usage=None)
            yield provider, method

    def timeout(self, provider_type, method):
        kwargs = method.call_args.kwargs
        return kwargs["config"].http_options.timeout / 1000 if provider_type is GeminiProvider else kwargs["timeout"]

    def test_all_adapters_use_remaining_budget_without_changing_model_or_prompt(self):
        token = generation_deadline.set(112.0)
        try:
            for provider_type in (GeminiProvider, OpenAIProvider, GrokProvider, ClaudeProvider):
                with self.subTest(provider=provider_type.__name__), self.transport(provider_type) as (provider, method):
                    self.assertEqual(provider.generate_with_metadata(**self.arguments).text, "answer")
                    self.assertEqual(self.timeout(provider_type, method), 12.0)
                    kwargs = method.call_args.kwargs
                    request = kwargs["json"] if provider_type is ClaudeProvider else kwargs
                    self.assertEqual(request["model"], "selected-model")
                    method.assert_called_once()
        finally:
            generation_deadline.reset(token)

    def test_generous_remaining_budget_preserves_existing_attempt_caps(self):
        token = generation_deadline.set(150.0)
        try:
            for provider_type, expected in ((GeminiProvider, 20.0), (OpenAIProvider, 20.0),
                                             (GrokProvider, 20.0), (ClaudeProvider, 30.0)):
                with self.subTest(provider=provider_type.__name__), self.transport(provider_type) as (provider, method):
                    provider.generate_with_metadata(**self.arguments)
                    self.assertEqual(self.timeout(provider_type, method), expected)
        finally:
            generation_deadline.reset(token)

    def test_expired_budget_prevents_every_adapter_transport_call(self):
        token = generation_deadline.set(99.0)
        try:
            for provider_type in (GeminiProvider, OpenAIProvider, GrokProvider, ClaudeProvider):
                with self.subTest(provider=provider_type.__name__), self.transport(provider_type) as (provider, method):
                    with self.assertRaises(ProviderError) as caught:
                        provider.generate_with_metadata(**self.arguments)
                    self.assertEqual(caught.exception.kind, ProviderErrorKind.TIMEOUT)
                    method.assert_not_called()
        finally:
            generation_deadline.reset(token)

    def test_auxiliary_transport_floor_and_token_limits_are_preserved(self):
        token = auxiliary_budget.set({"timeout": 5.0, "tokens": 128, "json_mode": True})
        deadline_token = generation_deadline.set(130.0)
        try:
            for provider_type in (GeminiProvider, OpenAIProvider, GrokProvider, ClaudeProvider):
                with self.subTest(provider=provider_type.__name__), self.transport(provider_type) as (provider, method):
                    provider.generate_with_metadata(**self.arguments)
                    self.assertEqual(self.timeout(provider_type, method), 10.0 if provider_type is GeminiProvider else 5.0)
                    kwargs = method.call_args.kwargs
                    if provider_type is GeminiProvider:
                        self.assertEqual(kwargs["config"].max_output_tokens, 128)
                        self.assertEqual(kwargs["config"].response_mime_type, "application/json")
                    elif provider_type is ClaudeProvider:
                        self.assertEqual(kwargs["json"]["max_tokens"], 128)
                    else:
                        self.assertEqual(kwargs["max_output_tokens" if provider_type is OpenAIProvider else "max_tokens"], 128)
        finally:
            generation_deadline.reset(deadline_token)
            auxiliary_budget.reset(token)

    def test_gemini_never_rounds_remaining_budget_up_to_server_minimum(self):
        token = generation_deadline.set(109.0)
        try:
            with self.transport(GeminiProvider) as (provider, method), self.assertRaises(ProviderError) as caught:
                provider.generate_with_metadata(**self.arguments)
            self.assertEqual(caught.exception.kind, ProviderErrorKind.TIMEOUT)
            method.assert_not_called()
        finally:
            generation_deadline.reset(token)

    def test_openai_and_grok_typed_timeout_is_not_a_connection_error(self):
        error = APITimeoutError(request=httpx.Request("POST", "https://example.invalid"))
        for provider_type in (OpenAIProvider, GrokProvider):
            with self.subTest(provider=provider_type.__name__), self.transport(provider_type) as (provider, method):
                method.side_effect = error
                with self.assertRaises(ProviderError) as caught:
                    provider.generate_with_metadata(**self.arguments)
                self.assertEqual((caught.exception.kind, caught.exception.status_code), (ProviderErrorKind.TIMEOUT, 504))

    def test_openai_gateway_timeout_mapping_does_not_expose_payload(self):
        response = httpx.Response(504, request=httpx.Request("POST", "https://example.invalid"))
        with self.transport(OpenAIProvider) as (provider, method):
            method.side_effect = InternalServerError("private-provider-payload", response=response, body=None)
            with self.assertRaises(ProviderError) as caught:
                provider.generate_with_metadata(**self.arguments)
            self.assertEqual(caught.exception.kind, ProviderErrorKind.TIMEOUT)
            self.assertNotIn("private-provider-payload", str(caught.exception))

    def test_claude_empty_typed_timeout_maps_correctly(self):
        with self.transport(ClaudeProvider) as (provider, method):
            method.side_effect = httpx.ReadTimeout("")
            with self.assertRaises(ProviderError) as caught:
                provider.generate_with_metadata(**self.arguments)
            self.assertEqual((caught.exception.kind, caught.exception.status_code), (ProviderErrorKind.TIMEOUT, 504))

    def test_sdk_timeout_options_preserve_single_gemini_transport_attempt(self):
        requests = []
        def transport(request):
            requests.append(request)
            return httpx.Response(503, json={"error": {"code": 503, "status": "UNAVAILABLE",
                                                      "message": "synthetic outage"}})
        http_client = httpx.Client(transport=httpx.MockTransport(transport))
        client = genai.Client(api_key="fake-key", http_options=types.HttpOptions(
            httpx_client=http_client, timeout=20000, retry_options=types.HttpRetryOptions(attempts=1)))
        provider = GeminiProvider()
        provider._client = Mock(return_value=client)
        token = generation_deadline.set(112.0)
        try:
            with self.assertRaises(ProviderError) as caught:
                provider.generate_with_metadata(**self.arguments)
            self.assertEqual(caught.exception.kind, ProviderErrorKind.TEMPORARY)
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0].headers["X-Server-Timeout"], "12")
            self.assertTrue(all(value == 12.0 for value in requests[0].extensions["timeout"].values()))
        finally:
            generation_deadline.reset(token)
            client.close()
            http_client.close()

    def test_openai_partial_stream_timeout_does_not_restart(self):
        provider = OpenAIProvider()
        client = Mock()
        provider._client = Mock(return_value=client)
        def events():
            yield SimpleNamespace(type="response.output_text.delta", delta="first part")
            raise APITimeoutError(request=httpx.Request("POST", "https://example.invalid"))
        client.responses.stream.return_value = nullcontext(events())
        stream = provider.generate_stream(**self.arguments)
        self.assertEqual(next(stream), "first part")
        with self.assertRaises(ProviderError) as caught:
            next(stream)
        self.assertEqual(caught.exception.kind, ProviderErrorKind.TIMEOUT)
        client.responses.stream.assert_called_once()


if __name__ == "__main__":
    unittest.main()
