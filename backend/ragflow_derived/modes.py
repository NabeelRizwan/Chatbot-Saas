"""Explicit mode entrypoints. Algorithms live in pinned upstream modules."""
from dataclasses import asdict
from .advanced import operation_for, exact_evidence
from .contracts import EngineError
from .engine import CheckedEmbeddings, CheckedReranker
from .full_runtime import full_operation, scoped_documents
from .model_runtime import AuthorizedChatModel, model_operation


def validate_query(query):
    if not isinstance(query, str) or not query.strip() or len(query) > 16384:
        raise EngineError('RETRIEVAL_FAILED', 'query bounds')


def make_tools(engine, op, query):
    from .upstream.advanced_rag.agentic_rag import RAGTools
    tools = RAGTools([op.scope.key], AuthorizedChatModel(engine.chat_model, op.check),
                     CheckedEmbeddings(engine.embedding, op.scope), kbs=op.catalog.knowledgebases(),
                     doc_scope=scoped_documents(), thinking_mode='high', original_user_question=query,
                     similarity_threshold=engine.config.similarity_threshold,
                     vector_similarity_weight=engine.config.vector_weight, top_n=12,
                     rerank_candidates_count=engine.config.candidates, top_k=engine.config.knn_top_k)
    op.tools = tools
    return tools


def generated_records(op, ids=None):
    artifacts = op.store.artifacts
    rows = artifacts.seen if ids is None else {cid: artifacts.seen[cid] for cid in ids}
    return [{'artifact_id': cid, 'text': row['content_with_weight'], 'generated': True,
             'organization_id': op.scope.organization_id, 'bot_id': op.scope.bot_id,
             'scope_key': op.scope.key, 'generation': op.scope.generation,
             'support_sources': [s.__dict__.copy() for s in op.scope.sources
                                 if s.key in {artifacts.leaves[leaf]['source_key'] for leaf in row['artifact_leaf_ids']}],
             'lineage_precision': 'document' if artifacts.kind == 'graph' else 'source_chunk',
             'source_chunk_ids': list(row['artifact_leaf_ids']), 'artifact_hash': row['artifact_hash_kwd']}
            for cid, row in rows.items()]


def supporting_evidence(op, generated):
    ids = sorted({cid for artifact in generated for cid in artifact['source_chunk_ids']})
    if ids:
        op.store.artifacts._validate_leaves(ids)
    return [exact_evidence(op, {'chunk_id': cid}) for cid in ids]


async def navigate(engine, scope, query, *, document_id=None, document_ids=None):
    from .upstream.advanced_rag.harness.tools.navigation import _navigate_tree_impl, _navigate_structure_impl
    validate_query(query)
    op = operation_for(engine, scope, document_ids, 'structure')
    with full_operation(op), model_operation(scope):
        if document_id is not None:
            scoped_documents([document_id])
        make_tools(engine, op, query)
        result = (await _navigate_structure_impl(query, doc_id=document_id, doc_scope=scoped_documents())
                  if document_id is not None else await _navigate_tree_impl(query, doc_scope=scoped_documents()))
        op.check()
        scoped_documents(result.doc_ids)
        generated = generated_records(op)
        evidence = supporting_evidence(op, generated)
        return {'mode': 'navigation', 'navigation': asdict(result), 'generated_artifacts': generated,
                'evidence': evidence, 'lineage_note': 'Artifact support inventory, not claim-level citation alignment.'}


async def graph_retrieve(engine, scope, query, *, document_ids=None):
    from .upstream.graphrag.search import KGSearch
    validate_query(query)
    op = operation_for(engine, scope, document_ids, 'graph')
    with full_operation(op), model_operation(scope):
        model = AuthorizedChatModel(engine.chat_model, op.check)
        kg = KGSearch(op.store, queryer=engine.queryer)
        result = await kg.retrieval(query, [scope.key], [scope.bot_id], CheckedEmbeddings(engine.embedding, scope), model)
        op.check()
        generated = generated_records(op)
        return {'mode': 'graph', 'generated_context': result['content_with_weight'],
                'generated_artifacts': generated, 'evidence': supporting_evidence(op, generated),
                'lineage_note': 'Document-level provenance for inspected graph candidates, not exact claim citations.'}


async def raptor_retrieve(engine, scope, query, *, top_k=12, document_ids=None):
    validate_query(query)
    if not 1 <= top_k <= engine.config.candidates:
        raise EngineError('RETRIEVAL_FAILED', 'top-k bounds')
    op = operation_for(engine, scope, document_ids, 'raptor')
    with full_operation(op):
        result = await op.retriever.retrieval(query, CheckedEmbeddings(engine.embedding, scope),
            [scope.key], [scope.bot_id], 1, top_k, engine.config.similarity_threshold,
            vector_similarity_weight=engine.config.vector_weight, knn_top_k=engine.config.knn_top_k,
            knn_num_candidates=engine.config.knn_num_candidates,
            doc_ids=document_ids, rerank_mdl=CheckedReranker(engine.reranker) if engine.reranker else None,
            rerank_candidates_count=engine.config.candidates)
        selected = [c['chunk_id'] for c in result['chunks']]
        summaries = [cid for cid in selected if cid in op.store.artifacts.rows]
        generated = generated_records(op, summaries)
        evidence = [exact_evidence(op, c) for c in result['chunks'] if c['chunk_id'] not in summaries]
        known = {e.chunk_id for e in evidence}
        evidence += [e for e in supporting_evidence(op, generated) if e.chunk_id not in known]
        op.check()
        return {'mode': 'raptor', 'selected_order': selected, 'generated_artifacts': generated, 'evidence': evidence}
