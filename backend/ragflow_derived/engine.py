"""RAGFlow-derived ingestion/retrieval/context orchestration, separate from platform routing."""
from dataclasses import dataclass
import hashlib
import json
import math
import asyncio
import copy
import re
import numpy as np
from .contracts import AuthorizedScope, EngineError, Evidence, safe_url
from .parsing import parse
from .storage import ScopedStore, SourceRegistry
from .upstream.embedding_utils import EmbeddingUtils
from .upstream.query import FulltextQueryer
from .upstream.search import Dealer
from .upstream.context import kb_prompt
from .upstream.runtime import native_tokenizer, num_tokens_from_string
from .model_runtime import AuthorizedChatModel, model_operation
from .orchestration import QueryOptions, prepare_query
from .observation import record, observe_dealer


@dataclass(frozen=True)
class EngineConfig:
    chunk_tokens: int = 512
    candidates: int = 64
    vector_weight: float = 0.3
    similarity_threshold: float = 0.2
    knn_top_k: int = 1024
    knn_num_candidates: int = 2048
    context_tokens: int = 8192
    context_bytes: int = 131072
    context_units: int = 48
    reranker_required: bool = False

    def __post_init__(self):
        if not (1 <= self.chunk_tokens <= 8192 and 1 <= self.candidates <= 1024
                and 0 <= self.vector_weight <= 1 and 0 <= self.similarity_threshold <= 1
                and self.candidates <= self.knn_top_k <= self.knn_num_candidates <= 10000
                and 1 <= self.context_tokens <= 32768 and 1 <= self.context_bytes <= 131072
                and 1 <= self.context_units <= 48):
            raise ValueError("Invalid bounded engine configuration")


def _model_failure(code, stage):
    from .full_runtime import _operation
    error = EngineError(code, stage)
    op = _operation.get()
    if op is not None:
        op.fatal = error
    raise error from None


class CheckedEmbeddings:
    def __init__(self, model, scope):
        if model is None or model.profile != scope.embedding_profile or model.dimension != scope.dimension:
            raise EngineError("EMBEDDING_UNAVAILABLE", "profile")
        self.model, self.dimension = model, scope.dimension
        self.llm_name = scope.embedding_profile

    def _check(self, values, count):
        a = np.asarray(values, dtype=float)
        if a.shape != (count, self.dimension) or not np.all(np.isfinite(a)) or np.any(np.linalg.norm(a, axis=1) == 0):
            _model_failure("EMBEDDING_UNAVAILABLE", "invalid vectors")
        return a

    def encode(self, texts):
        try:
            values, tokens = self.model.encode(texts)
            return self._check(values, len(texts)), tokens
        except EngineError as exc:
            _model_failure(exc.code, exc.stage)
        except Exception:
            _model_failure("EMBEDDING_UNAVAILABLE", "encode")

    def encode_queries(self, question):
        try:
            vector, tokens = self.model.encode_queries(question)
            return self._check([vector], 1)[0].tolist(), tokens
        except EngineError as exc:
            _model_failure(exc.code, exc.stage)
        except Exception:
            _model_failure("EMBEDDING_UNAVAILABLE", "query")


class CheckedReranker:
    def __init__(self, model):
        self.model = model

    def similarity(self, query, docs):
        try:
            scores, usage = self.model.similarity(query, docs)
            scores = np.asarray(scores, dtype=float)
            if scores.shape != (len(docs),) or not np.all(np.isfinite(scores)) or np.any(scores < 0) or np.any(scores > 1):
                raise ValueError("Invalid reranker output")
            return scores, usage
        except Exception:
            _model_failure("RERANKER_UNAVAILABLE", "rerank")


