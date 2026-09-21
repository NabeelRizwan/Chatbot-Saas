"""Compiled storage security and real upstream CPU compilation; no network/model API."""
import asyncio
import copy
import json
from dataclasses import replace
import pytest
from ragflow_derived.advanced import operation_for
from ragflow_derived.artifacts import ArtifactSession, digest
from ragflow_derived.contracts import EngineError
from ragflow_derived.engine import EngineConfig
from ragflow_derived.full_runtime import full_operation
from ragflow_derived.upstream.doc_store import OrderByExpr
from .fixtures import engine, scope, MemoryFixtureBackend, TokenizerDouble
from .test_full_agentic import ResearchModel


@pytest.fixture(autouse=True)
def tokenizer_assets_not_required(monkeypatch):
    from ragflow_derived.upstream.runtime import native_tokenizer
    monkeypatch.setattr(native_tokenizer, '_instance', TokenizerDouble())


class MemoryArtifactIO:
    """IO contract double only; real Elasticsearch parity is a separate gate."""
    def __init__(self):
        self.indices, self.manifests, self.calls = {}, {}, []

    def create(self, index):
        assert index.index not in self.indices
        self.indices[index.index] = MemoryFixtureBackend()

    def insert(self, index, rows):
        self.indices[index.index].rows.update({r['id']: copy.deepcopy(r) for r in rows})

    def delete_rows(self, index, ids):
        for cid in ids:
            self.indices[index.index].rows.pop(cid, None)

    def search(self, fields, highlights, condition, expressions, order, offset, limit, indexes, kb_ids, **kwargs):
        self.calls.append((copy.deepcopy(condition), indexes, kb_ids))
        backend = MemoryFixtureBackend()
        for index in indexes:
            source = self.indices.get(index) or self.source_backend
            backend.rows.update(source.rows)
        physical = ['ragflow_' + condition['scope_key_kwd']]
        return backend.search(fields, highlights, condition, expressions, order, offset, limit, physical, kb_ids, **kwargs)

    def publish(self, scope, key, manifest):
        if (scope.key, key) in self.manifests:
            raise EngineError('INDEX_FAILED', 'publish conflict')
        self.manifests[scope.key, key] = copy.deepcopy(manifest)

    def load(self, scope, key):
        return copy.deepcopy(self.manifests.get((scope.key, key)))

    def abandon(self, index):
        self.indices.pop(index.index)


class SummaryModel(ResearchModel):
    async def async_chat(self, system, history, gen_conf=None, **kwargs):
        self.prompts.append((system, history))
        if 'JSON' in system and 'title' in system:
            return json.dumps({'title': 'Laboratory Operations', 'description': 'Laboratory calibration and safety.'})
        return 'Laboratory Operations\nCalibrate equipment weekly and inspect protective guards.'


def compilation_fixture():
    e, s = engine(config=EngineConfig(chunk_tokens=8, similarity_threshold=0)), scope()
    e.ingest(s, 'manual', 'Calibrate laboratory equipment every seven days.\nInspect protective guards before starting equipment.\nKeep calibration records for annual inspections.', title='Calibration Manual')
    e.ingest(s, 'terms', 'Review laboratory safety records each month.\nKeep emergency exits unobstructed during work.\nCheck protective clothing before hazardous tasks.', title='Safety Manual')
    e.artifact_io = MemoryArtifactIO()
    e.artifact_io.source_backend = e.backend
    e.chat_model = SummaryModel()
    return e, s


def test_actual_raptor_compiles_publishes_and_preserves_leaf_provenance():
    e, s = compilation_fixture()
    result = asyncio.run(e.compile(s, kind='raptor'))
    assert result['rows'] >= 2 and result['generated']
    op = operation_for(e, s, artifact_kind='raptor')
    with full_operation(op):
        found = op.store.search([], [], {'raptor_kwd': 'raptor'}, [], OrderByExpr(), 0, 100,
                                [s.index], [s.bot_id])
        assert found['hits']['hits']
        for hit in found['hits']['hits']:
            assert hit['_source']['generated_int'] == 1
            assert hit['_source']['source_chunk_ids']
    assert all(not row.get('generated_int') for row in e.backend.rows.values())


