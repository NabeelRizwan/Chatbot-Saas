"""Regression for actual Gemini Retry-After33s under queued widget bursts."""
from contextlib import contextmanager
from unittest.mock import Mock

import pytest

from services import llm_client
from services.providers.base_provider import ProviderError, ProviderErrorKind, generation_deadline


@pytest.fixture
def runtime(monkeypatch):
    now = [0.0]
    held = [False]
    sleeps = []
    monkeypatch.setattr(llm_client.time, 'monotonic', lambda: now[0])
    def sleep(seconds):
        assert not held[0], 'Provider slot must be released before retry waiting'
        sleeps.append(seconds)
        now[0] += seconds
    monkeypatch.setattr(llm_client.time, 'sleep', sleep)
    monkeypatch.setattr(llm_client, 'LLM_TIMEOUT', 30)
    monkeypatch.setattr(llm_client.random, 'uniform', lambda *args: .2)
    breaker = Mock()
    breaker.is_allowed.return_value = True
    monkeypatch.setattr(llm_client, 'global_circuit_breaker', breaker)
    @contextmanager
    def admission():
        held[0] = True
        try:
            yield
        finally:
            held[0] = False
    return now, sleeps, admission, breaker


def rate_error(delay=33, kind=ProviderErrorKind.RATE_LIMIT):
    return ProviderError('Provider throttled.', status_code=429, kind=kind, retry_after_seconds=delay)


def test_real_33_second_cooldown_retries_with_unspent_generation_budget(runtime):
    now, sleeps, admission, breaker = runtime
    observations = []
    def generate():
        observations.append((now[0], generation_deadline.get() - now[0]))
        if len(observations) == 1:
            now[0] += 1
            raise rate_error()
        return 'Answer'
    assert llm_client.execute_with_resilience(generate, 'gemini', 'same-model',
        skip_legacy_guard=True, attempt_admission=admission,
        remaining_budget=lambda: 180 - now[0]) == 'Answer'
    assert observations[0] == (0, 30)
    assert observations[1][0] >= 34
    assert observations[1][1] == pytest.approx(29)
    assert sum(sleeps) == pytest.approx(33)
    breaker.record_failure.assert_not_called()


@pytest.mark.parametrize('remaining,inherited', [(40, None), (180, 40)])
def test_whole_turn_or_inherited_deadline_cannot_fit_cooldown(runtime, remaining, inherited):
    now, sleeps, admission, breaker = runtime
    generate = Mock(side_effect=rate_error())
    token = generation_deadline.set(inherited)
    try:
        with pytest.raises(llm_client.CentralizedLLMError):
            llm_client.execute_with_resilience(generate, 'gemini', 'model', skip_legacy_guard=True,
                attempt_admission=admission, remaining_budget=lambda: remaining - now[0])
    finally:
        generation_deadline.reset(token)
    generate.assert_called_once()
    assert not sleeps


def test_cancellation_during_retry_wait_prevents_next_provider_call(runtime):
    now, sleeps, admission, breaker = runtime
    generate = Mock(side_effect=rate_error())
    def remaining():
        if now[0] >= .2:
            raise RuntimeError('cancelled')
        return 180 - now[0]
    with pytest.raises(RuntimeError, match='cancelled'):
        llm_client.execute_with_resilience(generate, 'gemini', 'model', skip_legacy_guard=True,
            attempt_admission=admission, remaining_budget=remaining)
    generate.assert_called_once()
    assert now[0] < 1


def test_inherited_deadline_oversleep_stops_before_second_admission(runtime, monkeypatch):
    now, sleeps, admission, breaker = runtime
    admissions = Mock(side_effect=admission)
    generate = Mock(side_effect=rate_error())
    # Simulate OS suspension while sleeping: the inherited hard deadline passes.
    monkeypatch.setattr(llm_client.time, 'sleep', lambda seconds: now.__setitem__(0, 61))
    token = generation_deadline.set(60)
    try:
        with pytest.raises(llm_client.CentralizedLLMError):
            llm_client.execute_with_resilience(generate, 'gemini', 'model', skip_legacy_guard=True,
                attempt_admission=admissions, remaining_budget=lambda: 180 - now[0])
    finally:
        generation_deadline.reset(token)
    generate.assert_called_once()
    admissions.assert_called_once()


def test_whole_turn_deadline_oversleep_stops_before_second_admission(runtime, monkeypatch):
    now, sleeps, admission, breaker = runtime
    admissions = Mock(side_effect=admission)
    generate = Mock(side_effect=rate_error())
    monkeypatch.setattr(llm_client.time, 'sleep', lambda seconds: now.__setitem__(0, 61))
    with pytest.raises(llm_client.CentralizedLLMError):
        llm_client.execute_with_resilience(generate, 'gemini', 'model', skip_legacy_guard=True,
            attempt_admission=admissions, remaining_budget=lambda: 60 - now[0])
    generate.assert_called_once()
    admissions.assert_called_once()


def test_visible_output_and_daily_exhaustion_do_not_retry(runtime):
    now, sleeps, admission, breaker = runtime
    for error, can_retry in [(rate_error(), lambda: False),
                             (rate_error(kind=ProviderErrorKind.QUOTA_EXHAUSTED), lambda: True)]:
        generate = Mock(side_effect=error)
        with pytest.raises(llm_client.CentralizedLLMError):
            llm_client.execute_with_resilience(generate, 'gemini', 'model', skip_legacy_guard=True,
                attempt_admission=admission, remaining_budget=lambda: 180 - now[0],
                can_retry=can_retry)
        generate.assert_called_once()
    assert not sleeps


def test_retry_count_stays_bounded_and_no_unbounded_context_is_created(runtime):
    now, sleeps, admission, breaker = runtime
    generate = Mock(side_effect=rate_error())
    with pytest.raises(llm_client.CentralizedLLMError):
        llm_client.execute_with_resilience(generate, 'gemini', 'model', max_retries=1,
            skip_legacy_guard=True, attempt_admission=admission,
            remaining_budget=lambda: 180 - now[0])
    assert generate.call_count == 2
    generate.reset_mock()
    sleeps.clear()
    with pytest.raises(llm_client.CentralizedLLMError):
        llm_client.execute_with_resilience(generate, 'gemini', 'model',
            skip_legacy_guard=True, attempt_admission=admission, remaining_budget=lambda: None)
    generate.assert_called_once()
    assert not sleeps
