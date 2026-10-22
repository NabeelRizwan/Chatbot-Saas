"""No models or provider calls: deployment-boundary and ranking invariants."""
from copy import deepcopy
from types import SimpleNamespace
import json
import time

import httpx
import pytest
import fakeredis
from rag2.request_budget import RequestBudget
from fastapi.testclient import TestClient

import service
from rag2.assemble_packets import digest_text, render_item
from rag2.pipeline import PlannedRetrievalEngine, assemble_searches, validate_queries
from rag2.voyage import PassageRanker, VoyagePredictor, VoyageError, QuotaLedger, retry_after_seconds


def packet(source, text, question='question'):
    item = {'citation_id': '1', 'source_id': source, 'subject_source_id': source,
        'title': 'Source ' + source, 'subject_title': 'Source ' + source,
        'url': 'https://example.test/' + source, 'section': 'Details', 'text': text,
        'start_char': 0, 'end_char': len(text), 'source_sha256': digest_text(text),
        'table_headers': [], 'evidence_roles': [], 'score': 0.5, 'node_id': 'context-' + source}
    context = render_item(item)
    result = {'question': question, 'evidence': [item], 'context': context,
              'context_tokens': len(context), 'context_sha256': digest_text(context),
              'audit': {'unique_candidates': 1}}
    doc = {'title': item['title'], 'text': text, 'url': item['url']}
    return result, doc


def test_planned_sources_are_exact_and_original_prefix_is_immutable():
    first, a = packet('1', 'Original product directions.')
    second, b = packet('2', 'A newly ingested arbitrary document.')
    called = []
    def retrieve(query):
        called.append(query)
        return first if query == 'original' else second
    result = assemble_searches('original', ['focused'], retrieve, {'1': a, '2': b}, list)
    assert called == ['original', 'focused']
    assert result['context'].startswith(first['context'])
    assert result['evidence'][0] == first['evidence'][0]
    assert [item['citation_id'] for item in result['evidence']] == ['1', '2']
    assert result['evidence'][1]['text'] == b['text']
    assert result['planning']['context_cap'] == 48000
    assert result['context_tokens'] <= 48000


def test_no_focus_is_native_rag2_and_duplicate_query_executes_once():
    native, doc = packet('1', 'Exact source.')
    calls = []
    def retrieve(query):
        calls.append(query)
        return native
    result = assemble_searches('original', ['original'], retrieve, {'1': doc}, list)
    assert calls == ['original']
    assert result['context'] == native['context']
    result = assemble_searches('original', [], retrieve, {'1': doc}, list)
    assert result['planning']['context_cap'] == 5200


def test_all_seven_maximum_lanes_remain_within_budget():
    rows = [packet(str(index), 'x' * 4900) for index in range(1, 8)]
    documents = {str(index): row[1] for index, row in enumerate(rows, 1)}
    result = assemble_searches('1', [str(i) for i in range(2, 8)],
                              lambda query: rows[int(query)-1][0], documents, list)
    assert len(result['evidence']) == 7
    assert result['context_tokens'] <= 48000
    assert result['context'].startswith(rows[0][0]['context'])


@pytest.mark.parametrize('corruption', ['text', 'source_id', 'source_sha256'])
def test_source_identity_tampering_fails_closed(corruption):
    native, doc = packet('1', 'Exact source.')
    native['evidence'][0][corruption] = 'tampered'
    with pytest.raises(ValueError):
        assemble_searches('question', [], lambda _: native, {'1': doc}, list)


def test_lane_cannot_exceed_native_budget():
    native, doc = packet('1', 'x' * 5300)
    with pytest.raises(ValueError):
        assemble_searches('question', ['focus'], lambda _: native, {'1': doc}, list)


@pytest.mark.parametrize('queries', [['x'] * 2, ['x'] * 7, [''], ['x' * 421], ['x ' * 66], [123]])
def test_invalid_plans_fail_closed(queries):
    with pytest.raises(ValueError):
        validate_queries(queries)


def test_passage_wrapper_preserves_discovery_and_restores_secondary_model():
    local, voyage = object(), object()
    class Ranker:
        _model = local
        def postprocess_nodes(self, nodes, **kwargs):
            return self._model
    ranker = Ranker()
    wrapper = PassageRanker(ranker, voyage)
    discovery = [SimpleNamespace(node=SimpleNamespace(metadata={'discovery_only': True}))]
    passage = [SimpleNamespace(node=SimpleNamespace(metadata={}))]
    assert wrapper.postprocess_nodes(discovery) is local
    assert wrapper.postprocess_nodes(passage) is voyage
    assert ranker._model is local
    wrapper.remote.postprocess_nodes = lambda *a, **k: (_ for _ in ()).throw(ValueError('failure'))
    with pytest.raises(ValueError):
        wrapper.postprocess_nodes(passage)
    assert ranker._model is local


class Tokens:
    def encode(self, text, **kwargs):
        return SimpleNamespace(ids=list(text))


class Ledger:
    def __init__(self):
        self.reservations = []
    def reserve(self, tokens, deadline):
        self.reservations.append(tokens)
        return str(len(self.reservations))
    def reconcile(self, key, tokens):
        self.last = key, tokens
    def defer(self, seconds):
        self.cooldown = seconds