def test_actual_tree_compiler_builds_navigation_and_graph_from_real_leaves():
    e, s = compilation_fixture()
    result = asyncio.run(e.compile(s, kind='structure'))
    assert result['rows'] >= 6
    op = operation_for(e, s, artifact_kind='structure')
    artifacts = op.store.artifacts
    rows = next(iter(e.artifact_io.indices.values())).rows.values()
    assert {'tree', 'dataset_nav'} <= {r.get('compile_kwd') for r in rows}
    assert {'graph', 'entity'} <= {r.get('knowledge_graph_kwd') for r in rows}
    # Small-N upstream collapse legitimately creates one summary per document,
    # not invented child edges. A separate larger fixture exercises real edges.
    for row in rows:
        artifacts.validate(row, row['id'])


def test_large_actual_tree_has_source_bound_child_relations():
    e, s = engine(config=EngineConfig(chunk_tokens=5, similarity_threshold=0)), scope()
    sections = ['Microscope optics cleaning schedule', 'Centrifuge rotor inspection interval',
                'Chemical cabinet ventilation checks', 'Electrical grounding measurements',
                'Water purification maintenance steps', 'Temperature probe calibration procedure',
                'Fire extinguisher storage requirements', 'Glassware disposal handling instructions',
                'Emergency shower weekly activation', 'Pressure gauge annual certification',
                'Laser enclosure safety interlocks', 'Specimen freezer alarm operation']
    for source in s.sources:
        e.ingest(s, source.source_id, '\n'.join(sections), title='Operations handbook')
    e.artifact_io, e.chat_model = MemoryArtifactIO(), SummaryModel()
    asyncio.run(e.compile(s, kind='structure'))
    rows = next(iter(e.artifact_io.indices.values())).rows.values()
    relations = [r for r in rows if r.get('knowledge_graph_kwd') == 'relation']
    assert relations and all(r['artifact_leaf_ids'] for r in relations)


@pytest.mark.parametrize('change', ['foreign_org', 'foreign_bot', 'stale_version', 'wrong_generation'])
def test_compiled_publication_cannot_cross_scope(change):
    e, s = compilation_fixture()
    asyncio.run(e.compile(s, kind='raptor'))
    altered = {'foreign_org': scope(org='other'), 'foreign_bot': scope(bot='other'),
               'stale_version': scope(version='old'), 'wrong_generation': scope(generation='old')}[change]
    with pytest.raises(EngineError, match='MODE_UNAVAILABLE|UNAUTHORIZED_SCOPE'):
        operation_for(e, altered, artifact_kind='raptor')


def test_deleted_source_invalidates_generated_aggregate_before_read():
    e, s = compilation_fixture()
    asyncio.run(e.compile(s, kind='raptor'))
    e.backend.delete(s, s.sources[0])
    with pytest.raises(EngineError, match='UNAUTHORIZED_SCOPE'):
        operation_for(e, s, artifact_kind='raptor')


def test_model_foreign_node_is_rejected_before_artifact_search():
    e, s = compilation_fixture()
    asyncio.run(e.compile(s, kind='raptor'))
    op = operation_for(e, s, artifact_kind='raptor')
    with pytest.raises(EngineError, match='UNAUTHORIZED_SCOPE'):
        with full_operation(op):
            op.store.search([], [], {'raptor_kwd': 'raptor', 'id': ['foreign-node']}, [], OrderByExpr(),
                            0, 5, s.index, [s.bot_id])


def test_changed_generated_text_is_rejected_even_if_backend_returns_it():
    e, s = compilation_fixture()
    asyncio.run(e.compile(s, kind='raptor'))
    op = operation_for(e, s, artifact_kind='raptor')
    row = next(iter(next(iter(e.artifact_io.indices.values())).rows.values()))
    row['content_with_weight'] = 'tampered'
    with pytest.raises(EngineError, match='PROVENANCE_FAILED'):
        with full_operation(op):
            op.store.search([], [], {'raptor_kwd': 'raptor'}, [], OrderByExpr(), 0, 100, s.index, [s.bot_id])


def test_subset_authority_does_not_reuse_broader_aggregate_manifest():
    e, s = compilation_fixture()
    asyncio.run(e.compile(s, kind='raptor'))
    with pytest.raises(EngineError, match='MODE_UNAVAILABLE'):
        operation_for(e, replace(s, sources=s.sources[:1]), artifact_kind='raptor')


def test_publication_conflict_leaves_prior_completed_index_unchanged():
    e, s = compilation_fixture()
    asyncio.run(e.compile(s, kind='raptor'))
    before = copy.deepcopy(e.artifact_io.manifests)
    with pytest.raises(EngineError, match='INDEX_FAILED'):
        asyncio.run(e.compile(s, kind='raptor'))
    assert e.artifact_io.manifests == before
    assert len(e.artifact_io.indices) == 1
