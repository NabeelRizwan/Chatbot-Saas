"""Development transport only: installed SDK, offline HTTP, no live requests."""
import asyncio
import copy
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from ragflow_dev.chat import PROJECT
from ragflow_derived.contracts import EngineError
from tests_ragflow.test_provider_diagnostics import sdk_model


def reply(text="OK"):
    return httpx.Response(200, json={"candidates": [{"content": {
        "role": "model", "parts": [{"text": text}]}}], "usageMetadata": {"totalTokenCount": 9}})


def test_config_defaults_and_exact_history_and_caller_bounds(monkeypatch):
    bodies = []
    def handler(request):
        bodies.append(json.loads(request.content))
        return reply()
    model = sdk_model(monkeypatch, handler)
    history = [{"role": "user", "content": "earlier question"},
        {"role": "assistant", "content": "earlier answer"}, {"role": "user", "content": "final question "}]
    conf = {"temperature": 0, "top_p": 0.9, "top_k": 20, "candidate_count": 2,
        "thinking_budget": 0, "thinking_level": "high", "max_tokens": 256,
        "stop_sequences": ["stop"], "response_mime_type": "application/json",
        "response_schema": {"type": "object"}, "tools": [{"name": "unused"}],
        "tool_config": {}, "safety_settings": []}
    original = copy.deepcopy((history, conf))
    assert asyncio.run(model.async_chat("unchanged upstream system prompt", history, conf)) == "OK"
    assert (history, conf) == original
    assert bodies[0] == {
        "systemInstruction": {"role": "user", "parts": [{"text": "unchanged upstream system prompt"}]},
        "contents": [{"role": "user", "parts": [{"text": "earlier question"}]},
            {"role": "model", "parts": [{"text": "earlier answer"}]},
            {"role": "user", "parts": [{"text": "final question "}]}],
        "generationConfig": {"maxOutputTokens": 256}}
    assert model.tokens == 9


@pytest.mark.parametrize("history", [[], [{"role": "user", "content": " "}],
    [{"role": "assistant", "content": "prefill"}], [{"role": "tool", "content": "x"}, {"role": "user", "content": "q"}]])
def test_invalid_or_empty_final_turn_never_reaches_network(monkeypatch, history):
    def handler(request):
        pytest.fail("invalid message must not reach transport")
    model = sdk_model(monkeypatch, handler)
    with pytest.raises(EngineError):
        asyncio.run(model.async_chat("system", history))
    assert model.failures == 1


@pytest.mark.parametrize("smoke_ok,helper_ok,expected_calls", [(False, True, 1), (True, False, 2), (True, True, 2)])
def test_adapter_job_conditional_real_upstream_helper_and_two_call_bound(monkeypatch, capsys, smoke_ok, helper_ok, expected_calls):
    bodies = []
    def handler(request):
        assert request.url.path == "/v1beta/models/gemini-3.5-flash-lite:generateContent"
        bodies.append(json.loads(request.content))
        if (len(bodies) == 1 and not smoke_ok) or (len(bodies) == 2 and not helper_ok):
            return httpx.Response(400, json={"error": {"code": 400, "status": "INVALID_ARGUMENT"}})
        return reply("OK" if len(bodies) == 1 else "opening hours, membership options, community facilities")
    model = sdk_model(monkeypatch, handler)
    spec = importlib.util.spec_from_file_location("compatible_provider_job", Path(__file__).parents[2] / "dev/ragflow/provider_diagnostic.py")
    job = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(job)
    monkeypatch.setattr(job, "from_env", lambda project: model)
    monkeypatch.setenv("RAILWAY_PROJECT_ID", PROJECT)
    monkeypatch.setenv("RAGFLOW_DEV_PROJECT_ID", PROJECT)
    monkeypatch.setenv("RAGFLOW_DEV_PROVIDER_DIAGNOSTIC", "ADAPTER35_ONCE")
    assert asyncio.run(job.run("adapter35")) is (smoke_ok and helper_ok)
    assert len(bodies) == expected_calls and model.calls == expected_calls
    assert bodies[0] == {"contents": [{"role": "user", "parts": [{"text": "Return the single word OK."}]}]}
    if len(bodies) == 2:
        from ragflow_derived.upstream.prompts.generator import PROMPT_JINJA_ENV, KEYWORD_PROMPT_TEMPLATE
        expected = PROMPT_JINJA_ENV.from_string(KEYWORD_PROMPT_TEMPLATE).render(
            content="Compare opening hours and membership options for two community facilities.", topn=3)
        # SDK emits an empty generationConfig with systemInstruction only.
        assert bodies[1] == {"contents": [{"role": "user", "parts": [{"text": "Output: "}]}],
            "systemInstruction": {"role": "user", "parts": [{"text": expected}]}, "generationConfig": {}}
    output = capsys.readouterr().out
    assert "offline-placeholder-not-a-real-key" not in output
    assert model.max_calls == 2
