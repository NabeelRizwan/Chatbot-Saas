import json
import os
import time

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

import service

TOKEN = 'isolated-unit-test-auth-token-32-characters'
AUTH = {'Authorization': 'Bearer ' + TOKEN}


class Engine:
    def __init__(self, config):
        self.config = config
    def build_or_load(self):
        return self.status()
    def status(self):
        return {'ready': True}
    def retrieve(self, question):
        return {'question': question, 'evidence': []}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('LLAMA_RETRIEVAL_TOKEN', TOKEN)
    monkeypatch.setattr(service, 'store', service.IndexStore(tmp_path/'cache', tmp_path/'models', Engine))
    with TestClient(service.app) as client:
        yield client


def payload(bot=1, org=1, text='A desk is 120 cm wide.'):
    rows=[{'id':'1','source_id':'1','title':'Desk','url':'https://example.test/desk','text':text,
           'version':1,'crawl_id':None}]
    return {'organization_id':org,'bot_id':bot,'fingerprint':service.fingerprint(rows),'documents':rows}


def scope(body):
    return {key:value for key,value in body.items() if key!='documents'}


def test_authenticated_snapshot_then_scoped_retrieval(client):
    body=payload()
    assert client.post('/v1/snapshots',json=body).status_code==401
    assert client.post('/v1/snapshots',json=body,headers=AUTH).status_code==200
    assert client.post('/v1/retrieve',json={**scope(body),'question':'Width?'},headers=AUTH).status_code==200
    for changes in ({'bot_id':2},{'organization_id':2},{'fingerprint':'a'*64}):
        assert client.post('/v1/retrieve',json={**scope(body),**changes,'question':'Width?'},headers=AUTH).status_code==409


def test_snapshot_digest_cannot_be_reused_with_other_content(client):
    body=payload(); body['documents'][0]['text']='Unrelated data'
    assert client.post('/v1/snapshots',json=body,headers=AUTH).status_code==422
    assert service.store.engine is None


@pytest.mark.parametrize('changes',[{'bot_id':True},{'organization_id':0},{'fingerprint':'../outside'},
    {'documents':[]},{'organization_id':'1'},{'extra':'value'}])
def test_scope_identifiers_and_body_are_strict(client,changes):
    assert client.post('/v1/snapshots',json={**payload(),**changes},headers=AUTH).status_code==422


def test_persisted_snapshot_integrity_checked_when_reloading(client):
    body=payload()
    client.post('/v1/snapshots',json=body,headers=AUTH)
    path=service.store.path(service.Scope(**scope(body)))/'corpus.jsonl'
    path.write_text(json.dumps(payload(text='tampered')['documents'][0])+'\n')
    service.store.engine=None; service.store.active_key=None
    result=client.post('/v1/retrieve',json={**scope(body),'question':'Width?'},headers=AUTH)
    assert result.status_code==503


def test_busy_service_rejects_without_unbounded_queue(client,monkeypatch):
    class Busy:
        def acquire(self, **kwargs): return False
    monkeypatch.setattr(service.store,'lock',Busy())
    result=client.post('/v1/snapshots',json=payload(),headers=AUTH)
    assert result.status_code==503
    assert result.headers['Retry-After']=='2'


def test_expired_cache_and_loaded_engine_are_released(client):
    body=payload(); client.post('/v1/snapshots',json=body,headers=AUTH)
    path=service.store.active_key
    old=time.time()-service.store.ttl-1
    os.utime(path,(old,old)); service.store.sweep()
    assert service.store.engine is None and not path.exists()


def test_cache_capacity_and_snapshot_count_are_bounded(client):
    service.store.max_entries=1
    first=payload(); second=payload(bot=2)
    client.post('/v1/snapshots',json=first,headers=AUTH)
    first_path=service.store.active_key
    client.post('/v1/snapshots',json=second,headers=AUTH)
    assert not first_path.exists()
    service.store.max_bytes=1
    with pytest.raises(HTTPException) as raised:
        service.store.sweep()
    assert raised.value.status_code==507


def test_body_limit_is_applied_before_json_validation(client,monkeypatch):
    monkeypatch.setattr(service,'MAX_BODY',100)
    assert client.post('/v1/snapshots',content=b' '*101,headers=AUTH).status_code==413


def test_missing_models_is_not_ready(client):
    assert client.get('/health/live').status_code==200
    assert client.get('/health/ready',headers=AUTH).status_code==503
