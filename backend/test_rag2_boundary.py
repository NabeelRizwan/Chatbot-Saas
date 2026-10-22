"""Pipeline integration contracts; synthetic evidence and no provider requests."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import threading
import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
import test_llama_rag  # Isolated test environment, never production data.

from services.rag2 import planned_client, search_planning
from services.rag2.client import RetrievalClient
from services.llama_rag.client_runtime import RetrievalError, retrieval_request_context, checkpoint
from services.providers.generation_input import generation_input, current_input
from services.providers.gemini_provider import _transport_timeout


def test_planner_receives_question_only_and_restores_request_contract():
    question = 'Compare the width and cleaning instructions for a Desk and Chair.'
    bot = SimpleNamespace(provider='gemini', model_name='gemini-3.5-flash-lite')
    queries = ['Desk width cleaning instructions', 'Chair width cleaning instructions']
    def provider(actual_bot, prompt, system, **kwargs):
        assert actual_bot is bot and prompt == question
        assert system == search_planning.PROMPT
        assert kwargs['tokens'] == 4096 and kwargs['use_auxiliary_model'] is True
        assert current_input().schema == search_planning.SCHEMA
        assert current_input().transport_timeout_seconds == 60
        return json.dumps({'queries': queries})
    with patch.object(search_planning, 'generate_auxiliary', side_effect=provider):
        result, meta = search_planning.plan_searches(bot, question)
    assert result == queries and meta['focused_searches'] == 2
    assert current_input().schema is None


@pytest.mark.parametrize('raw', ['{}', '{"queries":[]}', '{"queries":["a","a"]}',
    '{"queries":["a"],"answer":"invented"}', '{"queries":["a"],"queries":["b"]}',
    json.dumps({'queries': ['x'*421]}), json.dumps({'queries': ['x '*66]})])
def test_invalid_plans_are_not_repaired_or_replayed(raw):
    with patch.object(search_planning, 'generate_auxiliary', return_value=raw) as provider:
        with pytest.raises(RetrievalError, match='search_plan_invalid'):
            search_planning.plan_searches(SimpleNamespace(provider='gemini'), 'Question')
    assert provider.call_count == 1


def test_planned_transport_warms_one_missing_snapshot_and_preserves_queries():
    calls = []
    class Client:
        _routing = False
        url = 'http://retrieval:8000'
        def _request_at(self, url, path, body, **kwargs):
            calls.append(('request', body.copy(), kwargs))
            if len(calls) == 1:
                raise RetrievalError('snapshot_required')
            return {'question': body['question']}
        def _snapshot_at(self, url, scope, docs):
            calls.append(('snapshot', scope, docs))
    scope = {'organization_id': 1, 'bot_id': 2, 'fingerprint': 'abc',
             'pipeline': 'rag2_improved', 'pipeline_build_revision': 'rag2-voyage-v1'}
    result = planned_client.retrieve_planned(Client(), scope, [], 'Question', ['focused'])
    assert result == {'question': 'Question'}
    assert [call[0] for call in calls] == ['request', 'snapshot', 'request']
    assert calls[0][1]['queries'] == ['focused']
    assert calls[0][1]['pipeline'] == 'rag2_improved'
    assert 1430 < calls[0][1]['timeout_seconds'] <= 1440


def test_provider_failure_does_not_repeat_unknown_ranker_work():
    calls = []
    class Client:
        _routing = False
        url = 'http://retrieval:8000'
        def _request_at(self, *args, **kwargs):
            calls.append(1)
            raise RetrievalError('retrieval_service_503', retryable=True)
    with pytest.raises(RetrievalError):
        planned_client.retrieve_planned(Client(), {}, [], 'Question', ['focused'])
    assert len(calls) == 1


def test_parent_deadline_is_not_reset_by_planned_transport():
    with retrieval_request_context(timeout=2):
        with retrieval_request_context(timeout=1500, max_timeout=1800):
            assert 0 < checkpoint() <= 2
    with retrieval_request_context(timeout=1500):
        assert 410 < checkpoint() <= 420  # OG default remains bounded as before.


def test_simultaneous_og_and_improved_provider_contracts_are_isolated():
    barrier = Barrier(2)
    def invoke(improved):
        kwargs = {'thinking_level': 'medium', 'require_complete': True,
                  'transport_timeout_seconds': 150} if improved else {}
        with generation_input(**kwargs):
            barrier.wait(timeout=5)
            assert _transport_timeout() == (150 if improved else 20)
            assert current_input().require_complete is improved
        assert current_input().transport_timeout_seconds is None
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(invoke, [False, True]))


def test_ingestion_profile_is_added_and_health_requires_both_lanes():
    seen = []
    def handler(request):
        seen.append(request)
        if request.url.path == '/v1/prepare':
            body = json.loads(request.content)
            assert body['pipeline'] == 'rag2_improved'
            assert body['pipeline_build_revision'] == 'rag2-voyage-v1'
            return httpx.Response(200, json={'chunks': 3, 'embeddings': 0})
        if request.url.host == 'unready':
            return httpx.Response(503, json={'detail': 'voyage_quota_store_unavailable'})
        return httpx.Response(200, json={'status': 'ready', 'engine': 'llamaindex', 'protocol': 1,
            'pipeline': 'rag2_improved', 'pipeline_build_revision': 'rag2-voyage-v1',
            'quota_store': 'ready', 'provider_validation': 'not_probed'})
    transport = httpx.MockTransport(handler)
    client = RetrievalClient(url='http://ready:8000', token='s'*32, transport=transport, urls=())
    assert client.request('/v1/prepare', {'id': '1'})['chunks'] == 3
    assert client.readiness() == 'ready'
    two = RetrievalClient(url='http://ready:8000', token='s'*32, transport=transport,
                          urls=('http://ready:8000', 'http://unready:8000'))
    with pytest.raises(RetrievalError):
        two.readiness()
    assert any(request.url.host == 'unready' for request in seen)


def test_stop_cancels_transport_while_waiting_for_response_headers():
    entered, cancelled, closed = threading.Event(), threading.Event(), threading.Event()
    async def handler(request):
        entered.set()
        try:
            await asyncio.sleep(60)
            return httpx.Response(200, json={})
        finally:
            closed.set()
    client = RetrievalClient(url='http://retrieval:8000', token='s'*32,
                             transport=httpx.MockTransport(handler), urls=())
    def run():
        with retrieval_request_context(timeout=1500, max_timeout=1800, cancel_event=cancelled):
            client._request_at(client.url, '/v1/retrieve', {}, timeout=1500)
    with ThreadPoolExecutor(1) as pool:
        result = pool.submit(run)
        assert entered.wait(3)
        started = time.monotonic()
        cancelled.set()
        with pytest.raises(RetrievalError, match='retrieval_cancelled'):
            result.result(timeout=2)
        assert time.monotonic() - started < 2
    assert closed.is_set()