class RagFlowDerivedEngine:
    async def retrieve_mode(self, scope, query, *, mode, **kwargs):
        from .modes import navigate, graph_retrieve, raptor_retrieve
        routes = {'navigation': navigate, 'graph': graph_retrieve, 'raptor': raptor_retrieve}
        if mode not in routes:
            raise EngineError('MODE_UNAVAILABLE', 'explicit supported mode required')
        return await routes[mode](self, scope, query, **kwargs)

    async def compile(self, scope, *, kind, **kwargs):
        from .compilation import compile_artifacts
        return await compile_artifacts(self, scope, kind=kind, **kwargs)

    def __init__(self, backend, embedding, *, still_authorized, tokenizer=native_tokenizer,
                 synonyms=None, reranker=None, config=None, registry=None, count_tokens=num_tokens_from_string,
                 chat_model=None):
        self.backend, self.embedding = backend, embedding
        self.still_authorized, self.tokenizer = still_authorized, tokenizer
        self.reranker, self.config = reranker, config or EngineConfig()
        self.registry = registry or SourceRegistry()
        self.count_tokens = count_tokens
        self.queryer = FulltextQueryer(tokenizer, synonyms)
        self.chat_model = chat_model

    def _scope(self, scope):
        if not isinstance(scope, AuthorizedScope) or not self.still_authorized(scope):
            raise EngineError("UNAUTHORIZED_SCOPE", "authority")
        return ScopedStore(self.backend, scope, self.still_authorized)

    def ingest(self, scope, source_id, content, *, kind="txt", title="", url="",
               child_delimiters=(), auto_keywords=0, auto_questions=0, generate_toc=False,
               metadata=None, tags=()):
        store = self._scope(scope)
        source = scope.source(source_id)
        metadata = copy.deepcopy(metadata or {})
        if (not isinstance(metadata, dict) or len(metadata) > 64 or len(tags) > 32
                or any(not isinstance(k, str) or len(k) > 128 for k in metadata)
                or any(not isinstance(t, str) or not 1 <= len(t) <= 128 for t in tags)):
            raise EngineError('PARSER_FAILED', 'metadata bounds')
        try:
            meta_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError):
            raise EngineError('PARSER_FAILED', 'metadata values') from None
        if len(meta_json.encode()) > 16384:
            raise EngineError('PARSER_FAILED', 'metadata bytes')
        if (len(child_delimiters) > 8 or any(not isinstance(x, str) or not 1 <= len(x) <= 32 for x in child_delimiters)
                or not 0 <= auto_keywords <= 10 or not 0 <= auto_questions <= 10):
            raise EngineError("PARSER_FAILED", "structural options")
        model = AuthorizedChatModel(self.chat_model, store.check) if (auto_keywords or auto_questions or generate_toc) else None
        pieces = parse(content, kind, tokenizer=self.tokenizer, chunk_tokens=self.config.chunk_tokens,
                       count_tokens=self.count_tokens, filename=str(title)[:512] or "document")
        raw = content.encode() if isinstance(content, str) else content
        digest = hashlib.sha256(raw).hexdigest()
        rows = []
        for piece in pieces:
            text = piece["text"]
            text_hash = hashlib.sha256(text.encode()).hexdigest()
            cid = hashlib.sha256(json.dumps([scope.key, source.key, piece["order"], text_hash]).encode()).hexdigest()
            row = {"id": cid, "kb_id": scope.bot_id, "scope_key_kwd": scope.key,
                   "source_version_kwd": source.key, "source_id": source.source_id,
                   "doc_id": source.document_id, "version_kwd": source.version, "generation_kwd": scope.generation,
                   "artifact_sha_kwd": digest, "content_sha_kwd": text_hash, "available_int": 1,
                   "docnm_kwd": str(title)[:512], "url_kwd": safe_url(url),
                   "content_with_weight": text, "content_ltks": self.tokenizer.tokenize(text),
                   "title_tks": self.tokenizer.tokenize(str(title)[:512]),
                   "chunk_order_int": piece["order"], "structure_kwd": json.dumps(piece["headings"]),
                   "source_type_kwd": kind,
                   "doc_type_kwd": piece["kind"]}
            if piece.get("parser_metadata"):
                row["parser_metadata_kwd"] = json.dumps(piece["parser_metadata"], ensure_ascii=False)
            if metadata:
                row['meta_fields_kwd'] = meta_json
                row['metadata_sha_kwd'] = hashlib.sha256(meta_json.encode()).hexdigest()
            if tags:
                row['tag_kwd'] = list(tags)
            row["content_sm_ltks"] = self.tokenizer.fine_grained_tokenize(row["content_ltks"])
            rows.append(row)
        parents = {}
        if child_delimiters:
            from .upstream.structure import split_with_pattern
            children = []
            pattern = "|".join(re.escape(x) for x in child_delimiters)
            for row in rows:
                parent = copy.deepcopy(row)
                parent.update(available_int=0, artifact_role_kwd="parent")
                # Same source/version/generation identity is part of every ID.
                parent["id"] = hashlib.sha256((scope.key + source.key + "parent" + parent["content_with_weight"]).encode()).hexdigest()
                parents[parent["id"]] = parent
                for child in split_with_pattern(row, pattern, row["content_with_weight"], True, tokenizer=self.tokenizer):
                    child["content_sha_kwd"] = hashlib.sha256(child["content_with_weight"].encode()).hexdigest()
                    child["id"] = hashlib.sha256(json.dumps([scope.key, source.key, len(children), child["content_sha_kwd"]]).encode()).hexdigest()
                    child["chunk_order_int"] = len(children)
                    child["mom_id"] = parent["id"]
                    children.append(child)
            rows = children
        if model:
            from .upstream.prompts.generator import keyword_extraction, question_proposal
            from .upstream.structure import build_toc
            async def enrich():
                with model_operation(scope):
                    for row in rows:
                        if auto_keywords:
                            kwd = await keyword_extraction(model, row["content_with_weight"], auto_keywords)
                            row["important_kwd"] = [k for k in re.split(r"[,，;；、\r\n]+", kwd) if k.strip()]
                            row["important_tks"] = self.tokenizer.tokenize(" ".join(row["important_kwd"]))
                        if auto_questions:
                            questions = await question_proposal(model, row["content_with_weight"], auto_questions)
                            row["question_kwd"] = questions.split("\n")
                            row["question_tks"] = self.tokenizer.tokenize("\n".join(row["question_kwd"]))
                    return await build_toc(rows, model) if generate_toc else None
            toc = asyncio.run(enrich())
            if toc:
                # Derived TOC is auxiliary, not verbatim source evidence. Every
                # model-emitted leaf must reference a child in this one version.
                allowed_ids = {r["id"] for r in rows}
                items = json.loads(toc["content_with_weight"])
                if any(not set(item.get("ids", [])).issubset(allowed_ids) for item in items):
                    raise EngineError("PROVENANCE_FAILED", "TOC leaf identity")
                toc.update(artifact_role_kwd="toc", available_int=0)
                toc["content_sha_kwd"] = hashlib.sha256(toc["content_with_weight"].encode()).hexdigest()
                toc["id"] = hashlib.sha256((scope.key + source.key + "toc" + toc["content_sha_kwd"]).encode()).hexdigest()
                parents[toc["id"]] = toc
        checked = CheckedEmbeddings(self.embedding, scope)
        titles, texts = EmbeddingUtils.prepare_texts_for_embedding(rows)
        cv, _ = checked.encode(texts)
        tv, _ = checked.encode(titles)
        combined = EmbeddingUtils.combine_title_content_vectors(tv, cv)
        checked._check(combined, len(rows))
        EmbeddingUtils.attach_vectors(rows, combined)
        rows.extend(parents.values())
        store.check()
        # Content and parser/title configuration must stay immutable within a
        # source version, including across process restarts.
        identity = [digest, self.config.chunk_tokens, kind,
                    [row["id"] for row in rows], str(title)[:512], safe_url(url)]
        if child_delimiters or auto_keywords or auto_questions or generate_toc:
            identity.extend([list(child_delimiters), auto_keywords, auto_questions, generate_toc,
                [{k: r[k] for k in ("important_kwd", "question_kwd") if k in r} for r in rows]])
        if metadata or tags:
            identity.extend([meta_json, list(tags)])
        index_digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        try:
            with self.registry.lock:
                key = self.registry.register(scope, source, index_digest)
                self.backend.claim_source(scope, source, index_digest)
                self.backend.replace(scope, source, rows)
                self.registry._digests[key] = index_digest
            store.check()
        except EngineError:
            raise
        except Exception:
            raise EngineError("INDEX_FAILED", "write") from None
        return {"source_id": source.source_id, "version": source.version, "chunks": len(rows), "digest": digest}

    def update_source(self, scope, source_id, content, **kwargs):
        # A different digest requires a new server-issued version, never an in-place rewrite.
        return self.ingest(scope, source_id, content, **kwargs)

    async def research(self, scope, query, **kwargs):
        from .advanced import research
        return await research(self, scope, query, **kwargs)

    def delete_source(self, scope, source_id):
        store = self._scope(scope)
        source = scope.source(source_id)
        try:
            self.backend.delete(scope, source)
            store.check()
        except EngineError:
            raise
        except Exception:
            raise EngineError("INDEX_FAILED", "delete") from None

    async def retrieve(self, scope, query, *, top_k=12, document_ids=None, messages=None, options=None,
                       metadata_filter=None, use_tags=False):
        store = self._scope(scope)
        record("query_scope", original_query=query, organization_id=scope.organization_id,
               bot_id=scope.bot_id, generation=scope.generation, scope_key=scope.key,
               sources=[{"source_id": s.source_id, "document_id": s.document_id, "version": s.version,
                         "source_version_key": s.key} for s in scope.sources], document_ids=document_ids)
        if not isinstance(query, str) or not query.strip() or len(query) > 16384:
            raise EngineError("RETRIEVAL_FAILED", "query bounds")
        if not 1 <= top_k <= min(self.config.candidates, 48):
            raise EngineError("RETRIEVAL_FAILED", "top_k")
        if document_ids is not None:
            permitted = {s.document_id for s in scope.sources}
            if not set(document_ids).issubset(permitted):
                raise EngineError("UNAUTHORIZED_SCOPE", "requested documents")
            if not document_ids:
                return []
            store.document_ids = frozenset(document_ids)
        options = options or QueryOptions()
        rank_feature = None
        if metadata_filter or use_tags:
            from .advanced import operation_for
            from .full_runtime import full_operation
            from .upstream.metadata_utils import apply_meta_data_filter
            op = operation_for(self, scope, document_ids)
            store = op.store
            with full_operation(op), model_operation(scope):
                if metadata_filter:
                    filter_model = (AuthorizedChatModel(self.chat_model, op.check)
                                    if metadata_filter.get('method') in {'auto', 'semi_auto'} else None)
                    selected = await apply_meta_data_filter(metadata_filter, question=query, chat_mdl=filter_model,
                        kb_ids=[scope.bot_id], metas_loader=op.catalog.flattened_metadata)
                    if selected == ['-999'] or selected == []:
                        return []
                    if selected is not None:
                        permitted = {s.document_id for s in scope.sources}
                        if document_ids is not None:
                            permitted &= set(document_ids)
                        if not set(selected).issubset(permitted):
                            op.refuse(stage='metadata document result')
                        document_ids = selected
                        store.document_ids = frozenset(selected)
                if use_tags:
                    all_tags = op.retriever.all_tags_in_portion(scope.key, [scope.bot_id])
                    rank_feature = op.retriever.tag_query(query, [scope.key], [scope.bot_id], all_tags)
        needs_model = options.keyword or options.cross_languages or options.toc_enhance or (options.refine_multiturn and messages)
        model = AuthorizedChatModel(self.chat_model, store.check) if needs_model else None
        with model_operation(scope):
            query = await prepare_query(query, messages, options, model)
        record("prepared_query", query=query)
        if not isinstance(query, str) or not query.strip() or len(query) > 16384:
            raise EngineError("RETRIEVAL_FAILED", "prepared query bounds")
        if self.config.reranker_required and self.reranker is None:
            raise EngineError("RERANKER_UNAVAILABLE", "configuration")
        dealer = observe_dealer(Dealer(store, queryer=self.queryer), self.config.similarity_threshold)
        try:
            result = await dealer.retrieval(query, CheckedEmbeddings(self.embedding, scope), [scope.key],
                                            [scope.bot_id], 1, top_k,
                                            similarity_threshold=self.config.similarity_threshold,
                                            vector_similarity_weight=self.config.vector_weight,
                                            doc_ids=document_ids,
                                            rerank_mdl=CheckedReranker(self.reranker) if self.reranker else None,
                                            rank_feature=rank_feature, rerank_candidates_count=self.config.candidates,
                                            knn_top_k=self.config.knn_top_k,
                                            knn_num_candidates=self.config.knn_num_candidates)
            if options.toc_enhance:
                with model_operation(scope):
                    chunks = await dealer.retrieval_by_toc(query, result["chunks"], [scope.key], model, top_k)
                if chunks:
                    result["chunks"] = chunks
            result["chunks"] = dealer.retrieval_by_children(result["chunks"], [scope.key])
            store.check()
            evidence = []
            for chunk in result["chunks"]:
                row = store.seen[chunk["chunk_id"]]
                store.validate_row(row, store.auxiliary_ids.get(chunk["chunk_id"]))
                evidence.append(Evidence(chunk_id=chunk["chunk_id"], source_id=row["source_id"],
                    document_id=row["doc_id"], version=row["version_kwd"], generation=scope.generation,
                    scope_key=scope.key, text=row["content_with_weight"], text_sha256=row["content_sha_kwd"],
                    title=row["docnm_kwd"], url=row["url_kwd"], order=int(row["chunk_order_int"]),
                    similarity=chunk["similarity"], lexical_similarity=chunk["term_similarity"],
                    vector_similarity=chunk["vector_similarity"], channel="ragflow_es_hybrid",
                    metadata={"headings": tuple(json.loads(row["structure_kwd"]))}))
            return evidence
        except EngineError:
            raise
        except Exception:
            raise EngineError("RETRIEVAL_FAILED", "upstream") from None

    def build_context(self, scope, evidence):
        self._scope(scope)
        seen, unique = set(), []
        for item in evidence:
            source = scope.source(item.source_id)
            if (item.scope_key != scope.key or item.version != source.version
                    or item.document_id != source.document_id or item.generation != scope.generation):
                raise EngineError("UNAUTHORIZED_SCOPE", "context")
            if item.chunk_id not in seen:
                seen.add(item.chunk_id)
                unique.append(item)
        chunks = [{"chunk_id": e.citation_id, "content_with_weight": e.text,
                   "docnm_kwd": e.title, "url": e.url} for e in unique[:self.config.context_units]]
        rendered = kb_prompt({"chunks": chunks}, self.config.context_tokens, hash_id=True)
        # The upstream content-token guard does not count titles/IDs. Apply a final
        # whole-block guard including framing; no text truncation or token rewriting.
        selected, packed = [], []
        for item, block in zip(unique, rendered):
            candidate = packed + [block]
            payload = json.dumps({"untrusted_source_evidence": candidate}, ensure_ascii=False)
            if len(payload.encode()) > self.config.context_bytes or self.count_tokens(payload) > self.config.context_tokens:
                break
            packed.append(block)
            selected.append(item)
        self._scope(scope)
        # No framing may overflow an otherwise empty, very small budget.
        context = json.dumps({"untrusted_source_evidence": packed}, ensure_ascii=False) if packed else ""
        return {"context": context,
                "evidence": tuple(selected), "sources": [e.citation() for e in selected],
                "excluded_units": len(unique) - len(selected)}

    def close(self):
        self.backend.close()
