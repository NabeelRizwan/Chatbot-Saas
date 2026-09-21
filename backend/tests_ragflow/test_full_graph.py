"""Actual upstream KG extraction, merge, indexing and search; provider doubles only."""
import asyncio
import json
import pytest
from ragflow_derived.advanced import operation_for
from ragflow_derived.full_runtime import full_operation
from ragflow_derived.contracts import EngineError
from ragflow_derived.upstream.doc_store import OrderByExpr
from .test_full_artifacts import compilation_fixture, SummaryModel
from .fixtures import TokenizerDouble
from ragflow_derived.upstream.runtime import native_tokenizer


@pytest.fixture(autouse=True)
def offline_tokenizer(monkeypatch):
    monkeypatch.setattr(native_tokenizer, '_instance', TokenizerDouble())


class GraphModel(SummaryModel):
    async def async_chat(self, system, history, gen_conf=None, **kwargs):
        self.prompts.append((system, history))
        prompt = system + '\n' + '\n'.join(m['content'] for m in history[-1:])
        if 'answer_type_keywords' in prompt:
            return json.dumps({'answer_type_keywords': ['organization'], 'entities_from_query': ['LABORATORY']})
        if 'identify all entities' in prompt:
            return ('("entity"<|>LABORATORY<|>organization<|>The laboratory calibrates equipment.)##'
                    '("entity"<|>EQUIPMENT<|>category<|>Equipment needs weekly calibration.)##'
                    '("relationship"<|>LABORATORY<|>EQUIPMENT<|>The laboratory calibrates equipment weekly.<|>calibration<|>8)<|COMPLETE|>')
        if 'YES' in prompt or 'yes' in prompt or 'missed' in prompt:
            return 'NO'
        return 'The laboratory calibrates equipment weekly.'


def graph_fixture():
    e, s = compilation_fixture()
    e.chat_model = GraphModel()
    return e, s


def test_actual_light_graph_extraction_merge_and_storage():
    e, s = graph_fixture()
    result = asyncio.run(e.compile(s, kind='graph', graphrag_config={'retry_attempts': 1}))
    assert result['lineage_precision'] == 'document'
    assert set(result['completed_documents']) == {v.document_id for v in s.sources}
    op = operation_for(e, s, artifact_kind='graph')
    with full_operation(op):
        found = op.store.search([], [], {'knowledge_graph_kwd': ['entity', 'relation', 'graph', 'subgraph']},
                                [], OrderByExpr(), 0, 100, [s.index], [s.bot_id])
        rows = [h['_source'] for h in found['hits']['hits']]
        assert {'entity', 'relation', 'graph', 'subgraph'} <= {r['knowledge_graph_kwd'] for r in rows}
        assert all(r['artifact_leaf_ids'] and r['generated_int'] == 1 for r in rows)
    assert e.chat_model.prompts


@pytest.mark.parametrize('config', [{'method': 'ner'}, {'community': True}])
def test_uninstalled_optional_graph_mode_is_explicitly_unavailable(config):
    e, s = graph_fixture()
    with pytest.raises(EngineError, match='MODE_UNAVAILABLE'):
        asyncio.run(e.compile(s, kind='graph', graphrag_config=config))
    assert not e.artifact_io.indices and not e.chat_model.prompts


def test_actual_graph_search_rewrites_queries_and_returns_generated_context_with_source_support():
    e, s = graph_fixture()
    asyncio.run(e.compile(s, kind='graph', graphrag_config={'retry_attempts': 1}))
    result = asyncio.run(e.retrieve_mode(s, 'Who calibrates laboratory equipment?', mode='graph'))
    assert result['generated_context']
    assert result['generated_artifacts'] and result['evidence']
    assert all(a['generated'] and a['lineage_precision'] == 'document' for a in result['generated_artifacts'])
    assert all(not ev.metadata['generated'] for ev in result['evidence'])
    assert any('answer_type_keywords' in system for system, _ in e.chat_model.prompts)


def test_model_provider_failure_cannot_be_swallowed_by_kg_rewrite_fallback():
    e, s = graph_fixture()
    asyncio.run(e.compile(s, kind='graph', graphrag_config={'retry_attempts': 1}))
    async def fail(*a, **k):
        raise EngineError('CHAT_MODEL_UNAVAILABLE', 'offline injected failure')
    e.chat_model.async_chat = fail
    with pytest.raises(EngineError, match='CHAT_MODEL_UNAVAILABLE'):
        asyncio.run(e.retrieve_mode(s, 'Who calibrates laboratory equipment?', mode='graph'))
