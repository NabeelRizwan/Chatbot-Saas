"""Storage, API and failure gates for optional modes; no provider/network access."""
import asyncio
import copy
import json
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from ragflow_derived.advanced import operation_for
from ragflow_derived.artifacts import ElasticsearchArtifactIO
from ragflow_derived.contracts import EngineError
from ragflow_derived.full_runtime import full_operation
from ragflow_derived.upstream.doc_store import OrderByExpr
from ragflow_dev.app import create_app
from ragflow_dev.config import Settings
from ragflow_dev.runtime import Runtime
from .fixtures import scope
from .test_native_dev import ApiRuntimeDouble
from .test_full_artifacts import compilation_fixture, tokenizer_assets_not_required


def test_manifest_uses_single_unindexed_string_and_roundtrips():
    class Client:
        def create(self, **kw): self.saved = kw['document']
        def get(self, **kw): return {'_source': self.saved}
    client = Client()
    io = ElasticsearchArtifactIO(SimpleNamespace(client=client))
    scope = SimpleNamespace(index='synthetic', key='scope')
    manifest = {'scope_key_kwd': 'scope', 'rows': {str(i): {'sha': str(i)} for i in range(2000)}}
    io.publish(scope, 'key', manifest)
    assert set(client.saved) == {'scope_key_kwd', 'available_int', 'compiled_manifest_with_weight'}
    assert isinstance(client.saved['compiled_manifest_with_weight'], str)
    assert io.load(scope, 'key') == manifest
    client.saved['scope_key_kwd'] = 'foreign'
    with pytest.raises(EngineError, match='PROVENANCE_FAILED'):
        io.load(scope, 'key')


def test_uncertain_successful_publication_never_deletes_published_index():
    e, s = compilation_fixture()
    publish = e.artifact_io.publish
    def uncertain(*args):
        publish(*args)
        raise TimeoutError('synthetic transport interruption after successful CREATE')
    e.artifact_io.publish = uncertain
    with pytest.raises(Exception):
        asyncio.run(e.compile(s, kind='raptor'))
    assert len(e.artifact_io.indices) == len(e.artifact_io.manifests) == 1
    op = operation_for(e, s, artifact_kind='raptor')
    assert op.store.artifacts.published


def test_publication_readback_detects_missing_generated_row():
    e, s = compilation_fixture()
    insert = e.artifact_io.insert
    def missing(index, rows):
        insert(index, rows)
        if rows:
            e.artifact_io.indices[index.index].rows.pop(rows[0]['id'])
    e.artifact_io.insert = missing
    with pytest.raises(EngineError, match='PROVENANCE_FAILED'):
        asyncio.run(e.compile(s, kind='raptor'))
    assert not e.artifact_io.manifests and not e.artifact_io.indices


@pytest.mark.parametrize('condition', [{}, {'doc_id': []}])
def test_empty_authority_does_not_issue_search(condition):
    e, s = compilation_fixture()
    op = operation_for(e, s, document_ids=[])
    def forbidden(*a, **kw): raise AssertionError('empty document scope reached backend')
    e.backend.search = forbidden
    with full_operation(op):
        result = op.store.search([], [], condition, [], OrderByExpr(), 0, 10, s.index, [s.bot_id])
    assert result['hits']['total']['value'] == 0


def test_compiled_transport_failure_is_latched_if_upstream_catches_it():
    e, s = compilation_fixture()
    asyncio.run(e.compile(s, kind='raptor'))
    op = operation_for(e, s, artifact_kind='raptor')
    def broken(*a, **kw): raise TimeoutError('synthetic transport failure')
    e.artifact_io.search = broken
    with pytest.raises(EngineError, match='RETRIEVAL_FAILED'):
        with full_operation(op):
            try:
                op.store.search([], [], {'raptor_kwd': 'raptor'}, [], OrderByExpr(), 0, 5, s.index, [s.bot_id])
            except Exception:
                pass  # upstream recoverable branches must not hide this failure


class FullApiRuntimeDouble(ApiRuntimeDouble):
    def compile(self, tenant, payload): return {'tenant': tenant, 'kind': payload.kind}
    def advanced(self, tenant, payload): return {'tenant': tenant, 'mode': payload.mode}


def test_artifact_inventory_can_only_narrow_server_scope():
    authorized = scope()
    narrow = Runtime.artifact_scope(authorized, ['manual'])
    assert narrow.sources == authorized.sources[:1] and narrow.key == authorized.key
    for invalid in [[], ['foreign'], ['manual', 'manual'], ['manual', 'foreign']]:
        with pytest.raises(EngineError, match='UNAUTHORIZED_SCOPE'):
            Runtime.artifact_scope(authorized, invalid)


@pytest.mark.parametrize('path,body', [
    ('compile', {'kind': 'raptor', 'source_versions': {'manual': 1}, 'generation': 'g'}),
    ('advanced', {'mode': 'agentic', 'query': 'How are laboratory records reviewed?'}),
    ('advanced', {'mode': 'graph', 'query': 'What relates the laboratory and its inspector?'}),
    ('advanced', {'mode': 'raptor', 'query': 'Summarize inspection procedures.'}),
    ('advanced', {'mode': 'navigation', 'query': 'Find inspection procedures.'}),
])
def test_new_endpoints_require_tenant_credential(path, body):
    settings = Settings('unused', 'a' * 48, 'b' * 48, 'c' * 48, 'new-project')
    with TestClient(create_app(settings, FullApiRuntimeDouble)) as client:
        for token in ['', 'wrong', 'c' * 48]:
            assert client.post('/ragflow-dev/' + path, json=body,
                               headers={'Authorization': 'Bearer ' + token}).status_code == 401
        for tenant in ['a', 'b']:
            response = client.post('/ragflow-dev/' + path, json=body,
                                   headers={'Authorization': 'Bearer ' + tenant * 48})
            assert response.status_code == 200 and response.json()['tenant'] == tenant
