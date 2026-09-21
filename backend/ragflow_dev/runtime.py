"""Development orchestration/observability around the unchanged port."""
import asyncio
import hashlib
import threading
import time
from elasticsearch import Elasticsearch
from ragflow_derived.contracts import EngineError, SourceRef
from ragflow_derived.engine import RagFlowDerivedEngine, CheckedEmbeddings
from ragflow_derived.storage import ElasticsearchBackend, ScopedStore
from ragflow_derived.upstream.doc_store import MatchDenseExpr, OrderByExpr
from ragflow_derived.upstream.search import Dealer
from ragflow_derived.upstream.runtime import native_tokenizer, NativeSynonyms, num_tokens_from_string
from ragflow_derived.orchestration import QueryOptions
from ragflow_derived.model_runtime import AuthorizedChatModel
from .authority import Authority
from .config import PROFILE, DIMENSION, EMBED_MODEL, EMBED_REVISION, RERANK_MODEL, RERANK_REVISION
from .models import CpuModels


def hit_metadata(result):
    return [{"chunk_id": h["_id"], "source_id": h["_source"].get("source_id"),
             "document_id": h["_source"].get("doc_id"), "version": h["_source"].get("version_kwd"),
             "score": h.get("_score")} for h in result.get("hits", {}).get("hits", [])]


class TracedBackend(ElasticsearchBackend):
    def __init__(self, client, trace, fault=None):
        super().__init__(client)
        self.trace, self.fault = trace, fault

    def search(self, *args, **kwargs):
        if self.fault == "storage":
            raise EngineError("RETRIEVAL_FAILED", "injected storage outage")
        started = time.perf_counter()
        result = super().search(*args, **kwargs)
        self.trace.append({"expressions": [type(e).__name__ for e in args[3]],
                           "hits": hit_metadata(result), "milliseconds": (time.perf_counter() - started) * 1000})
        return result


class FailedEmbedding:
    """Explicit failure injection only; never the successful native path."""
    profile, dimension = PROFILE, DIMENSION

    def encode_queries(self, text):
        raise RuntimeError("CONTROLLED_EMBEDDING_FAILURE")


class FailedReranker:
    def similarity(self, query, docs):
        raise RuntimeError("CONTROLLED_RERANKER_FAILURE")


