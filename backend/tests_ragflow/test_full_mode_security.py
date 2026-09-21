"""Every optional artifact mode goes through the same fail-closed capability boundary."""
import asyncio
from dataclasses import replace
import pytest
from ragflow_derived.contracts import EngineError
from ragflow_derived.advanced import operation_for
from ragflow_derived.full_runtime import full_operation
from ragflow_derived.upstream.doc_store import OrderByExpr
from .fixtures import scope
from .test_full_artifacts import tokenizer_assets_not_required
from .test_full_graph import graph_fixture


@pytest.mark.parametrize('mode,kind', [('navigation', 'structure'), ('raptor', 'raptor'), ('graph', 'graph')])
@pytest.mark.parametrize('attack', ['org', 'bot', 'version', 'generation', 'deleted', 'document', 'node', 'text', 'manifest'])
def test_all_artifact_modes_deny_foreign_or_corrupt_candidates(mode, kind, attack):
    e, s = graph_fixture()
    asyncio.run(e.compile(s, kind=kind))
    if attack in {'org', 'bot', 'version', 'generation'}:
        argument = {'org': {'org': 'foreign'}, 'bot': {'bot': 'foreign'},
                    'version': {'version': '99'}, 'generation': {'generation': 'foreign'}}[attack]
        s = scope(**argument)
    elif attack == 'deleted':
        e.backend.delete(s, s.sources[0])
    elif attack == 'text':
        row = next(iter(next(iter(e.artifact_io.indices.values())).rows.values()))
        row['content_with_weight'] += ' altered'
    elif attack == 'manifest':
        next(iter(e.artifact_io.manifests.values()))['leaves'] = {}
    with pytest.raises(EngineError):
        op = operation_for(e, s, ['foreign'] if attack == 'document' else None, kind)
        with full_operation(op):
            condition = {'id': ['foreign-node']} if attack == 'node' else {}
            # Reads use actual compiled dispatch for each artifact family.
            condition[{'structure': 'compile_kwd', 'raptor': 'raptor_kwd', 'graph': 'knowledge_graph_kwd'}[kind]] = (
                ['tree', 'dataset_nav'] if kind == 'structure' else 'raptor' if kind == 'raptor'
                else ['entity', 'relation', 'graph', 'subgraph'])
            op.store.search([], [], condition, [], OrderByExpr(), 0, 10000, s.index, [s.bot_id])


@pytest.mark.parametrize('mode', ['low', 'medium', 'high', 'ultra'])
def test_every_agentic_mode_rejects_model_requested_foreign_documents(mode):
    e, s = graph_fixture()
    with pytest.raises(EngineError, match='UNAUTHORIZED_SCOPE'):
        asyncio.run(e.research(s, 'Inspect laboratory records.', thinking_mode=mode,
                               document_ids=['foreign-document']))
    assert not e.chat_model.prompts


def test_embedding_failure_is_not_hidden_by_optional_tool_fallback():
    from ragflow_derived.engine import CheckedEmbeddings
    e, s = graph_fixture()
    op = operation_for(e, s)
    def fail(*a): raise TimeoutError('offline embedding failure')
    e.embedding.encode_queries = fail
    with pytest.raises(EngineError, match='EMBEDDING_UNAVAILABLE'):
        with full_operation(op):
            try:
                CheckedEmbeddings(e.embedding, s).encode_queries('calibration')
            except EngineError:
                pass
