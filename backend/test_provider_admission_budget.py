from contextlib import contextmanager
from unittest.mock import Mock

import pytest

from services import llm_client
from services.providers.base_provider import generation_deadline


@pytest.fixture
def clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(llm_client.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(llm_client, "LLM_TIMEOUT", 10)
    breaker = Mock()
    breaker.is_allowed.return_value = True
    monkeypatch.setattr(llm_client, "global_circuit_breaker", breaker)
    return now


def test_admission_wait_does_not_spend_provider_generation_budget(clock):
    seen = []
    @contextmanager
    def admission():
        clock[0] += 20
        try:
            yield
        finally:
            seen.append("released")
    def generate():
        assert generation_deadline.get() - clock[0] == 10
        clock[0] += 2
        return "Answer"
    assert llm_client.execute_with_resilience(generate, "openai", "test",
        skip_legacy_guard=True, attempt_admission=admission,
        remaining_budget=lambda: 100-clock[0]) == "Answer"
    assert seen == ["released"]


def test_admission_does_not_extend_inherited_hard_deadline(clock):
    @contextmanager
    def admission():
        clock[0] += 20
        yield
    generate = Mock(return_value="Answer")
    token = generation_deadline.set(15)
    try:
        with pytest.raises(llm_client.CentralizedLLMError) as error:
            llm_client.execute_with_resilience(generate, "openai", "test", max_retries=0,
                skip_legacy_guard=True, attempt_admission=admission)
    finally:
        generation_deadline.reset(token)
    assert error.value.code == llm_client.LLMErrorCode.LLM_TIMEOUT
    generate.assert_not_called()


def test_whole_turn_remaining_clips_transport_budget(clock):
    @contextmanager
    def admission():
        clock[0] += 20
        yield
    def generate():
        assert generation_deadline.get() - clock[0] == 3
        return "Answer"
    assert llm_client.execute_with_resilience(generate, "openai", "test",
        skip_legacy_guard=True, attempt_admission=admission, remaining_budget=lambda: 3) == "Answer"


def test_visible_stream_never_retries_or_uses_fallback(clock):
    call, fallback = Mock(side_effect=TimeoutError("provider timeout")), Mock(return_value="Other answer")
    with pytest.raises(llm_client.CentralizedLLMError):
        llm_client.execute_with_resilience(call, "openai", "test", skip_legacy_guard=True,
            can_retry=lambda: False, fallback_fn=fallback)
    call.assert_called_once()
    fallback.assert_not_called()
