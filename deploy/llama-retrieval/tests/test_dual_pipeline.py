"""Mixed-engine ownership, quota coordination and cancellation without providers."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import threading
import time

import fakeredis
import httpx
import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

import service
from rag2 import pipeline
from rag2.request_budget import RequestBudget, VoyageError, yield_cpu
from rag2.redis_quota import QuotaLedger
from rag2.voyage import PassageRanker, VoyagePredictor
from test_planned_voyage import Tokens, Ledger, packet
from test_service import Engine, AUTH, TOKEN, payload, scope


def rag2_scope(body):
    return {**scope(body), 'pipeline': 'rag2_improved',
            'pipeline_build_revision': service.RAG2_BUILD_REVISION}


def test_profile_and_build_identity_keep_legacy_og_and_isolate_rag2(tmp_path, monkeypatch):
    og = service.IndexStore(tmp_path/'data', tmp_path/'models', Engine)
    monkeypatch.setattr(service, 'store', og)
    other = service.get_rag2_store()
    other.engine_factory = Engine
    old = service.Scope(**scope(payload()))
    new = service.Scope(**rag2_scope(payload()))
    assert service.selected_store(old) is og
    assert service.selected_store(new) is other
    assert og.path(old) == tmp_path/'data'/'1-1'/old.fingerprint
    assert other.path(new) == tmp_path/'data'/'pipelines'/'rag2-voyage-v1'/'1-1'/old.fingerprint
    with og.admitted():
        original = og.load(old, payload()['documents'])
    with other.admitted():
        improved = other.load(new, payload()['documents'])
    assert original is not improved
    assert improved.config.independent_question_coverage is True
    assert original.config.independent_question_coverage is False
    with og.admitted():
        assert og.load(old) is original  # OG -> RAG2 -> OG reuses the same build.
        og.max_entries = 0
        og.prune(None)
    assert other.path(new).exists()  # Legacy pruning cannot remove the other tree.
    assert service.get_rag2_store().load(new) is improved


@pytest.mark.parametrize('changes', [
    {'pipeline':'foreign'}, {'pipeline_build_revision':'../outside'},
    {'pipeline':'rag2_improved'}, {'organization_policy_revision':99},
    {'pipeline':'og','pipeline_build_revision':'rag2-voyage-v1'},
    {'timeout_seconds':1441}, {'timeout_seconds':0}, {'timeout_seconds':float('inf')},
])
def test_unknown_or_unbounded_profile_is_rejected(changes):
    with pytest.raises(ValueError):
        service.Search(**{**scope(payload()), 'question':'Width?', **changes})


def test_rag2_response_echoes_profile_and_old_response_stays_unchanged(tmp_path, monkeypatch):
    class Planned(Engine):
        def retrieve_planned(self, question, queries, *, budget):
            budget.remaining()
            return {'question':question,'evidence':[]}
    monkeypatch.setenv('LLAMA_RETRIEVAL_TOKEN', TOKEN)
    monkeypatch.setattr(service,'store',service.IndexStore(tmp_path/'data',tmp_path/'models',Engine))
    other=service.get_rag2_store();other.engine_factory=Planned
    body=payload(); improved=rag2_scope(body)
    with TestClient(service.app) as client:
        legacy=client.post('/v1/snapshots',json=body,headers=AUTH)
        assert set(legacy.json()) == {'fingerprint','status'}
        uploaded=client.post('/v1/snapshots',json={**improved,'documents':body['documents']},headers=AUTH)
        assert uploaded.json()['pipeline_build_revision']=='rag2-voyage-v1'
        result=client.post('/v1/retrieve',json={**improved,'question':'Width?','queries':['Size?']},headers=AUTH)
        assert result.status_code==200 and result.json()['pipeline']=='rag2_improved'
        old=client.post('/v1/retrieve',json={**scope(body),'question':'Width?'},headers=AUTH)
        assert set(old.json())=={'fingerprint','question','evidence'}
        # A trusted scope may not use a different tenant's retained snapshot.
        assert client.post('/v1/retrieve',json={**improved,'organization_id':2,'question':'Width?'},headers=AUTH).status_code==409


def test_private_real_pydantic_ranker_does_not_swap_shared_model():
    from llama_index.core.postprocessor import SentenceTransformerRerank
    from llama_index.core.callbacks import CallbackManager
    from llama_index.core.schema import NodeWithScore, TextNode, QueryBundle
    local=SimpleNamespace(predict=lambda pairs:[.2]*len(pairs))
    remote=SimpleNamespace(predict=lambda pairs:[.9]*len(pairs))
    ranker=SentenceTransformerRerank.model_construct(model='fixture',top_n=2,
        keep_retrieval_score=False,callback_manager=CallbackManager([]))
    ranker._model=local
    wrapper=PassageRanker(ranker,remote)
    nodes=[NodeWithScore(node=TextNode(text='Private source text'))]
    assert wrapper.postprocess_nodes(nodes,query_bundle=QueryBundle('question'))[0].score==.9
    assert ranker._model is local
    assert ranker.postprocess_nodes(nodes,query_bundle=QueryBundle('question'))[0].score==.2


def test_actual_variant_orchestration_releases_og_cpu_during_remote_wait(monkeypatch,tmp_path):
    entered,release=threading.Event(),threading.Event()
    async def respond(request):
        entered.set()
        while not release.is_set(): await asyncio.sleep(.01)
        return httpx.Response(200,json={'model':'rerank-3','data':[{'index':0,'relevance_score':.9}],
            'usage':{'total_tokens':5}})
    local=SimpleNamespace(predict=lambda pairs:[.2]*len(pairs))
    class Ranker:
        _model=local
        def postprocess_nodes(self,nodes,**kwargs): return self._model.predict([('q','evidence')])
    runtime=SimpleNamespace(lock=threading.RLock(),reranker=Ranker(),context_tokenizer=list,tokenizer=None)
    engine=object.__new__(pipeline.PlannedRetrievalEngine)
    engine._lock=threading.RLock();engine.runtime=runtime;engine.config=SimpleNamespace(root=tmp_path)
    engine._reranker=runtime.reranker;engine._source_nodes={};engine._model_nodes={};engine._block_index={}
    base,doc=packet('1','Evidence.');base['audit']['reranked_candidates']=[];engine._documents={'1':doc}
    def base_retrieve(self,question):
        with self._lock,self.runtime.lock:
            assert self._reranker.postprocess_nodes([SimpleNamespace(node=SimpleNamespace(metadata={}))])==[.9]
            return base
    monkeypatch.setattr(pipeline.LocalRetrievalEngine,'retrieve',base_retrieve)
    monkeypatch.setattr(pipeline,'prepare_candidates',lambda *a,**k:{'proposals':[]})
    monkeypatch.setattr(pipeline,'assemble',lambda base,*a,**k:base)
    monkeypatch.setattr(VoyagePredictor,'from_environment',lambda root,**kw:
        VoyagePredictor('test-key',Tokens(),Ledger(),transport=httpx.MockTransport(respond),**kw))
    def og_search():
        with runtime.lock:
            assert runtime.reranker._model is local
            return runtime.reranker.postprocess_nodes([])
    with ThreadPoolExecutor(max_workers=2) as pool:
        work=pool.submit(engine.retrieve_planned,'q',[],budget=RequestBudget(5))
        assert entered.wait(2)
        try:
            assert pool.submit(og_search).result(timeout=1)==[.2]
            assert not work.done()
        finally: release.set()
        assert work.result(timeout=2)['context']==base['context']
    assert runtime.reranker._model is local


def test_remote_transport_cancel_stops_inflight_attempt_without_retry():
    entered=threading.Event();budget=RequestBudget(5);ledger=Ledger()
    async def delayed(request):
        entered.set();await asyncio.sleep(10)
    scorer=VoyagePredictor('key',Tokens(),ledger,budget=budget,transport=httpx.MockTransport(delayed))
    with ThreadPoolExecutor(max_workers=1) as pool:
        work=pool.submit(scorer.predict,[('q','text')])
        assert entered.wait(1)
        budget.cancel_event.set()
        with pytest.raises(VoyageError,match='cancelled'):work.result(timeout=1)
    assert len(ledger.reservations)==1


def test_atomic_shared_quota_under_simultaneous_independent_clients():
    server=fakeredis.FakeServer()
    def reserve(_):
        ledger=QuotaLedger(fakeredis.FakeRedis(server=server),'account')
        try:ledger.reserve(1000,RequestBudget(.05));return True
        except VoyageError:return False
    with ThreadPoolExecutor(max_workers=12) as pool:
        assert sum(pool.map(reserve,range(12)))==3


def test_token_limit_and_usage_reconciliation_are_shared():
    server=fakeredis.FakeServer()
    first=QuotaLedger(fakeredis.FakeRedis(server=server),'account')
    second=QuotaLedger(fakeredis.FakeRedis(server=server),'account')
    key=first.reserve(3500,RequestBudget(1));first.reconcile(key,7000)
    with pytest.raises(VoyageError,match='deadline'):second.reserve(3500,RequestBudget(.01))
    # Expiry removes both the reservation and its token accounting.
    first.redis.zadd(first.keys[0],{key:0})
    second.reserve(3500,RequestBudget(1))
    assert first.redis.hget(first.keys[1],key) is None


def test_redis_failure_and_disagreeing_worker_limits_fail_closed():
    server=fakeredis.FakeServer();client=fakeredis.FakeRedis(server=server)
    first=QuotaLedger(client,'account');first.reserve(100,RequestBudget(1))
    other=QuotaLedger(fakeredis.FakeRedis(server=server),'account',rpm=4)
    with pytest.raises(VoyageError,match='configuration_mismatch'):other.reserve(100,RequestBudget(1))
    server.connected=False
    with pytest.raises(VoyageError,match='store_unavailable'):first.reserve(100,RequestBudget(1))


def test_rag2_admission_wait_can_be_cancelled_without_touching_og(tmp_path,monkeypatch):
    og=service.IndexStore(tmp_path/'data',tmp_path/'models',Engine)
    monkeypatch.setattr(service,'store',og);other=service.get_rag2_store()
    budget=RequestBudget(10);other.lock.acquire()
    def blocked():
        with other.admitted(budget):raise AssertionError('cancelled request admitted')
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            work=pool.submit(blocked);budget.cancel_event.set()
            with pytest.raises(VoyageError,match='cancelled'):work.result(timeout=1)
            with og.admitted():pass
    finally:other.lock.release()


def test_route_disconnect_signal_stops_the_worker_before_another_attempt(monkeypatch):
    entered=threading.Event();calls=[]
    def work(body,budget):
        calls.append(body.pipeline);entered.set()
        while True:budget.pause(.01)
    class DisconnectedRequest:
        async def is_disconnected(self):return entered.is_set()
    monkeypatch.setattr(service,'execute_search',work)
    request=service.Search(**rag2_scope(payload()),question='Question',timeout_seconds=5)
    with pytest.raises(HTTPException) as error:
        asyncio.run(service.retrieve(request,DisconnectedRequest()))
    assert error.value.status_code==503
    assert error.value.detail=='voyage_request_cancelled'
    assert calls==['rag2_improved']


def test_rag2_readiness_does_not_claim_live_provider_validation(tmp_path,monkeypatch):
    og=service.IndexStore(tmp_path/'data',tmp_path/'models',Engine)
    og.runtime=SimpleNamespace(ready=True);og.startup_ready=True
    monkeypatch.setattr(service,'store',og)
    other=service.get_rag2_store();other.startup_ready=True
    checked=[]
    monkeypatch.setattr(VoyagePredictor,'from_environment',lambda root:
        SimpleNamespace(ledger=SimpleNamespace(ready=lambda:checked.append('redis'))))
    assert service.ready()=={'status':'ready','engine':'llamaindex','protocol':1}
    result=service.rag2_ready()
    assert checked==['redis'] and result['provider_validation']=='not_probed'
    monkeypatch.setattr(VoyagePredictor,'from_environment',lambda root:
        (_ for _ in ()).throw(VoyageError('voyage_quota_store_unavailable')))
    with pytest.raises(HTTPException) as error:service.rag2_ready()
    assert error.value.status_code==503
    assert service.ready()['status']=='ready'


def test_quota_override_requires_operator_verification_and_account_key_is_shared(monkeypatch):
    root=Path(service.__file__).parent
    monkeypatch.setenv('VOYAGE_API_KEY','synthetic-key')
    monkeypatch.setenv('VOYAGE_REDIS_URL','redis://unused.test/0')
    monkeypatch.setenv('VOYAGE_RPM','6')
    monkeypatch.delenv('VOYAGE_QUOTA_LIMITS_VERIFIED',raising=False)
    with pytest.raises(VoyageError,match='configuration_invalid'):
        VoyagePredictor.from_environment(root)
    monkeypatch.setenv('VOYAGE_QUOTA_LIMITS_VERIFIED','true')
    monkeypatch.setenv('VOYAGE_QUOTA_ACCOUNT_ID','one-provider-account')
    monkeypatch.setattr('rag2.voyage.Redis.from_url',lambda *a,**k:fakeredis.FakeRedis())
    first=VoyagePredictor.from_environment(root)
    monkeypatch.setenv('VOYAGE_API_KEY','different-key-same-account')
    second=VoyagePredictor.from_environment(root)
    assert first.ledger.keys==second.ledger.keys
    assert first.ledger.rpm==6 and first.ledger.tpm==10000
