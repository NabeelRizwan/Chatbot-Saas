"""Offline router-to-SDK budgets; no credentials, database or provider calls."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
import time

import pytest
from google.genai import types

from services import llm_client, llm_router, provider_capacity
from services.providers.base_provider import generation_deadline, ProviderError, ProviderErrorKind
from services.providers.gemini_provider import GeminiProvider
from services.providers.generation_input import generation_input, current_input


@pytest.fixture
def sdk_boundary(monkeypatch):
    calls = []
    response = SimpleNamespace(text='Grounded answer', usage_metadata=None,
        candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)], sdk_http_response=None)

    def invoke(**kwargs):
        calls.append({'timeout_ms': kwargs['config'].http_options.timeout,
                      'remaining': generation_deadline.get() - time.monotonic()})
        return response

    models = SimpleNamespace(generate_content=invoke)
    provider = GeminiProvider()
    monkeypatch.setattr(provider, '_client', lambda key: SimpleNamespace(models=models))
    monkeypatch.setitem(llm_router.PROVIDERS, 'gemini', provider)
    monkeypatch.setattr(llm_router, '_resolve_api_key', lambda bot: ('synthetic-placeholder', False))
    monkeypatch.setattr(llm_router, '_admission_options',
                        lambda *args, **kwargs: {'skip_legacy_guard': True})
    monkeypatch.setattr(llm_client, 'global_circuit_breaker', llm_client.CircuitBreaker())
    monkeypatch.setattr(llm_client, 'LLM_TIMEOUT', 30.0)
    bot = SimpleNamespace(id=1, organization_id=2, provider='gemini',
                          model_name='gemini-3.5-flash-lite', capabilities={})
    return bot, calls, models, invoke


def test_actual_router_preserves_og_and_applies_explicit_rag2_sdk_budget(sdk_boundary):
    bot, calls, _, _ = sdk_boundary
    assert llm_router.generate(bot, 'Question') == 'Grounded answer'
    with generation_input(transport_timeout_seconds=150, generation_timeout_seconds=150,
                          require_complete=True):
        assert llm_router.generate(bot, 'Question') == 'Grounded answer'
    assert llm_router.generate(bot, 'Question') == 'Grounded answer'
    assert calls[0]['timeout_ms'] == calls[2]['timeout_ms'] == 20000
    assert 29 <= calls[0]['remaining'] <= 30
    assert 149000 <= calls[1]['timeout_ms'] <= 150000
    assert 149 <= calls[1]['remaining'] <= 150
    assert current_input().generation_timeout_seconds is None
    assert generation_deadline.get() is None


def test_transport_override_alone_does_not_extend_generation_retry_budget(sdk_boundary):
    bot, calls, _, _ = sdk_boundary
    with generation_input(transport_timeout_seconds=150):
        llm_router.generate(bot, 'Question')
    assert 29000 <= calls[0]['timeout_ms'] <= 30000


def test_planner_auxiliary_uses_60_seconds_and_keeps_og_auxiliary_budget(sdk_boundary, monkeypatch):
    from services.rag2.search_planning import plan_searches
    bot, calls, models, invoke = sdk_boundary
    monkeypatch.setattr(provider_capacity, 'enabled', lambda: False)
    monkeypatch.delenv('RAG_AUX_MODEL_GEMINI', raising=False)
    monkeypatch.delenv('LLAMA_SEARCH_PLANNER_TIMEOUT', raising=False)

    def plan_response(**kwargs):
        response = invoke(**kwargs)
        response.text = '{"queries":["Desk width"]}'
        return response

    models.generate_content = plan_response
    assert plan_searches(bot, 'How wide is the desk?')[0] == ['Desk width']
    # An OG caller with a long transport allowance does not opt into a larger
    # retry budget. The normal short OG auxiliary allowance also stays intact.
    llm_router.generate_auxiliary(bot, 'Question', 'System', timeout=60)
    llm_router.generate_auxiliary(bot, 'Question', 'System', timeout=5)
    assert 59000 <= calls[0]['timeout_ms'] <= 60000
    assert 29000 <= calls[1]['timeout_ms'] <= 30000
    assert calls[2]['timeout_ms'] == 10000  # Existing Gemini auxiliary SDK floor.
    assert current_input().generation_timeout_seconds is None


def test_inherited_shorter_generation_deadline_wins(sdk_boundary):
    bot, calls, _, _ = sdk_boundary
    parent = time.monotonic() + 18
    token = generation_deadline.set(parent)
    try:
        with generation_input(transport_timeout_seconds=150, generation_timeout_seconds=150):
            llm_router.generate(bot, 'Question')
        assert generation_deadline.get() == parent
    finally:
        generation_deadline.reset(token)
    assert 17000 <= calls[0]['timeout_ms'] <= 18000


@pytest.mark.parametrize('remaining', [25, 9])
def test_outer_turn_budget_wins_without_rounding_up(sdk_boundary, monkeypatch, remaining):
    bot, calls, _, _ = sdk_boundary
    monkeypatch.setattr(provider_capacity, 'enabled', lambda: True)
    monkeypatch.setattr(llm_router, '_admission_options', lambda *args, **kwargs: {
        'skip_legacy_guard': True,
        'remaining_budget': provider_capacity.provider_capacity_remaining})
    with provider_capacity.provider_capacity_context(timeout=remaining), \
            generation_input(transport_timeout_seconds=150, generation_timeout_seconds=150):
        if remaining < 10:
            with pytest.raises(llm_router.LLMRouterError):
                llm_router.generate(bot, 'Question')
        else:
            llm_router.generate(bot, 'Question')
    if remaining < 10:
        assert calls == []
    else:
        assert 24000 <= calls[0]['timeout_ms'] <= 25000


def test_retry_uses_remaining_request_budget_instead_of_resetting_it(sdk_boundary, monkeypatch):
    bot, calls, models, invoke = sdk_boundary
    clock = [1000.0]
    monkeypatch.setattr(llm_client.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(llm_client.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(llm_client.random, 'uniform', lambda *args: 0.0)
    monkeypatch.setattr(llm_client, 'LLM_BACKOFF_BASE', 1.0)
    attempts = []

    def fail_first(**kwargs):
        attempts.append(kwargs['config'].http_options.timeout)
        if len(attempts) == 1:
            clock[0] += 50
            raise ProviderError('Synthetic timeout', 504, kind=ProviderErrorKind.TIMEOUT)
        return invoke(**kwargs)

    models.generate_content = fail_first
    with generation_input(transport_timeout_seconds=150, generation_timeout_seconds=150):
        assert llm_router.generate(bot, 'Question') == 'Grounded answer'
    assert attempts == [150000, 99000]
    assert calls[0]['remaining'] == 99


def test_concurrent_og_and_rag2_budgets_are_request_scoped(sdk_boundary):
    bot, calls, models, invoke = sdk_boundary
    barrier = Barrier(2)

    def synchronized(**kwargs):
        barrier.wait(timeout=5)
        return invoke(**kwargs)

    models.generate_content = synchronized

    def run(improved):
        kwargs = {'transport_timeout_seconds': 150, 'generation_timeout_seconds': 150} if improved else {}
        with generation_input(**kwargs):
            result = llm_router.generate(bot, 'Question')
        assert current_input().generation_timeout_seconds is None
        assert generation_deadline.get() is None
        return result

    with ThreadPoolExecutor(2) as pool:
        assert list(pool.map(run, [False, True])) == ['Grounded answer', 'Grounded answer']
    values = sorted(call['timeout_ms'] for call in calls)
    assert values[0] == 20000 and 149000 <= values[1] <= 150000


@pytest.mark.parametrize('invalid', [True, 0, 9, 181, float('nan'), float('inf'), '150'])
def test_invalid_explicit_budget_is_rejected_before_provider(invalid):
    with pytest.raises(ValueError, match='invalid_generation_budget_timeout'):
        with generation_input(generation_timeout_seconds=invalid):
            pytest.fail('Invalid request input admitted')
    with pytest.raises(ValueError, match='invalid_generation_budget_timeout'):
        llm_client.execute_with_resilience(lambda: pytest.fail('Provider must not run'),
            'gemini', 'synthetic-model', generation_timeout_seconds=invalid)


def test_nested_request_input_restores_outer_budget_after_failure():
    with generation_input(generation_timeout_seconds=150):
        with pytest.raises(RuntimeError):
            with generation_input(generation_timeout_seconds=30):
                raise RuntimeError('Synthetic failure')
        assert current_input().generation_timeout_seconds == 150
    assert current_input().generation_timeout_seconds is None
