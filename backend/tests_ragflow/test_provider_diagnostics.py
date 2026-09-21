"""Actual installed SDK with an in-memory transport; zero network/provider calls."""
import asyncio
import importlib.util
import json
from pathlib import Path

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
        assert request.url.path == "/v1beta/models/gemini-3.5-flash-lite:generateContent"
        body = json.loads(request.content)
        assert body["contents"][0]["role"] == "user"
        assert body["contents"][0]["parts"][0]["text"] == "Return the single word OK."
        assert body["generationConfig"] == {"maxOutputTokens": 16}
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


@pytest.mark.parametrize("visible,generation_supported,smoke_ok,expected_calls", [
    (False, True, True, 0),
    (True, False, True, 0),
    (True, True, False, 1),
    (True, True, True, 2),
])
def test_model35_job_metadata_gate_and_two_call_ceiling(monkeypatch, capsys, visible, generation_supported, smoke_ok, expected_calls):
    generated, metadata = [], []
    def handler(request):
        if request.method == "GET":
            assert request.url.path == "/v1beta/models"
            metadata.append(request.url.path)
            return httpx.Response(200, json={"models": [{
                "name": "models/gemini-3.5-flash-lite" if visible else "models/unrelated-model",
                "supportedGenerationMethods": ["generateContent"] if generation_supported else ["embedContent"]}]})
        generated.append(json.loads(request.content))
        if not smoke_ok:
            return httpx.Response(404, json={"error": {"code": 404, "status": "NOT_FOUND"}})
        answer = "OK" if len(generated) == 1 else "opening hours, membership options, community facilities"
        return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [{"text": answer}]}}],
            "usageMetadata": {"totalTokenCount": 9}})
    model = sdk_model(monkeypatch, handler)
    spec = importlib.util.spec_from_file_location("bounded_provider_job", Path(__file__).parents[2] / "dev/ragflow/provider_diagnostic.py")
    job = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(job)
    monkeypatch.setattr(job, "from_env", lambda project: model)
    monkeypatch.setenv("RAILWAY_PROJECT_ID", PROJECT)
    monkeypatch.setenv("RAGFLOW_DEV_PROJECT_ID", PROJECT)
    monkeypatch.setenv("RAGFLOW_DEV_PROVIDER_DIAGNOSTIC", "MODEL35_ONCE")
    success = asyncio.run(job.run("model35"))
    assert success is (visible and generation_supported and smoke_ok)
    assert len(metadata) == 1 and len(generated) == expected_calls
    if expected_calls == 2:
        from ragflow_derived.upstream.prompts.generator import PROMPT_JINJA_ENV, KEYWORD_PROMPT_TEMPLATE
        expected_prompt = PROMPT_JINJA_ENV.from_string(KEYWORD_PROMPT_TEMPLATE).render(
            content="Compare opening hours and membership options for two community facilities.", topn=3)
        assert generated[1]["systemInstruction"]["parts"][0]["text"] == expected_prompt
    output = capsys.readouterr().out
    assert "offline-placeholder-not-a-real-key" not in output


@pytest.mark.parametrize("success", [False, True])
def test_minimal_job_exact_content_only_one_attempt(monkeypatch, capsys, success):
    requests = []
    def handler(request):
        requests.append(request)
        assert request.url.path == "/v1beta/models/gemini-3.5-flash-lite:generateContent"
        assert json.loads(request.content) == {"contents": [{"role": "user", "parts": [
            {"text": "Return the single word OK."}]}]}
        if not success:
            return httpx.Response(400, json={"error": {"code": 400, "status": "INVALID_ARGUMENT",
                "message": "do-not-export-response-text"}})
        return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [{"text": "OK"}]}}],
            "usageMetadata": {"totalTokenCount": 9}})
    model = sdk_model(monkeypatch, handler)
    spec = importlib.util.spec_from_file_location("minimal_provider_job", Path(__file__).parents[2] / "dev/ragflow/provider_diagnostic.py")
    job = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(job)
    monkeypatch.setattr(job, "from_env", lambda project: model)
    monkeypatch.setenv("RAILWAY_PROJECT_ID", PROJECT)
    monkeypatch.setenv("RAGFLOW_DEV_PROJECT_ID", PROJECT)
    monkeypatch.setenv("RAGFLOW_DEV_PROVIDER_DIAGNOSTIC", "MINIMAL35_ONCE")
    assert asyncio.run(job.run("minimal35")) is success
    assert len(requests) == 1
    output = capsys.readouterr().out
    assert "do-not-export-response-text" not in output
    assert "offline-placeholder-not-a-real-key" not in output
