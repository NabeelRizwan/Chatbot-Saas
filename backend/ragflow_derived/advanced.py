"""Platform boundary around the complete pinned agentic executor, not its helpers alone."""
import copy
import json
import hashlib
from types import SimpleNamespace
from .contracts import EngineError, Evidence
from .full_runtime import FullOperation, full_operation
from .model_runtime import AuthorizedChatModel, model_operation
from .storage import ScopedStore
from .upstream.doc_store import OrderByExpr
from .upstream.search import Dealer


class AdvancedScopedStore(ScopedStore):
    """Scope failures are latched even if an upstream optional tool catches them."""
    operation = None
    artifacts = None

    def check(self):
        if self.operation and self.operation.fatal:
            raise self.operation.fatal
        try:
            super().check()
        except EngineError as exc:
            if self.operation:
                self.operation.fatal = exc
            raise

    def search(self, *args, **kwargs):
        try:
            # Upstream DocStore accepts a single index name and both positional
            # and named parameters. Normalize only the calling convention; the
            # existing exact routing and returned-row checks still run.
            args = list(args)
            aliases = {'select_fields': 'fields', 'highlight_fields': 'highlights',
                       'match_expressions': 'expressions', 'order_by': 'order',
                       'index_names': 'indexes', 'knowledgebase_ids': 'kb_ids'}
            for old, new in aliases.items():
                if old in kwargs:
                    if new in kwargs:
                        raise EngineError('UNAUTHORIZED_SCOPE', 'duplicate routing argument')
                    kwargs[new] = kwargs.pop(old)
            if len(args) > 7 and isinstance(args[7], str):
                args[7] = [args[7]]
            if isinstance(kwargs.get('indexes'), str):
                kwargs['indexes'] = [kwargs['indexes']]
            if len(args) > 9:
                kwargs['agg_fields'] = args.pop(9)
            return self._dispatch_search(*args, **kwargs)
        except EngineError as exc:
            if self.operation:
                self.operation.fatal = exc
            raise
        except Exception:
            if self.operation:
                self.operation.refuse('RETRIEVAL_FAILED', 'advanced storage')
            raise EngineError('RETRIEVAL_FAILED', 'advanced storage') from None

    def _dispatch_search(self, fields, highlights, condition, expressions, order, offset, limit, indexes, kb_ids, **kwargs):
        if indexes != [self.scope.index] or kb_ids != [self.scope.bot_id]:
            raise EngineError('UNAUTHORIZED_SCOPE', 'advanced routing')
        is_compiled = any(key in condition for key in ('compile_kwd', 'knowledge_graph_kwd', 'raptor_kwd'))
        if is_compiled and self.artifacts is not None:
            return self.artifacts.search(fields, highlights, condition, expressions, order, offset, limit, **kwargs)
        if self.artifacts is not None and self.artifacts.kind == 'raptor' and not self.artifacts.writable:
            return self.artifacts.search_raptor(fields, highlights, condition, expressions, order, offset, limit, **kwargs)
        return super().search(fields, highlights, condition, expressions, order, offset, limit, indexes, kb_ids, **kwargs)

    @staticmethod
    def get_aggregation(result, field):
        # Pinned ESConnectionBase.get_aggregation result format.
        return [(b['key'], b['doc_count']) for b in result.get('aggregations', {}).get(
            'aggs_' + field, {}).get('buckets', [])]

    def insert(self, rows, index, kb_id):
        self.check()
        if index != self.scope.index or kb_id != self.scope.bot_id or self.artifacts is None:
            self.operation.refuse(stage='compiled write routing')
        try:
            self.artifacts.insert(rows)
            return []
        except EngineError as exc:
            self.operation.fatal = exc
            raise
        except Exception:
            self.operation.refuse('INDEX_FAILED', 'compiled write')

    def delete(self, condition, index, kb_id):
        self.check()
        if index != self.scope.index or kb_id != self.scope.bot_id or self.artifacts is None:
            self.operation.refuse(stage='compiled delete routing')
        try:
            return self.artifacts.delete(condition)
        except EngineError as exc:
            self.operation.fatal = exc
            raise
        except Exception:
            self.operation.refuse('INDEX_FAILED', 'compiled delete')

    def index_exist(self, index, kb_id):
        self.check()
        if index != self.scope.index or kb_id != self.scope.bot_id:
            self.operation.refuse(stage='index existence routing')
        return bool(self.backend.ready_sources(self.scope))

    def update(self, condition, values, index, kb_id):
        self.check()
        if index != self.scope.index or kb_id != self.scope.bot_id or self.artifacts is None:
            self.operation.refuse(stage='compiled update routing')
        try:
            return self.artifacts.update(condition, values)
        except EngineError as exc:
            self.operation.fatal = exc
            raise
        except Exception:
            self.operation.refuse('INDEX_FAILED', 'compiled update')

    def get(self, *args, **kwargs):
        try:
            if self.artifacts is not None:
                cid, index, kb_ids = args
                if index != self.scope.index or kb_ids != [self.scope.bot_id]:
                    self.operation.refuse(stage='compiled ID routing')
                if cid in self.artifacts.rows:
                    hits = self.artifacts.search([], [], {'id': [cid]}, [], OrderByExpr(), 0, 1)['hits']['hits']
                    return hits[0]['_source'] if hits else None
                if self.artifacts.writable:
                    return None
            return super().get(*args, **kwargs)
        except EngineError as exc:
            if self.operation:
                self.operation.fatal = exc
            raise


