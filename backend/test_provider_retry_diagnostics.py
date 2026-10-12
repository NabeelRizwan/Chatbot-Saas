"""Retry diagnostics preserve real waiting and never change answer delivery."""
from contextlib import contextmanager, nullcontext
import json
from unittest.mock import Mock

import pytest

from services import llm_client
from services.providers.base_provider import ProviderError, ProviderErrorKind, ProviderFeedback


@pytest.fixture
def clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(llm_client.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(llm_client.time, "sleep", lambda delay: now.__setitem__(0, now[0] + delay))
    monkeypatch.setattr(llm_client.random, "uniform", lambda *args: 0.2)
    monkeypatch.setattr(llm_client, "LLM_TIMEOUT", 30)
    monkeypatch.setattr(llm_client, "LLM_BACKOFF_MAX", 10)
    monkeypatch.setattr(llm_client, "LLM_BACKOFF_BASE", 1)
    breaker = Mock()
    breaker.is_allowed.return_value = True
    monkeypatch.setattr(llm_client, "global_circuit_breaker", breaker)
    return now


def invoke(generate, events, **kwargs):
    return llm_client.execute_with_resilience(generate, "gemini", "configured-model",
        skip_legacy_guard=True, on_event=events.append, **kwargs)


def test_success_separates_admission_from_provider_time(clock):
    events = []
    @contextmanager
    def admission():
        clock[0] += 4
        yield
    def generate():
        clock[0] += 2
        return "Answer"
    assert invoke(generate, events, attempt_admission=admission) == "Answer"
    assert events == [{"event": "attempt_finished", "attempt": 1, "outcome": "success",
        "provider_started": True, "error_code": None, "status_code": None, "error_kind": None,
        "quota_category": None, "request_id": None,
        "retry_after_seconds": 0, "provider_call_ms": 2000.0, "admission_wait_ms": 4000.0}]


def test_successful_retry_keeps_original_error_and_actual_cooldown(clock):
    events = []
    attempts = [0]
    def generate():
        attempts[0] += 1
        clock[0] += 1
        if attempts[0] == 1:
            raise ProviderError("sensitive provider response", status_code=429,
                kind=ProviderErrorKind.RATE_LIMIT, retry_after_seconds=58)
        return "Answer"
    assert invoke(generate, events, attempt_admission=nullcontext,
        remaining_budget=lambda: 180 - clock[0]) == "Answer"
    assert [event["event"] for event in events] == ["attempt_finished", "retry_wait_finished", "attempt_finished"]
    assert events[0]["error_kind"] == "rate_limit"
    assert events[0]["error_code"] == "LLM_RATE_LIMITED"
    assert events[0]["status_code"] == 429
    assert events[0]["retry_after_seconds"] == 58
    assert events[1]["requested_wait_ms"] == 58000
    assert events[1]["actual_wait_ms"] == pytest.approx(58000)
    assert events[1]["outcome"] == "completed"
    assert events[-1]["outcome"] == "success"
    assert events[-1]["attempt"] == 2
    assert "sensitive" not in json.dumps(events)


def test_terminal_provider_failure_is_recorded_without_raw_exception(clock):
    events = []
    generate = Mock(side_effect=ProviderError("Authorization: secret", status_code=401,
        kind=ProviderErrorKind.AUTHENTICATION))
    with pytest.raises(llm_client.CentralizedLLMError):
        invoke(generate, events)
    generate.assert_called_once()
    assert len(events) == 1
    assert events[0]["provider_started"] is True
    assert events[0]["error_kind"] == "authentication"
    assert "secret" not in json.dumps(events)


def test_normalized_provider_feedback_is_preserved(clock):
    events = []
    generate = Mock(side_effect=ProviderError("Rate limited", status_code=429,
        kind=ProviderErrorKind.RATE_LIMIT,
        feedback=ProviderFeedback(quota_category="input_token_rate_limit", request_id="req_123-abc")))
    with pytest.raises(llm_client.CentralizedLLMError):
        invoke(generate, events, max_retries=0)
    assert events[0]["quota_category"] == "input_token_rate_limit"
    assert events[0]["request_id"] == "req_123-abc"


@pytest.mark.parametrize("identifier", ["sk-do-not-record", "Bearer_secret", "not\na\nrequest", "x" * 129])
def test_invalid_feedback_strings_do_not_enter_diagnostics(clock, identifier):
    events = []
    generate = Mock(side_effect=ProviderError("Rate limited", status_code=429,
        kind=ProviderErrorKind.RATE_LIMIT,
        feedback=ProviderFeedback(quota_category="secret-quota-payload", request_id=identifier)))
    with pytest.raises(llm_client.CentralizedLLMError):
        invoke(generate, events, max_retries=0)
    assert events[0]["quota_category"] is None
    assert events[0]["request_id"] is None


def test_admission_failure_is_not_reported_as_provider_execution(clock):
    events = []
    @contextmanager
    def admission():
        clock[0] += 3
        raise ProviderError("Admission ended", status_code=499, kind=ProviderErrorKind.INVALID_REQUEST)
        yield
    generate = Mock(return_value="not called")
    with pytest.raises(llm_client.CentralizedLLMError):
        invoke(generate, events, attempt_admission=admission)
    generate.assert_not_called()
    assert events[0]["provider_started"] is False
    assert events[0]["provider_call_ms"] == 0
    assert events[0]["admission_wait_ms"] == 3000


def test_cancellation_during_cooldown_records_partial_wait(clock):
    events = []
    generate = Mock(side_effect=ProviderError("Rate limited", status_code=429,
        kind=ProviderErrorKind.RATE_LIMIT, retry_after_seconds=58))
    def remaining():
        if clock[0] >= 0.2:
            raise RuntimeError("cancelled")
        return 180 - clock[0]
    with pytest.raises(RuntimeError, match="cancelled"):
        invoke(generate, events, attempt_admission=nullcontext, remaining_budget=remaining)
    generate.assert_called_once()
    assert len(events) == 2
    assert events[-1]["outcome"] == "interrupted"
    assert events[-1]["requested_wait_ms"] == 58000
    assert events[-1]["actual_wait_ms"] == pytest.approx(200)


def test_deadline_during_cooldown_records_oversleep(clock, monkeypatch):
    events = []
    generate = Mock(side_effect=ProviderError("Rate limited", status_code=429,
        kind=ProviderErrorKind.RATE_LIMIT, retry_after_seconds=58))
    monkeypatch.setattr(llm_client.time, "sleep", lambda delay: clock.__setitem__(0, 190))
    with pytest.raises(llm_client.CentralizedLLMError):
        invoke(generate, events, attempt_admission=nullcontext, remaining_budget=lambda: 180 - clock[0])
    generate.assert_called_once()
    assert events[-1]["outcome"] == "interrupted"
    assert events[-1]["actual_wait_ms"] == 190000


def test_fractional_retry_hint_is_reported_exactly_but_wait_rounds_up(clock):
    events = []
    generate = Mock(side_effect=[ProviderError("Rate limited", status_code=429,
        kind=ProviderErrorKind.RATE_LIMIT, retry_after_seconds=2.1), "Answer"])
    assert invoke(generate, events) == "Answer"
    assert events[0]["retry_after_seconds"] == 2.1
    assert events[1]["requested_wait_ms"] == 3000
    assert events[1]["actual_wait_ms"] == 3000


@pytest.mark.parametrize("delay", [float("nan"), float("inf"), -2.0])
def test_nonfinite_retry_hints_are_absent_from_json(clock, delay):
    events = []
    generate = Mock(side_effect=ProviderError("Rate limited", status_code=429,
        kind=ProviderErrorKind.RATE_LIMIT, retry_after_seconds=delay))
    with pytest.raises(llm_client.CentralizedLLMError):
        invoke(generate, events, max_retries=0)
    assert events[0]["retry_after_seconds"] == 0
    json.dumps(events, allow_nan=False)


def test_broken_callback_cannot_retry_delivered_answer(clock):
    generate = Mock(return_value="Answer")
    callback = Mock(side_effect=RuntimeError("diagnostic sink unavailable"))
    assert llm_client.execute_with_resilience(generate, "gemini", "model",
        skip_legacy_guard=True, on_event=callback) == "Answer"
    callback.assert_called_once()
    generate.assert_called_once()


def test_partial_stream_failure_does_not_duplicate_attempt_or_wait(clock):
    events = []
    fallback = Mock(return_value="Other answer")
    generate = Mock(side_effect=ProviderError("Rate limited", status_code=429,
        kind=ProviderErrorKind.RATE_LIMIT, retry_after_seconds=2))
    with pytest.raises(llm_client.CentralizedLLMError):
        invoke(generate, events, can_retry=lambda: False, fallback_fn=fallback)
    generate.assert_called_once()
    fallback.assert_not_called()
    assert len(events) == 1


def test_circuit_rejection_records_no_attempt(clock, monkeypatch):
    events = []
    monkeypatch.setattr(llm_client.global_circuit_breaker, "is_allowed", lambda *args: False)
    generate = Mock(return_value="not called")
    with pytest.raises(llm_client.CentralizedLLMError):
        invoke(generate, events)
    generate.assert_not_called()
    assert events[0]["attempt"] == 0
    assert events[0]["provider_started"] is False
    assert events[0]["error_code"] == "LLM_CIRCUIT_OPEN"


def test_emission_is_bounded_without_affecting_retry_count(clock, monkeypatch):
    events = []
    monkeypatch.setattr(llm_client.random, "uniform", lambda *args: 0)
    monkeypatch.setattr(llm_client, "LLM_BACKOFF_MAX", 0)
    generate = Mock(side_effect=ProviderError("Rate limited", status_code=429,
        kind=ProviderErrorKind.RATE_LIMIT))
    with pytest.raises(llm_client.CentralizedLLMError):
        invoke(generate, events, max_retries=70)
    assert generate.call_count == 71
    assert len(events) == 64
