"""Explicit compilation entrypoints using pinned upstream builders and serializers."""
from collections import defaultdict
from types import SimpleNamespace
import copy
import numpy as np
from .contracts import EngineError
from .advanced import operation_for
from .artifacts import ArtifactSession, ElasticsearchArtifactIO, MAX_ARTIFACT_ROWS
from .engine import CheckedEmbeddings
from .full_runtime import full_operation
from .model_runtime import AuthorizedChatModel, model_operation
from .upstream.doc_store import OrderByExpr
from .upstream.raptor_config import RaptorConfig
from .upstream.raptor_service import RaptorService
from .upstream.raptor_utils import should_skip_raptor
from .upstream.tree_graph import raptor_tree_to_graph, rewrite_duplicate_tree_names
from .upstream.advanced_rag.knowlege_compile.dataset_nav import upsert_dataset_nav_doc, build_nav_graph_text
from .upstream.advanced_rag.knowlege_compile.structure import _struct_upsert_tree_graph_rows, _struct_upsert_graph_json


def load_leaves(op):
    scope = op.scope
    fields = ['id', 'content_ltks', 'content_sm_ltks', 'parser_metadata_kwd',
              'source_type_kwd', f'q_{scope.dimension}_vec']
    found = op.store.search(fields, [], {}, [], OrderByExpr().asc('chunk_order_int'),
                            0, MAX_ARTIFACT_ROWS, [scope.index], [scope.bot_id])
    if found['hits']['total']['value'] > MAX_ARTIFACT_ROWS:
        op.refuse('INGESTION_FAILED', 'development compilation source bound')
    rows = [h['_source'] for h in found['hits']['hits']]
    if not rows:
        op.refuse('MODE_UNAVAILABLE', 'empty compilation corpus')
    # Retrieval IDs are the authoritative leaf identity (never model output).
    for hit, row in zip(found['hits']['hits'], rows):
        row['id'] = hit['_id']
    return rows


async def compile_artifacts(engine, scope, *, kind, raptor_config=None, graphrag_config=None):
    if kind == 'graph':
        return await compile_graph(engine, scope, graphrag_config)
    if kind not in {'raptor', 'structure'}:
        raise EngineError('MODE_UNAVAILABLE', 'explicit supported compiler required')
    cfg = RaptorConfig(**copy.deepcopy(raptor_config or {})).model_dump()
    if cfg['scope'] != 'file':
        raise EngineError('MODE_UNAVAILABLE', 'dataset RAPTOR compilation not exposed')
    op = operation_for(engine, scope)
    io = getattr(engine, 'artifact_io', None) or ElasticsearchArtifactIO(engine.backend)
    artifacts = ArtifactSession(op.store, io, kind)
    op.store.artifacts = artifacts
    op.lock_factory = artifacts.lock_factory
    try:
        with full_operation(op), model_operation(scope):
            model = AuthorizedChatModel(engine.chat_model, op.check)
            embeddings = CheckedEmbeddings(engine.embedding, scope)
            op.tools = SimpleNamespace(embed_mdl=embeddings)
            leaves = load_leaves(op)
            artifacts.add_leaves(leaves)
            docs = defaultdict(list)
            for row in leaves:
                docs[row['doc_id']].append(row)
            skipped = []
            for doc_id, rows in docs.items():
                title = rows[0]['docnm_kwd']
                if should_skip_raptor(rows[0].get('source_type_kwd'), raptor_config=cfg):
                    skipped.append(doc_id)
                    continue
                ctx = SimpleNamespace(tenant_id=scope.key, kb_id=scope.bot_id, doc_id=doc_id,
                                      id='', name=title, pagerank=0, progress_cb=lambda *a, **k: None)
                service = RaptorService(ctx)
                inputs = [(r['content_with_weight'], np.asarray(r[f'q_{scope.dimension}_vec']), r['id'])
                          for r in sorted(rows, key=lambda r: r['chunk_order_int'])]
                if kind == 'raptor':
                    generated, _ = await service._generate_raptor(inputs, doc_id, cfg, model, embeddings,
                                                                 3, {doc_id: {'name': title}})
                    artifacts.insert(generated)
                else:
                    tree = await service.build_doc_tree(inputs, cfg, model, embeddings, 3)
                    op.check()
                    if tree is None:
                        skipped.append(doc_id)
                        continue
                    await rewrite_duplicate_tree_names(tree, model)
                    graph = raptor_tree_to_graph(tree)
                    artifacts.register_tree_lineage(doc_id, graph)
                    await _struct_upsert_tree_graph_rows(graph, scope.key, scope.bot_id, doc_id,
                                                        title, embeddings)
                    await _struct_upsert_graph_json(graph, scope.key, scope.bot_id, doc_id, title, 'tree')
                    nav_title, nav_text = build_nav_graph_text(graph)
                    await upsert_dataset_nav_doc(scope.key, scope.bot_id, doc_id,
                                                 {'title': nav_title, 'graph_text': nav_text}, embeddings, model)
                op.check()
            seal = artifacts.publish()
            return {'kind': kind, 'seal': seal, 'rows': len(artifacts.rows), 'leaves': len(artifacts.leaves),
                    'skipped_documents': skipped, 'generated': True}
    except BaseException:
        artifacts.abandon()
        raise


async def compile_graph(engine, scope, config=None):
    from .upstream.graphrag_config import GraphragConfig
    from .upstream.graphrag.general.index import run_graphrag_for_kb
    cfg = GraphragConfig(**copy.deepcopy(config or {})).model_dump()
    if cfg['method'] == 'ner' or cfg['community']:
        raise EngineError('MODE_UNAVAILABLE', 'optional spaCy/community native assets not installed')
    op = operation_for(engine, scope)
    io = getattr(engine, 'artifact_io', None) or ElasticsearchArtifactIO(engine.backend)
    artifacts = ArtifactSession(op.store, io, 'graph')
    op.store.artifacts, op.lock_factory = artifacts, artifacts.lock_factory
    try:
        with full_operation(op), model_operation(scope):
            model = AuthorizedChatModel(engine.chat_model, op.check)
            embeddings = CheckedEmbeddings(engine.embedding, scope)
            op.tools = SimpleNamespace(embed_mdl=embeddings)
            leaves = load_leaves(op)
            artifacts.add_leaves(leaves)
            docs = sorted({r['doc_id'] for r in leaves})
            result = await run_graphrag_for_kb(
                {'tenant_id': scope.key, 'kb_id': scope.bot_id, 'id': ''}, docs, 'English',
                {'graphrag': cfg}, model, embeddings, lambda *a, **k: None,
                with_resolution=cfg['resolution'], with_community=cfg['community'])
            op.check()
            if result['failed_docs'] or set(result['ok_docs']) != set(docs):
                op.refuse('INGESTION_FAILED', 'incomplete KG compilation')
            seal = artifacts.publish()
            return {'kind': 'graph', 'seal': seal, 'rows': len(artifacts.rows),
                    'leaves': len(artifacts.leaves), 'generated': True,
                    'lineage_precision': 'document', 'completed_documents': result['ok_docs']}
    except BaseException:
        artifacts.abandon()
        raise
