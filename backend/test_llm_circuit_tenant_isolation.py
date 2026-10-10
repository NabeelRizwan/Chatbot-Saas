from contextlib import contextmanager
from unittest.mock import Mock

import pytest

from services import llm_client
from services.providers.base_provider import ProviderError, ProviderErrorKind


@pytest.fixture
def breaker(monkeypatch):
    breaker = llm_client.CircuitBreaker(failure_threshold=5)
    monkeypatch.setattr(llm_client, 'global_circuit_breaker', breaker)
    return breaker


def execute(fn, org_id=1, **kwargs):
    return llm_client.execute_with_resilience(
        fn, 'gemini', 'shared-model', org_id=org_id,
        max_retries=0, skip_legacy_guard=True, **kwargs)


@pytest.mark.parametrize('kind,status', [
    (ProviderErrorKind.RATE_LIMIT, 429),
    (ProviderErrorKind.QUOTA_EXHAUSTED, 429),
    (ProviderErrorKind.AUTHENTICATION, 401),
    (ProviderErrorKind.BILLING_RESTRICTION, 403),
    (ProviderErrorKind.INVALID_MODEL, 404),
    (ProviderErrorKind.INVALID_REQUEST, 400),
    (ProviderErrorKind.INVALID_REQUEST, 499),
    (ProviderErrorKind.UNKNOWN, 500),
])
def test_one_tenants_credential_or_request_errors_do_not_block_another(breaker, kind, status):
    generate = Mock(side_effect=ProviderError('Request failed', status_code=status, kind=kind))
    for _ in range(6):
        with pytest.raises(llm_client.CentralizedLLMError) as caught:
            execute(generate)
        assert caught.value.code != llm_client.LLMErrorCode.LLM_CIRCUIT_OPEN
    assert generate.call_count == 6
    assert breaker.is_allowed('gemini', 'shared-model')
    unrelated = Mock(return_value='Unrelated tenant answer')
    assert execute(unrelated, org_id=2) == 'Unrelated tenant answer'
    unrelated.assert_called_once()


@pytest.mark.parametrize('capacity_code', [
    'provider_capacity_cancelled',
    'provider_capacity_unavailable',
    'provider_capacity_deadline_exceeded',
])
def test_capacity_admission_failures_do_not_count_as_provider_outage(breaker, capacity_code):
    from services import llm_router
    from services.provider_capacity import ProviderCapacityError

    @contextmanager
    def denied():
        raise llm_router._capacity_error(ProviderCapacityError(capacity_code))
        yield

    generate = Mock(return_value='Should never run')
    for _ in range(6):
        with pytest.raises(llm_client.CentralizedLLMError) as caught:
            execute(generate, attempt_admission=denied, remaining_budget=lambda: 180)
        assert caught.value.code != llm_client.LLMErrorCode.LLM_CIRCUIT_OPEN
    generate.assert_not_called()
    assert execute(lambda: 'Other tenant still works', org_id=2) == 'Other tenant still works'


def test_expired_whole_turn_before_provider_call_does_not_open_circuit(breaker):
    generate = Mock(return_value='Should never run')
    for _ in range(6):
        with pytest.raises(llm_client.CentralizedLLMError) as caught:
            execute(generate, remaining_budget=lambda: 0)
        assert caught.value.code == llm_client.LLMErrorCode.LLM_TIMEOUT
    generate.assert_not_called()
    assert breaker.is_allowed('gemini', 'shared-model')


@pytest.mark.parametrize('kind', [
    ProviderErrorKind.TEMPORARY,
    ProviderErrorKind.UNAVAILABLE,
    ProviderErrorKind.TIMEOUT,
])
def test_real_provider_health_failures_still_open_shared_circuit(breaker, kind):
    generate = Mock(side_effect=ProviderError('Provider failed', status_code=503, kind=kind))
    for _ in range(5):
        with pytest.raises(llm_client.CentralizedLLMError):
            execute(generate)
    generate.assert_called()
    assert not breaker.is_allowed('gemini', 'shared-model')
    unrelated = Mock(return_value='Provider still down')
    with pytest.raises(llm_client.CentralizedLLMError) as caught:
        execute(unrelated, org_id=2)
    assert caught.value.code == llm_client.LLMErrorCode.LLM_CIRCUIT_OPEN
    unrelated.assert_not_called()
