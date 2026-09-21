"""Actual installed SDK with an in-memory transport; zero network/provider calls."""
import asyncio
import json

import httpx
import pytest
from google import genai
from google.genai import errors

from ragflow_dev.chat import from_env, PROJECT
from ragflow_dev.provider_diagnostics import safe_diagnostic
from ragflow_derived.contracts import EngineError


@pytest.mark.parametrize("code,status,reason,category,retryable", [
    (400, "INVALID_ARGUMENT", "API_KEY_INVALID", "AUTHENTICATION", False),
    (401, "UNAUTHENTICATED", None, "AUTHENTICATION", False),
    (403, "PERMISSION_DENIED", "SERVICE_DISABLED", "PERMISSION", False),
    (429, "RESOURCE_EXHAUSTED", None, "QUOTA", True),
    (404, "NOT_FOUND", None, "MODEL_NOT_FOUND", False),
    (400, "INVALID_ARGUMENT", None, "INVALID_REQUEST", False),
    (503, "UNAVAILABLE", None, "UNKNOWN", True),
])
def test_sdk_error_allowlist(code, status, reason, category, retryable):
    secret = "private-unrelated-value-not-to-serialize"
    exc = errors.ClientError(code, {"error": {"status": status, "message": secret,
        "details": [{"reason": reason, "metadata": {"credential": secret}}]}},
        response=httpx.Response(code, headers={"Authorization": secret}))
    result = safe_diagnostic(exc, "gemini-2.5-flash-lite", "request")
    assert result["category"] == category and result["retryable"] is retryable
    assert result["http_status"] == code and result["provider_code"] == status
    assert result["provider_reason"] == reason
    assert secret not in json.dumps(result)


def test_unknown_strings_and_exception_text_never_exported():
    secret = "do-not-print-secret"
    exc = errors.APIError(400, {"error": {"status": secret, "message": secret,
        "details": [{"reason": secret}]}})
    result = safe_diagnostic(exc, secret, secret)
    assert secret not in json.dumps(result)
    assert result["provider_code"] is None and result["provider_reason"] is None
    class UnsafeError(Exception):
        def __str__(self):
            raise AssertionError("must not stringify errors")
    assert safe_diagnostic(UnsafeError(), "offline", "request")["exception_class"] == "OTHER"


@pytest.mark.parametrize("exc,category", [
    (httpx.ReadTimeout("secret"), "TIMEOUT"),
    (httpx.ConnectError("secret"), "NETWORK"),
    (TypeError("secret"), "SDK"),
    (json.JSONDecodeError("secret", "secret", 0), "RESPONSE_PARSE"),
])
def test_non_api_categories(exc, category):
    assert safe_diagnostic(exc, "offline", "request")["category"] == category


def sdk_model(monkeypatch, handler):
    original = genai.Client
    monkeypatch.setenv("RAGFLOW_DEV_GEMINI_API_KEY", "offline-placeholder-not-a-real-key")
    def local_client(**kwargs):
        assert kwargs["vertexai"] is False
        options = kwargs["http_options"]
        assert options.timeout == 60000 and options.retry_options.attempts == 1
        options.httpx_async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return original(**kwargs)
    monkeypatch.setattr(genai, "Client", local_client)
    return from_env(PROJECT)


def test_actual_sdk_request_and_response_without_network(monkeypatch):
    requests = []
    def handler(request):
        requests.append(request)
        assert request.url.path == "/v1beta/models/gemini-2.5-flash-lite:generateContent"
        body = json.loads(request.content)
        assert body["contents"][0]["role"] == "user"
        assert body["contents"][0]["parts"][0]["text"] == "Return the single word OK."
        # Installed 1.55.0 serializes this nested typed object in snake_case.
        assert body["generationConfig"]["thinkingConfig"]["thinking_budget"] == 0
        return httpx.Response(200, json={"candidates": [{"content": {
            "role": "model", "parts": [{"text": "OK"}]}}], "usageMetadata": {"totalTokenCount": 7}})
    model = sdk_model(monkeypatch, handler)
    result = asyncio.run(model.async_chat("", [{"role": "user", "content": "Return the single word OK."}], {"max_tokens": 16}))
    assert result == "OK" and model.tokens == 7 and len(requests) == 1
    assert model.last_diagnostic is None


def test_actual_sdk_failure_no_retry_and_safe_log(monkeypatch, caplog):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(400, json={"error": {"code": 400, "status": "INVALID_ARGUMENT",
            "message": "private-header-like-secret", "details": [{"reason": "API_KEY_INVALID"}]}})
    model = sdk_model(monkeypatch, handler)
    with pytest.raises(EngineError):
        asyncio.run(model.async_chat("", [{"role": "user", "content": "OK"}]))
    assert len(requests) == 1 and model.failures == 1
    assert model.last_diagnostic["category"] == "AUTHENTICATION"
    assert model.last_diagnostic["phase"] == "request"
    assert "private-header-like-secret" not in caplog.text
    assert "offline-placeholder-not-a-real-key" not in caplog.text