class ScopedCatalog:
    """Authorized document catalogue derived from READY indexed rows, no application ORM."""
    def __init__(self, store, parser_config=None):
        self.store = store
        self.parser_config = copy.deepcopy(parser_config or {})

    def knowledgebases(self):
        self.store.check()
        return [SimpleNamespace(id=self.store.scope.bot_id, tenant_id=self.store.scope.key,
                                parser_config=copy.deepcopy(self.parser_config))]

    def documents(self):
        self.store.check()
        scope = self.store.scope
        ready = self.store.backend.ready_sources(scope)
        # Names are fetched through the same scope boundary; no title/metadata
        # catalog may inspect an inactive or unauthorized document.
        result = self.store.search(['docnm_kwd'], [], {}, [], OrderByExpr(), 0, 10000,
                                   [scope.index], [scope.bot_id])
        if result['hits']['total']['value'] > 10000:
            self.store.operation.refuse('CAPACITY_EXCEEDED', 'document catalog bound')
        names = {row['_source']['doc_id']: row['_source'].get('docnm_kwd', '')
                 for row in result['hits']['hits']}
        return [SimpleNamespace(id=s.document_id, name=names.get(s.document_id, ''), kb_id=scope.bot_id)
                for s in scope.sources if s.key in ready
                and (self.store.document_ids is None or s.document_id in self.store.document_ids)]

    def disabled_documents(self):
        ready = self.store.backend.ready_sources(self.store.scope)
        return [s.document_id for s in self.store.scope.sources if s.key not in ready]

    def flattened_metadata(self):
        scope = self.store.scope
        # Same flattened representation as pinned DocMetadataService, but rows
        # come from our READY/version-scoped store instead of an unscoped ORM.
        result = self.store.search(['meta_fields_kwd', 'metadata_sha_kwd'], [], {}, [], OrderByExpr(),
                                   0, 10000, [scope.index], [scope.bot_id])
        if result['hits']['total']['value'] > 10000:
            self.store.operation.refuse('CAPACITY_EXCEEDED', 'metadata development catalog bound')
        documents = {}
        for hit in result['hits']['hits']:
            row = hit['_source']
            if not row.get('meta_fields_kwd'):
                continue
            raw = row['meta_fields_kwd']
            if hashlib.sha256(raw.encode()).hexdigest() != row.get('metadata_sha_kwd'):
                self.store.operation.refuse('PROVENANCE_FAILED', 'document metadata')
            if row['doc_id'] in documents and documents[row['doc_id']] != raw:
                self.store.operation.refuse('PROVENANCE_FAILED', 'inconsistent document metadata')
            documents[row['doc_id']] = raw
        meta = {}
        for doc_id, raw in documents.items():
            for key, value in json.loads(raw).items():
                values = value if isinstance(value, list) else [value]
                for item in values:
                    if item is not None:
                        meta.setdefault(key, {}).setdefault(str(item), []).append(doc_id)
        return meta

    def filter_metadata(self, conditions, logic):
        from .upstream.metadata_utils import meta_filter
        return meta_filter(self.flattened_metadata(), conditions, logic)


def operation_for(engine, scope, document_ids=None, artifact_kind=None):
    engine._scope(scope)
    store = AdvancedScopedStore(engine.backend, scope, engine.still_authorized)
    if document_ids is not None:
        if not set(document_ids).issubset({s.document_id for s in scope.sources}):
            raise EngineError('UNAUTHORIZED_SCOPE', 'requested documents')
        store.document_ids = frozenset(document_ids)
    op = FullOperation(scope, store, Dealer(store, queryer=engine.queryer), ScopedCatalog(store))
    store.operation = op
    if artifact_kind is not None:
        from .artifacts import ArtifactSession, ElasticsearchArtifactIO
        io = getattr(engine, 'artifact_io', None) or ElasticsearchArtifactIO(engine.backend)
        store.artifacts = ArtifactSession.open(store, io, artifact_kind)
    return op


