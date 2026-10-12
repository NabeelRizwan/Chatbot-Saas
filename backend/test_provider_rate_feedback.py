"""Offline protocol tests: real SDK transports, no credentials or paid requests."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import asdict
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from google.genai import errors
import pytest

from services.providers.base_provider import GenerationResult, GenerationStreamEvent, ProviderError, ProviderErrorKind
from services.providers.claude_provider import ClaudeProvider
from services.providers.gemini_provider import GeminiProvider
from services.providers.grok_provider import GrokProvider
from services.providers.openai_provider import OpenAIProvider, _sampling_options
from services.providers.rate_feedback import capture_generation_feedback, capture_response, feedback_from_headers, gemini_error_feedback


NOW = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
ARGUMENTS = dict(api_key="local-fake-key", model_name="configured-model", prompt="question",
                 system_instruction="instruction", temperature=0.37)


def test_openai_headers_preserve_all_budget_dimensions_and_project_scope():
    feedback = feedback_from_headers("openai", {
        "X-RateLimit-Limit-Requests": "10", "x-ratelimit-remaining-requests": "0",
        "x-ratelimit-reset-requests": "1m2.5s", "x-ratelimit-limit-tokens": "50000",
        "x-ratelimit-remaining-tokens": "40000", "x-ratelimit-reset-tokens": "250ms",
        "x-ratelimit-limit-project-tokens": "20000", "x-ratelimit-remaining-project-tokens": "1234",
        "x-ratelimit-reset-project-tokens": "3s", "x-request-id": "req_example",
        "authorization": "secret", "x-api-key": "secret", "unrelated": "private-body",
    }, now=NOW)
    assert feedback.request_id == "req_example"
    assert feedback.observed_at_unix == NOW.timestamp()
    assert [(item.dimension, item.scope, item.limit, item.window_seconds) for item in feedback.rate_limits] == [
        ("requests", "model", 10, 60.0), ("total_tokens", "model", 50000, 60.0),
        ("total_tokens", "project", 20000, 60.0)]
    assert feedback.rate_limits[0].remaining == 0
    assert feedback.rate_limits[0].reset_after_seconds == 62.5
    assert feedback.rate_limits[1].reset_after_seconds == 0.25
    assert "secret" not in json.dumps(asdict(feedback))
    assert "private-body" not in json.dumps(asdict(feedback))


def test_claude_separate_input_and_output_budgets_and_rfc3339_resets():
    feedback = feedback_from_headers("claude", {
        "anthropic-ratelimit-requests-limit": "100", "anthropic-ratelimit-requests-remaining": "8",
        "anthropic-ratelimit-requests-reset": "2026-10-10T12:00:02Z",
        "anthropic-ratelimit-input-tokens-limit": "20000",
        "anthropic-ratelimit-input-tokens-remaining": "1000",
        "anthropic-ratelimit-input-tokens-reset": "2026-10-10T12:00:04.5Z",
        "anthropic-ratelimit-output-tokens-limit": "3000",
        "anthropic-ratelimit-output-tokens-remaining": "0",
        "anthropic-ratelimit-output-tokens-reset": "2026-10-10T12:00:03Z",
        "request-id": "req_claude",
    }, now=NOW)
    assert [item.dimension for item in feedback.rate_limits] == ["requests", "input_tokens", "output_tokens"]
    assert [item.reset_after_seconds for item in feedback.rate_limits] == [2.0, 4.5, 3.0]
    assert all(item.window_seconds == 60.0 for item in feedback.rate_limits)


@pytest.mark.parametrize("value", ["NaN", "inf", "-1", "1e10", "9" * 100, True, {}, None])
def test_invalid_limits_are_not_inferred(value):
    assert feedback_from_headers("openai", {"x-ratelimit-limit-tokens": value,
                                            "x-ratelimit-reset-tokens": value}, now=NOW) is None


def test_absent_feedback_and_unknown_provider_headers_do_not_invent_allowances():
    assert feedback_from_headers("openai", {}) is None
    assert feedback_from_headers("gemini", {"x-ratelimit-limit-tokens": "10000"}) is None
    assert feedback_from_headers("unknown", {"x-ratelimit-limit-tokens": "10000"}) is None
    assert feedback_from_headers("grok", {"x-ratelimit-limit-requests": "50"}).rate_limits[0].window_seconds is None


def test_retry_headers_support_http_date_and_milliseconds():
    feedback = feedback_from_headers("openai", {"retry-after": "Sat, 10 Oct 2026 12:00:12 GMT",
                                                 "retry-after-ms": "12500"}, now=NOW)
    assert feedback.retry_after_seconds == 12.5
    assert feedback_from_headers("claude", {"retry-after": "0"}, now=NOW).retry_after_seconds == 0
    assert feedback_from_headers("openai", {"retry-after": "secret"}) is None


@pytest.mark.parametrize("value", ["sk-secret", "xai-secret", "AIzaSecret", "BearerSecret", "req_\nsecret", "a" * 129])
def test_request_ids_reject_obvious_credentials_and_unbounded_values(value):
    assert feedback_from_headers("openai", {"x-request-id": value}) is None


def test_gemini_feedback_uses_only_structured_allowlisted_fields():
    feedback = gemini_error_feedback([
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
            {"quotaId": "GenerateRequestsPerMinutePerProjectPerModel", "quotaValue": "10", "description": "secret"},
            {"quotaId": "GenerateContentInputTokensPerModelPerMinute", "quotaValue": "20000"},
            {"quotaId": "GenerateRequestsPerDayPerProjectPerModel", "quotaValue": "500"},
            {"quotaId": "unknown", "quotaValue": "1000"}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "58.25s"},
    ], headers={"retry-after": "57", "x-api-key": "secret"})
    assert feedback.quota_category == "daily_quota"
    assert feedback.retry_after_seconds == 58.25
    assert [(item.dimension, item.limit, item.window_seconds, item.scope) for item in feedback.rate_limits] == [
        ("requests", 10, 60.0, "model"), ("input_tokens", 20000, 60.0, "model"),
        ("requests", 500, 86400.0, "model")]
    assert all(item.remaining is None and item.reset_after_seconds is None for item in feedback.rate_limits)
    assert "secret" not in json.dumps(asdict(feedback))


def test_gemini_unknown_window_is_not_converted_to_per_minute():
    assert gemini_error_feedback([{"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
        {"quotaId": "GenerateRequests", "quotaValue": "20"}]}]).rate_limits == ()


def test_gemini_model_dimension_preserves_scope_and_project_limit_stays_separate():
    feedback = gemini_error_feedback([{"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
        {"quotaId": "GenerateRequestsPerMinutePerProject", "quotaValue": "20", "quotaDimensions": {"model": "selected"}},
        {"quotaId": "GenerateRequestsPerMinutePerProject", "quotaValue": "200"}]}])
    assert [limit.scope for limit in feedback.rate_limits] == ["model", "project"]


def test_gemini_provider_preserves_failure_feedback_and_rounded_retry_delay():
    provider = GeminiProvider()
    client = Mock()
    client.models.generate_content.side_effect = errors.ClientError(429, {"error": {"message": "private secret",
        "details": [
            {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
                {"quotaId": "GenerateRequestsPerMinutePerProjectPerModel", "quotaValue": "10"}]},
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "1.5s"}]}})
    provider._client = Mock(return_value=client)
    with pytest.raises(ProviderError) as caught:
        provider.generate_with_metadata(**ARGUMENTS)
    assert caught.value.kind == ProviderErrorKind.RATE_LIMIT
    assert caught.value.retry_after_seconds == 2
    assert caught.value.feedback.quota_category == "request_rate_limit"
    assert caught.value.feedback.rate_limits[0].limit == 10
    assert "private secret" not in json.dumps(asdict(caught.value.feedback))


def _openai_body(text="answer"):
    return {"id": "resp_example", "object": "response", "created_at": 1, "status": "completed",
            "model": "configured-model", "output": [{"id": "msg_example", "type": "message",
                "status": "completed", "role": "assistant", "content": [
                    {"type": "output_text", "text": text, "annotations": []}]}],
            "usage": {"input_tokens": 12, "output_tokens": 4, "total_tokens": 16}}


def _grok_body():
    return {"id": "chatcmpl_example", "object": "chat.completion", "created": 1, "model": "configured-model",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "answer"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16}}


@pytest.mark.parametrize("provider_type,module,body", [(OpenAIProvider, "openai_provider", _openai_body),
                                                        (GrokProvider, "grok_provider", _grok_body)])
def test_real_sdk_captures_success_headers_without_an_additional_request(provider_type, module, body):
    calls = []
    def transport(request):
        calls.append(request)
        return httpx.Response(200, json=body(), headers={"x-ratelimit-limit-requests": "50", "x-request-id": "req_buffered"})
    provider = provider_type()
    provider._clients = {}
    client_factory = lambda **kwargs: httpx.Client(transport=httpx.MockTransport(transport), **kwargs)
    with patch(f"services.providers.{module}.DefaultHttpxClient", side_effect=client_factory):
        try:
            result = provider.generate_with_metadata(**ARGUMENTS)
        finally:
            for client in provider._clients.values():
                client.close()
    assert result.text == "answer"
    assert result.usage.total_tokens == 16
    assert result.feedback.rate_limits[0].limit == 50
    assert result.feedback.request_id == "req_buffered"
    assert len(calls) == 1
    payload = json.loads(calls[0].content)
    assert payload["model"] == "configured-model" and payload["temperature"] == 0.37
    assert "max_output_tokens" not in payload and "max_tokens" not in payload


@pytest.mark.parametrize("provider_type,module", [(OpenAIProvider, "openai_provider"), (GrokProvider, "grok_provider")])
@pytest.mark.parametrize("code,kind", [("rate_limit_exceeded", ProviderErrorKind.RATE_LIMIT),
                                      ("insufficient_quota", ProviderErrorKind.QUOTA_EXHAUSTED),
                                      ("billing_hard_limit_reached", ProviderErrorKind.BILLING_RESTRICTION)])
def test_real_sdk_failure_preserves_retry_and_quota_type_without_secrets(provider_type, module, code, kind):
    calls = []
    def transport(request):
        calls.append(request)
        return httpx.Response(429, headers={"retry-after": "58", "x-request-id": "req_limited"},
                              json={"error": {"code": code, "message": "private raw body"}})
    provider = provider_type()
    provider._clients = {}
    client_factory = lambda **kwargs: httpx.Client(transport=httpx.MockTransport(transport), **kwargs)
    with patch(f"services.providers.{module}.DefaultHttpxClient", side_effect=client_factory):
        try:
            with pytest.raises(ProviderError) as caught:
                provider.generate_with_metadata(**ARGUMENTS)
        finally:
            for client in provider._clients.values():
                client.close()
    error = caught.value
    assert error.kind == kind
    assert error.retry_after_seconds == 58
    assert error.feedback.request_id == "req_limited"
    assert len(calls) == 1
    assert "private raw body" not in str(error) + json.dumps(asdict(error.feedback))


@pytest.mark.parametrize("model", ["configured-model", "gpt-6.1-sol"])
def test_real_openai_sdk_stream_retains_headers_and_final_usage(model):
    provider = OpenAIProvider()
    provider._clients = {}
    calls = []
    def transport(request):
        calls.append(request)
        events = [{"type": "response.created", "response": dict(_openai_body(""), status="in_progress"), "sequence_number": 0},
                  {"type": "response.output_text.delta", "delta": "answer", "item_id": "msg_example",
                   "output_index": 0, "content_index": 0, "sequence_number": 1},
                  {"type": "response.completed", "response": _openai_body(), "sequence_number": 2}]
        content = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
        return httpx.Response(200, text=content, headers={"content-type": "text/event-stream",
            "x-ratelimit-limit-tokens": "50000", "x-ratelimit-remaining-tokens": "40000", "x-request-id": "req_stream"})
    client_factory = lambda **kwargs: httpx.Client(transport=httpx.MockTransport(transport), **kwargs)
    with patch("services.providers.openai_provider.DefaultHttpxClient", side_effect=client_factory):
        try:
            events = list(provider.generate_stream_with_metadata(**dict(ARGUMENTS, model_name=model)))
        finally:
            for client in provider._clients.values():
                client.close()
    assert "".join(event.delta for event in events) == "answer"
    assert events[-1].result.text == "answer"
    assert events[-1].result.usage.total_tokens == 16
    assert events[-1].result.feedback.request_id == "req_stream"
    assert events[-1].result.feedback.rate_limits[0].remaining == 40000
    assert len(calls) == 1
    payload = json.loads(calls[0].content)
    assert payload["model"] == model
    assert "reasoning" not in payload
    assert ("temperature" in payload) == (model != "gpt-6.1-sol")


def test_claude_buffered_feedback_success_failure_and_missing_headers_do_not_leak():
    provider = ClaudeProvider()
    client = Mock()
    client.post.side_effect = [
        httpx.Response(200, json={"content": [{"text": "answer"}], "usage": {"input_tokens": 3, "output_tokens": 2}},
                       headers={"anthropic-ratelimit-input-tokens-limit": "20000", "request-id": "req_first"}),
        httpx.Response(429, json={"error": {"message": "secret"}}, headers={"retry-after": "12"}),
        httpx.Response(200, json={"content": [{"text": "answer"}], "usage": {}})]
    with patch("services.providers.claude_provider.httpx.Client", return_value=nullcontext(client)):
        assert provider.generate_with_metadata(**ARGUMENTS).feedback.request_id == "req_first"
        with pytest.raises(ProviderError) as caught:
            provider.generate_with_metadata(**ARGUMENTS)
        assert caught.value.retry_after_seconds == 12
        assert caught.value.feedback.request_id is None
        assert provider.generate_with_metadata(**ARGUMENTS).feedback is None
    assert provider.default_output_token_limit == 1024
    assert client.post.call_args.kwargs["json"]["max_tokens"] == 1024


def test_feedback_is_isolated_between_concurrent_bot_calls():
    provider = OpenAIProvider()
    provider._clients = {}
    def transport(request):
        text = json.loads(request.content)["input"][-1]["content"]
        return httpx.Response(200, json=_openai_body(text), headers={"x-request-id": f"req_{text}"})
    client_factory = lambda **kwargs: httpx.Client(transport=httpx.MockTransport(transport), **kwargs)
    with patch("services.providers.openai_provider.DefaultHttpxClient", side_effect=client_factory):
        provider._client(ARGUMENTS["api_key"])
        try:
            with ThreadPoolExecutor(max_workers=10) as pool:
                results = list(pool.map(lambda i: provider.generate_with_metadata(**dict(ARGUMENTS, prompt=str(i))), range(10)))
        finally:
            for client in provider._clients.values():
                client.close()
    assert [(result.text, result.feedback.request_id) for result in results] == [(str(i), f"req_{i}") for i in range(10)]


def test_interleaved_streams_do_not_share_feedback_or_keep_context_after_yield():
    closed = []
    class Provider:
        provider_name = "openai"

        @capture_generation_feedback(streaming=True)
        def stream(self, identifier):
            try:
                capture_response("openai", httpx.Response(200, headers={"x-request-id": identifier}))
                yield GenerationStreamEvent(delta=identifier)
                yield GenerationStreamEvent(result=GenerationResult(text=identifier, provider="openai", model="selected"))
            finally:
                closed.append(identifier)

    provider = Provider()
    first, second = provider.stream("req_first"), provider.stream("req_second")
    assert next(first).delta == "req_first"
    assert next(second).delta == "req_second"
    assert next(first).result.feedback.request_id == "req_first"
    assert next(second).result.feedback.request_id == "req_second"
    first.close()
    second.close()
    assert closed == ["req_first", "req_second"]


def test_gemini_usage_includes_thinking_without_changing_answer_settings():
    provider = GeminiProvider()
    client = Mock()
    provider._client = Mock(return_value=client)
    client.models.generate_content.return_value = SimpleNamespace(text="answer", candidates=[],
        usage_metadata=SimpleNamespace(prompt_token_count=12, candidates_token_count=4, thoughts_token_count=7))
    result = provider.generate_with_metadata(**ARGUMENTS)
    assert result.usage.input_tokens == 12 and result.usage.output_tokens == 11
    assert result.text == "answer"
    assert client.models.generate_content.call_args.kwargs["config"].thinking_config is None


@pytest.mark.parametrize("model,expected", [("configured-model", 30), ("claude-3-5-haiku-20241022", 5030)])
def test_claude_usage_counts_cache_writes_and_only_nonexempt_cache_reads(model, expected):
    provider = ClaudeProvider()
    client = Mock()
    client.post.return_value = httpx.Response(200, json={"content": [{"text": "answer"}], "usage": {
        "input_tokens": 10, "cache_creation_input_tokens": 20, "cache_read_input_tokens": 5000, "output_tokens": 3}})
    with patch("services.providers.claude_provider.httpx.Client", return_value=nullcontext(client)):
        result = provider.generate_with_metadata(**dict(ARGUMENTS, model_name=model))
    assert result.usage.input_tokens == expected and result.usage.output_tokens == 3


@pytest.mark.parametrize("model", ["gpt-6.1-sol", "gpt-6.1-sol-2026-09-29", "gpt-6-astra", "gpt-6-sol", "gpt-6-luna"])
def test_documented_default_reasoning_models_omit_sampling_without_changing_effort(model):
    assert _sampling_options(model, 0.37) == {}


@pytest.mark.parametrize("model", ["gpt-4.1", "gpt-4.1-mini", "configured-model", "gpt-6.1-sol-new-unknown-variant", "gpt-7"])
def test_sampling_capability_does_not_guess_future_or_other_model_families(model):
    assert _sampling_options(model, 0.37) == {"temperature": 0.37}


def test_sol_buffered_and_legacy_stream_use_same_sampling_contract():
    provider = OpenAIProvider()
    client = Mock()
    provider._client = Mock(return_value=client)
    client.responses.create.return_value = SimpleNamespace(output_text="answer", usage=None)
    client.responses.stream.return_value = nullcontext(iter([SimpleNamespace(type="response.output_text.delta", delta="answer")]))
    assert provider.generate_with_metadata(**dict(ARGUMENTS, model_name="gpt-6.1-sol")).text == "answer"
    assert list(provider.generate_stream(**dict(ARGUMENTS, model_name="gpt-6.1-sol"))) == ["answer"]
    for method in (client.responses.create, client.responses.stream):
        assert method.call_args.kwargs["model"] == "gpt-6.1-sol"
        assert "temperature" not in method.call_args.kwargs
        assert "reasoning" not in method.call_args.kwargs


def test_gemini_explicit_zero_allocation_is_not_retryable_minute_throttle():
    provider = GeminiProvider()
    client = Mock()
    provider._client = Mock(return_value=client)
    client.models.generate_content.side_effect = errors.ClientError(429, {"error": {"details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
            {"quotaId": "GenerateRequestsPerMinutePerProjectPerModel", "quotaValue": "0"}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "58s"}]}})
    with pytest.raises(ProviderError) as caught:
        provider.generate_with_metadata(**ARGUMENTS)
    assert caught.value.kind == ProviderErrorKind.QUOTA_EXHAUSTED
    assert caught.value.feedback.quota_category == "insufficient_quota"
    assert caught.value.feedback.rate_limits[0].limit == 0