class Runtime:
    def __init__(self, settings, *, chat_model=None):
        # Explicit operator callback only; never discovers production credentials.
        from .chat import from_env
        self.chat_model = chat_model if chat_model is not None else from_env(settings.project_id)
        self.client = Elasticsearch(settings.es_url, request_timeout=20, max_retries=0, retry_on_timeout=False)
        info = self.client.info()
        if info["version"]["number"] != "8.11.3":
            raise RuntimeError("UNVALIDATED_ELASTICSEARCH_VERSION")
        self.es_version = info["version"]["number"]
        self.authority = Authority(self.client)
        self.authority.initialize()
        self.backend = ElasticsearchBackend(self.client)
        # One worker and serialization bound memory/CPU. ES CAS remains authoritative.
        self.lock = threading.RLock()
        self.synonyms = NativeSynonyms()
        first = native_tokenizer.tokenize("Library services include borrowing books.")
        if not first or first != native_tokenizer.tokenize("Library services include borrowing books."):
            raise RuntimeError("TOKENIZER_STARTUP_FAILED")
        self.synonyms.lookup("library")
        num_tokens_from_string(first)
        self.tokenizer_digest = hashlib.sha256(first.encode()).hexdigest()
        self.models = CpuModels()

    def engine(self, tenant, *, pending=False, rerank=True, trace=None, fault=None):
        trace = trace if trace is not None else {"backend": [], "reranker": []}
        backend = TracedBackend(self.client, trace["backend"], fault=fault)
        return RagFlowDerivedEngine(backend, FailedEmbedding() if fault == "embedding" else self.models.embedding,
            still_authorized=lambda scope: self.authority.authorized(tenant, scope, pending=pending),
            synonyms=self.synonyms, reranker=(FailedReranker() if fault == "reranker" else
                self.models.traced_reranker(trace["reranker"])) if rerank else None,
            chat_model=self.chat_model)

    def ingest(self, tenant, payload):
        started = time.perf_counter()
        with self.lock:
            if any(not 1 <= len(x) <= 32 for x in payload.child_delimiters):
                raise EngineError("PARSER_FAILED", "child delimiter bounds")
            if payload.auto_keywords or payload.auto_questions or payload.generate_toc:
                # Reject unavailable optional models BEFORE revoking the old version.
                AuthorizedChatModel(self.chat_model, lambda: None)
            scope, previous = self.authority.begin(tenant, payload.source_id, payload.expected_version)
            version = int(scope.sources[0].version)
            try:
                result = self.engine(tenant, pending=True).ingest(scope, payload.source_id,
                    payload.content, kind=payload.kind, title=payload.title, url=payload.url,
                    child_delimiters=payload.child_delimiters, auto_keywords=payload.auto_keywords,
                    auto_questions=payload.auto_questions, generate_toc=payload.generate_toc)
                # Old version already revoked by begin(); remove only its exact owned rows.
                if previous:
                    self.backend.delete(scope, SourceRef(payload.source_id, previous["document_id"], str(previous["version"])))
                self.authority.finish(tenant, payload.source_id, version, ready=True)
            except Exception:
                self.authority.finish(tenant, payload.source_id, version, ready=False)
                raise
            return dict(result, generation=scope.generation, embedding_profile=PROFILE,
                        dimension=DIMENSION, milliseconds=(time.perf_counter() - started) * 1000)

    def delete(self, tenant, source_id, expected_version):
        with self.lock:
            scope = self.authority.deactivate(tenant, source_id, expected_version)
            self.backend.delete(scope, scope.source(source_id))
            return {"source_id": source_id, "version": expected_version, "state": "deleted"}

    @staticmethod
    def check_assertions(scope, payload):
        for key in ("organization_id", "bot_id", "generation"):
            value = getattr(payload, key, None)
            if value is not None and value != getattr(scope, key):
                raise EngineError("UNAUTHORIZED_SCOPE", "scope assertion")
        for sid, version in payload.source_versions.items():
            if scope.source(sid).version != str(version):
                raise EngineError("STALE_VERSION", "retrieval version")

    def retrieve(self, tenant, payload, *, fault=None):
        with self.lock:
            return asyncio.run(self._retrieve(tenant, payload, fault=fault))

    async def _retrieve(self, tenant, payload, *, fault=None):
        started = time.perf_counter()
        scope = self.authority.active_scope(tenant)
        self.check_assertions(scope, payload)
        trace = {"backend": [], "reranker": []}
        engine = self.engine(tenant, rerank=payload.rerank, trace=trace, fault=fault)
        options = QueryOptions(**payload.options.model_dump())
        messages = [m.model_dump() for m in payload.messages]
        if options.keyword or options.cross_languages or options.toc_enhance or (options.refine_multiturn and messages):
            AuthorizedChatModel(self.chat_model, lambda: None)
        lexical, vector, unranked = [], [], []
        if payload.trace and not fault and payload.document_ids != []:
            store = ScopedStore(engine.backend, scope, engine.still_authorized)
            if payload.document_ids is not None and not set(payload.document_ids).issubset({s.document_id for s in scope.sources}):
                raise EngineError("UNAUTHORIZED_SCOPE", "requested documents")
            # Diagnostic channels are separately labelled, not a substitute ranking/fusion algorithm.
            dealer = Dealer(store, queryer=engine.queryer)
            result = await dealer.search({"question": payload.query, "size": 64, "page": 1,
                "doc_ids": payload.document_ids, "available_int": 1}, [scope.index], [scope.bot_id], emb_mdl=None)
            lexical = [{"chunk_id": cid, "source_id": store.seen[cid]["source_id"],
                        "score": result.field[cid].get("_score")} for cid in result.ids]
            qvec, _ = CheckedEmbeddings(self.models.embedding, scope).encode_queries(payload.query)
            expr = MatchDenseExpr("q_384_vec", qvec, "float", "cosine", 1024,
                                  {"similarity": 0.1, "num_candidates": 2048})
            condition = {"doc_id": payload.document_ids} if payload.document_ids is not None else {}
            raw = store.search([], [], condition, [expr], OrderByExpr(), 0, 64, [scope.index], [scope.bot_id])
            vector = hit_metadata(raw)
            if payload.rerank:
                no_rerank = self.engine(tenant, rerank=False)
                unranked = await no_rerank.retrieve(scope, payload.query, top_k=payload.top_k,
                                                  document_ids=payload.document_ids)
        trace["backend"].clear()  # Following records are the actual final hybrid lane only.
        evidence = await engine.retrieve(scope, payload.query, top_k=payload.top_k, document_ids=payload.document_ids,
                                        messages=messages, options=options)
        pack = engine.build_context(scope, evidence)
        engine._scope(scope)
        serialized = [dict(e.citation(), text=e.text, scope_key=e.scope_key, generation=e.generation,
            similarity=e.similarity, lexical_similarity=e.lexical_similarity,
            vector_or_model_similarity=e.vector_similarity) for e in pack["evidence"]]
        return {"engine": "ragflow-derived", "organization_id": scope.organization_id, "bot_id": scope.bot_id,
            "generation": scope.generation, "context": pack["context"], "evidence": serialized,
            "citations": pack["sources"], "context_bytes": len(pack["context"].encode()),
            "context_tokens": num_tokens_from_string(pack["context"]), "units": len(serialized),
            "excluded_units": pack["excluded_units"], "milliseconds": (time.perf_counter() - started) * 1000,
            "trace": {"lexical_candidates": lexical, "vector_candidates": vector,
                "hybrid_calls": trace["backend"],
                "without_reranker_order": [e.chunk_id for e in unranked],
                "pre_rerank_order": next(([h["chunk_id"] for h in call["hits"]]
                    for call in reversed(trace["backend"]) if "MatchDenseExpr" in call["expressions"]), []),
                "post_rerank_order": [e.chunk_id for e in evidence], "real_reranker": trace["reranker"],
                "diagnostic_channel_query": "original_query_not_model_prepared",
                "query_options": payload.options.model_dump(),
                "old_engine_used": False, "test_doubles": bool(fault)} if payload.trace else None}

    def status(self, tenant):
        with self.lock:
            data = self.authority.read(tenant)["_source"]
            scope = self.authority.active_scope(tenant)
            stats = self.client.indices.stats(index=scope.index, metric="docs,store") if self.client.indices.exists(index=scope.index) else {}
            return dict(data, index=scope.index, index_stats=stats.get("_all", {}))

    def health(self):
        try:
            healthy = self.client.cluster.health(timeout="3s")["status"] in ("green", "yellow")
        except Exception:
            healthy = False
        return {"healthy": healthy, "engine": "ragflow-derived", "backend": "healthy",
            "elasticsearch": "healthy" if healthy else "unavailable", "elasticsearch_version": self.es_version,
            "tokenizer": "healthy", "tokenizer_implementation": "infinity-sdk-0.7.3.RagTokenizer",
            "tokenizer_smoke_sha256": self.tokenizer_digest, "embedding": "healthy", "reranker": "healthy",
            "embedding_model": EMBED_MODEL, "embedding_revision": EMBED_REVISION, "dimension": DIMENSION,
            "reranker_model": RERANK_MODEL, "reranker_revision": RERANK_REVISION, "runtime": "cpu",
            "upstream_components": {"parent_child": "available", "query_helpers": "integrated",
                "toc": "integrated_model_gated", "chat_callback": "configured" if self.chat_model else "unavailable",
                "chat_model": getattr(self.chat_model, "llm_name", None),
                "chat_calls": getattr(self.chat_model, "calls", 0), "chat_tokens": getattr(self.chat_model, "tokens", 0),
                "chat_failures": getattr(self.chat_model, "failures", 0),
                "agentic_executor": "not_integrated", "graph": "not_integrated", "raptor": "not_integrated"},
            "old_engine_used": False, "test_doubles": False}

    def close(self):
        self.client.close()
        if self.chat_model and callable(getattr(self.chat_model, "close", None)):
            self.chat_model.close()
