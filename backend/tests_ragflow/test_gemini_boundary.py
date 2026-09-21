"""Offline transport tests: no provider requests, no real keys."""
import asyncio
from types import SimpleNamespace
import pytest
from ragflow_dev.chat import DevGemini, from_env, PROJECT
from ragflow_derived.contracts import EngineError
from ragflow_derived.upstream.gemini import GeminiProvider


def test_upstream_gemini_config_and_roles():
    calls = []
    async def generate(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text="reply", usage_metadata=SimpleNamespace(total_token_count=23))
    p = GeminiProvider(SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate))), "test-model")
    model = DevGemini(p)
    conf = {"temperature": .2, "top_p": .9, "max_tokens": 512, "irrelevant": True}
    history = [{"role": "assistant", "content": "prior"}, {"role": "user", "content": "question"}]
    assert asyncio.run(model.async_chat("system", history, conf)) == "reply"
    assert calls[0]["config"].system_instruction == "system"
    assert calls[0]["config"].temperature == .2
    assert calls[0]["config"].max_output_tokens == 512
    assert calls[0]["config"].thinking_config.thinking_budget == 0
    assert [c.role for c in calls[0]["contents"]] == ["model", "user"]
    assert model.calls == 1 and model.tokens == 23
    assert "max_tokens" in conf and history[0]["role"] == "assistant"


def test_no_ordinary_provider_key_fallback(monkeypatch):
    monkeypatch.delenv("RAGFLOW_DEV_GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "not-authorized")
    monkeypatch.setenv("GOOGLE_API_KEY", "not-authorized")
    assert from_env(PROJECT) is None
    with pytest.raises(EngineError):
        from_env("other-project")


def test_budget_and_safe_error_are_fail_closed():
    class Broken:
        model_name = "offline"
        async def _async_chat(self, *args, **kwargs):
            raise RuntimeError("private credential detail")
    m = DevGemini(Broken(), max_calls=1)
    for stage in ("Gemini transport", "call budget"):
        with pytest.raises(EngineError) as exc:
            asyncio.run(m.async_chat("sys", [{"role": "user", "content": "q"}]))
        assert exc.value.stage == stage and "private" not in str(exc.value)
    assert m.calls == 1 and m.failures == 1


def test_factory_closes_each_loop_client():
    events = []
    class Provider:
        model_name = "offline"
        def __init__(self):
            async def close(): events.append("async-close")
            self.client = SimpleNamespace(aio=SimpleNamespace(aclose=close), close=lambda: events.append("close"))
        async def _async_chat(self, *args, **kwargs): return "ok", 1
    m = DevGemini(Provider(), provider_factory=Provider)
    for _ in range(2):
        assert asyncio.run(m.async_chat("sys", [])) == "ok"
    assert events == ["async-close", "close", "async-close", "close"]