def exact_evidence(op, chunk):
    cid = str(chunk.get('chunk_id') or chunk.get('id') or '')
    row = op.store.seen.get(cid)
    if row is None:
        op.refuse('PROVENANCE_FAILED', 'agentic unobserved citation')
    op.store.validate_row(row, op.store.auxiliary_ids.get(cid))
    # Agentic narrowing is an upstream context operation, not replacement of
    # the original source. Citations retain the exact observed supporting row.
    return Evidence(cid, row['source_id'], row['doc_id'], row['version_kwd'], op.scope.generation,
                    op.scope.key, row['content_with_weight'], row['content_sha_kwd'],
                    row['docnm_kwd'], row['url_kwd'], int(row['chunk_order_int']),
                    float(chunk.get('similarity') or 0), float(chunk.get('term_similarity') or 0),
                    float(chunk.get('vector_similarity') or 0), 'ragflow_agentic',
                    {'generated': False, 'upstream_excerpt': str(chunk.get('content_with_weight') or chunk.get('content') or '')})


async def research(engine, scope, query, *, thinking_mode='medium', messages=None, document_ids=None, artifact_kind=None):
    from .engine import CheckedEmbeddings
    from .upstream.advanced_rag.agentic_rag import RAGTools
    from .upstream.advanced_rag.agentic_rag_graph import run_agentic_rag
    from .upstream.advanced_rag.harness.config import THINKING_MODES
    if thinking_mode not in THINKING_MODES:
        raise EngineError('MODE_UNAVAILABLE', 'explicit thinking mode required')
    if not isinstance(query, str) or not query.strip() or len(query) > 16384:
        raise EngineError('RETRIEVAL_FAILED', 'query bounds')
    op = operation_for(engine, scope, document_ids, artifact_kind)
    # Validate history as data; it never contributes authority or system prompts.
    history = copy.deepcopy(messages or [])
    if len(history) > 64 or any(not isinstance(m, dict) or m.get('role') not in {'user', 'assistant'}
                               or not isinstance(m.get('content'), str) for m in history):
        raise EngineError('RETRIEVAL_FAILED', 'history bounds')
    if sum(len(m['content']) for m in history) > 131072:
        raise EngineError('RETRIEVAL_FAILED', 'history bounds')
    if not history or history[-1] != {'role': 'user', 'content': query}:
        history.append({'role': 'user', 'content': query})
    if document_ids == [] or not scope.sources:
        return {'answer': '', 'evidence': [], 'mode': thinking_mode, 'verdict': None, 'usage': {}}
    with full_operation(op), model_operation(scope):
        model = AuthorizedChatModel(engine.chat_model, op.check)
        if thinking_mode != 'low' and not callable(getattr(engine.chat_model, 'async_completion', None)):
            raise EngineError('CHAT_MODEL_UNAVAILABLE', 'native tool interface required')
        tools = RAGTools([scope.key], model, CheckedEmbeddings(engine.embedding, scope),
                         kbs=op.catalog.knowledgebases(),
                         doc_scope=document_ids if document_ids is not None else [s.document_id for s in scope.sources],
                         thinking_mode=thinking_mode, original_user_question=query,
                         similarity_threshold=engine.config.similarity_threshold,
                         vector_similarity_weight=engine.config.vector_weight,
                         top_n=12, rerank_candidates_count=engine.config.candidates,
                         top_k=engine.config.knn_top_k)
        op.tools = tools
        answer = []
        # Buffer until every source/tool result is revalidated. Never stream a
        # partial answer past a scope violation caught inside upstream code.
        async for token in run_agentic_rag(tools, history):
            op.check()
            answer.append(str(token))
        from .modes import generated_records, supporting_evidence
        artifacts = op.store.artifacts
        generated = generated_records(op) if artifacts is not None else []
        evidence = [exact_evidence(op, c) for c in tools.kbinfos.get('chunks', [])
                    if artifacts is None or c.get('chunk_id') not in artifacts.rows]
        known = {e.chunk_id for e in evidence}
        evidence += [e for e in supporting_evidence(op, generated) if e.chunk_id not in known]
        # Keep the pinned final-answer [ID:n] pool order. Supporting leaf
        # expansion is a separate provenance inventory, not a renumbering.
        citation_pool = [{'upstream_id': index, 'chunk_id': c.get('chunk_id'),
                          'generated': bool(artifacts and c.get('chunk_id') in artifacts.rows)}
                         for index, c in enumerate(tools.kbinfos.get('chunks', []))]
        op.check()
        return {'answer': ''.join(answer), 'evidence': evidence, 'mode': thinking_mode,
                'generated_artifacts': generated,
                'citation_pool': citation_pool,
                'verdict': copy.deepcopy(tools._rag_verdict), 'usage': tools.llm_stats.snapshot()}