def test_voyage_preserves_order_and_all_text_with_bounded_batches():
    requests = []
    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, json={'model': 'rerank-3', 'data': [
            {'index': i, 'relevance_score': float(ord(text[0]))}
            for i, text in reversed(list(enumerate(body['documents'])))], 'usage': {'total_tokens': 3000}})
    scorer = VoyagePredictor('test-key', Tokens(), Ledger(), transport=httpx.MockTransport(respond))
    scorer.budget = RequestBudget(5)
    pairs = [('q', 'a' * 1700), ('q', 'b' * 1700), ('q', 'c' * 1700), ('other', 'd')]
    assert scorer.predict(pairs) == [97., 98., 99., 100.]
    assert [text for request in requests for text in request['documents']] == [p[1] for p in pairs]
    assert all(request['model'] == 'rerank-3' and request['truncation'] is False for request in requests)
    assert all(sum(len(request['query']) + len(text) for text in request['documents']) <= 3500 for request in requests)


@pytest.mark.parametrize('status', [401, 429, 503])
def test_provider_failures_have_no_local_score_fallback(status):
    scorer = VoyagePredictor('test-key', Tokens(), Ledger(), max_attempts=1,
        transport=httpx.MockTransport(lambda request: httpx.Response(status, json={'error': 'unavailable'})))
    scorer.budget = RequestBudget(2)
    with pytest.raises(VoyageError):
        scorer.predict([('query', 'passage')])


def ledgers():
    server = fakeredis.FakeServer()
    return (QuotaLedger(fakeredis.FakeRedis(server=server), 'test-account'),
            QuotaLedger(fakeredis.FakeRedis(server=server), 'test-account'))


def test_quota_ledger_coordinates_independent_predictors():
    first, second = ledgers()
    for ledger in (first, second, first):
        ledger.reserve(3000, RequestBudget(1))
    with pytest.raises(VoyageError, match='deadline'):
        second.reserve(100, RequestBudget(.01))


def test_shared_cooldown_blocks_another_worker_without_real_wait():
    first, second = ledgers()
    first.defer(120)
    original = first.redis.get(first.keys[2])
    second.defer(30)
    assert second.redis.get(second.keys[2]) == original
    with pytest.raises(VoyageError, match='deadline'):
        second.reserve(100, RequestBudget(1))
    assert first.redis.zcard(first.keys[0]) == 0


def test_429_publishes_cooldown_even_when_no_retry_remains():
    first, second = ledgers()
    scorer = VoyagePredictor('test-key', Tokens(), first, max_attempts=1,
        transport=httpx.MockTransport(lambda request: httpx.Response(429, headers={'Retry-After': '90'})))
    with pytest.raises(VoyageError, match='unavailable'):
        scorer.predict([('query', 'passage')])
    with pytest.raises(VoyageError, match='deadline'):
        second.reserve(100, RequestBudget(1))
    assert first.redis.pttl(first.keys[2]) > 89000
    assert first.redis.zcard(first.keys[0]) == 1


def test_429_without_retry_header_publishes_default_cooldown():
    ledger = Ledger()
    scorer = VoyagePredictor('test-key', Tokens(), ledger, max_attempts=1,
        transport=httpx.MockTransport(lambda request: httpx.Response(429)))
    scorer.budget = RequestBudget(1)
    with pytest.raises(VoyageError):
        scorer.predict([('query', 'passage')])
    assert ledger.cooldown == 62


def test_quota_reconciliation_never_refunds_reserved_consumption():
    ledger, _ = ledgers()
    key = ledger.reserve(3500, RequestBudget(1))
    ledger.reconcile(key, 100)
    assert int(ledger.redis.hget(ledger.keys[1], key)) == 3500
    ledger.reconcile(key, 3700)
    assert int(ledger.redis.hget(ledger.keys[1], key)) == 3700


def test_retry_after_accepts_http_dates_and_rejects_invalid_numbers(monkeypatch):
    monkeypatch.setattr('rag2.voyage.time.time', lambda: 0)
    assert retry_after_seconds('Thu, 01 Jan 1970 00:02:00 GMT') == 120
    assert retry_after_seconds('nan') == 0
    assert retry_after_seconds('-5') == 0
    assert retry_after_seconds('invalid') == 0


def test_service_passes_plan_through_authorized_snapshot(tmp_path, monkeypatch):
    class FakePlanned(PlannedRetrievalEngine):
        def __init__(self, config):
            self.config = config
        def build_or_load(self):
            pass
        def status(self):
            return {'ready': True}
        def retrieve_planned(self, question, queries, *, budget=None):
            return {'question': question, 'evidence': [], 'queries_received': queries}
    monkeypatch.setenv('LLAMA_RETRIEVAL_TOKEN', 'test-authorization-token-at-least-32-characters')
    monkeypatch.setattr(service, 'store', service.IndexStore(tmp_path / 'data', tmp_path / 'models', FakePlanned))
    monkeypatch.setattr(service, 'get_rag2_store', lambda: service.store)
    records = [{'id': '1', 'source_id': '1', 'title': 'New upload', 'url': 'https://example.test/new',
                'text': 'New knowledge.', 'version': 1, 'crawl_id': None}]
    scope = {'organization_id': 1, 'bot_id': 1, 'fingerprint': service.fingerprint(records),
             'pipeline': 'rag2_improved', 'pipeline_build_revision': 'rag2-voyage-v1'}
    headers = {'Authorization': 'Bearer test-authorization-token-at-least-32-characters'}
    with TestClient(service.app) as client:
        assert client.post('/v1/snapshots', json={**scope, 'documents': records}, headers=headers).status_code == 200
        reply = client.post('/v1/retrieve', json={**scope, 'question': 'Original', 'queries': ['Focused']}, headers=headers)
        assert reply.status_code == 200
        assert reply.json()['queries_received'] == ['Focused']
        assert reply.json()['fingerprint'] == scope['fingerprint']
        assert client.post('/v1/retrieve', json={**scope, 'bot_id': 2, 'question': 'Original', 'queries': ['Focused']}, headers=headers).status_code == 409
