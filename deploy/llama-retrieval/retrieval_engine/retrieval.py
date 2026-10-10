"""Local retrieval using maintained LlamaIndex components.

Algorithms are supplied by VectorStoreIndex, BM25Retriever,
QueryFusionRetriever, SentenceSplitter and SentenceTransformerRerank.
This module handles local persistence, input limits and source provenance.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import threading
import time
from collections import Counter
from importlib.metadata import version
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import RetrievalConfig
from .model_runtime import ModelRuntime


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _node_id(index: int, document: Any) -> str:
    return hashlib.sha256(f"{document.id_}:{index}".encode("utf-8")).hexdigest()


def _model_projection(raw):
    from .document_nodes import model_text
    node = raw.model_copy(deep=True)
    node.text = model_text(raw)
    node.excluded_embed_metadata_keys = list(node.metadata)
    node.excluded_llm_metadata_keys = list(node.metadata)
    return node


def _wants_document_discovery(question: str, broad_discovery: bool) -> bool:
    """Catalog/overview only: generic option lists regressed in the ablation."""
    return bool(re.search(
        r'\b(?:catalog(?:ue)?|product range|service range|overview)\b|'
        r'\b(?:what|which)\b.*\b(?:sell|sells|selling|offer|offers)\b',
        question, flags=re.I,
    ))


def _merge_discovered_candidates(global_ranked, detail_groups, max_candidates, discovery_slots):
    """Reserve global hits, round-robin discovered detail, then global fallback."""
    selected, seen, origins = [], set(), {}
    slots = min(discovery_slots, max_candidates)

    def add(item, origin):
        fact = (item.node.metadata.get('subject_source_id', item.node.metadata['source_id']),
                ' '.join(item.node.text.split()))
        if fact in seen or len(selected) >= max_candidates:
            return False
        seen.add(fact)
        selected.append(item)
        origins[item.node.node_id] = origin
        return True

    for item in global_ranked:
        if len(selected) >= max_candidates - slots:
            break
        add(item, 'global')
    queues = {source: iter(items) for source, items in detail_groups.items()}
    supplied = 0
    while queues and supplied < slots:
        for source, queue in list(queues.items()):
            for item in queue:
                if add(item, 'document_discovery:' + source):
                    supplied += 1
                    break
            else:
                del queues[source]
            if supplied >= slots:
                break
    for item in global_ranked:
        add(item, 'global')
    return selected, {'reserved_global_slots': max_candidates - slots, 'discovery_slot_cap': slots,
                      'discovery_slots_used': supplied, 'selected_origins': origins}


class LocalRetrievalEngine:
    """One corpus, local CPU embeddings/reranking, and no generative provider."""

    def __init__(self, config: RetrievalConfig | None = None, *, runtime: ModelRuntime | None = None) -> None:
        self.config = config or RetrievalConfig()
        self.runtime = runtime or ModelRuntime(self.config)
        if not self.runtime.compatible(self.config):
            raise ValueError('The model runtime configuration does not match this corpus engine.')
        self._lock = threading.RLock()
        self._state = "not_loaded"
        self._manifest: dict[str, Any] = {}
        self._documents: dict[str, Any] = {}
        self._fusion = None
        self._reranker = None
        self._embedding = None
        self._tokenizer = None
        self._embedding_tokenizer = None
        self._context_tokenizer = None
        self._load_ms: float | None = None
        self._pipeline_artifacts: dict[str, Any] = {}
        self._source_nodes: dict[str, Any] = {}
        self._model_nodes: dict[str, Any] = {}
        self._scoped: dict[str, Any] = {}
        self._primary: dict[str, Any] = {}
        self._discovery = None
        self._targeted_discovery = None
        self._discovery_summaries = {}
        self._discovery_manifest: dict[str, Any] = {}
        self._exclusion_titles: tuple[str, ...] = ()

    def pipeline_provenance(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "retrieval": "LlamaIndex VectorStoreIndex + BM25Retriever",
            "fusion": "QueryFusionRetriever reciprocal-rank fusion",
            "generated_queries": 0,
            "parser": "LlamaIndex MarkdownNodeParser + SentenceSplitter, exact source adapter",
            "candidate_selection": "bounded pairs; hybrid search; explicit subject comparison scopes",
            "evidence_selection": "Haystack MMR within query groups; balanced subject round-robin",
            "subject_attribution": "known corpus URLs in linked headings; original citation origin retained",
            "comparison_filter": "source_id and subject_source_id both match the requested page",
            "broad_diversity_strength": .45,
            "broad_source_penalty": .10,
            "retriever_top_k": self.config.retriever_top_k,
            "embedding": self.config.embedding_model,
            "embedding_query_prefix": self.config.embedding_query_prefix,
            "reranker": "SentenceTransformerRerank",
            "reranker_model": self.config.reranker_model,
            "reranker_max_pair_tokens": 512,
            "rerank_candidates": self.config.rerank_candidates,
            "reranker_batch_size": self.config.reranker_batch_size,
            "adaptive_evidence": self.config.adaptive_evidence,
            "comparison_pair_cap": min(self.config.retriever_top_k * 2, max(self.config.rerank_candidates, 96)) if self.config.adaptive_evidence else self.config.rerank_candidates,
            "adaptive_core_cap": max(self.config.evidence_top_k, 16) if self.config.adaptive_evidence else self.config.evidence_top_k,
            "evidence_top_k": self.config.evidence_top_k,
            "context_token_budget": self.config.context_token_budget,
            "evidence_role_weight": self.config.evidence_role_weight,
            "primary_candidate_slots": self.config.primary_candidate_slots,
            "primary_candidate_policy": "broad discovery only; precise questions and named comparisons retain global/scoped candidate pools",
            "document_discovery_slots": self.config.document_discovery_slots,
            "document_discovery": "extractive summaries; overview routes up to4 sources; adaptive options rerank up to20 summaries and retain up to8 routes plus4 global subjects",
            "catalog_context": "retain up to3 scored original description anchors per routed document; remaining cores use MMR",
            "comparison_context": "reserve one scored native description when a requested subject lacks selected primary evidence; preserve existing duplicate-span representatives",
            "evidence_role_preference": "Haystack weighted RRF; optional, raw relevance margin retained",
            "context_tokenizer": "cl100k_base",
            "context_expansion": "up to three adjacent nodes, bounded128 tokens each, selected cores reserved",
            "chunk_tokens": self.config.chunk_tokens,
            "chunk_overlap": self.config.chunk_overlap,
            "max_query_tokens": self.config.max_query_tokens,
            "cpu_threads": self.config.cpu_threads,
            "device": "cpu",
            **self._pipeline_artifacts,
        }

    def status(self) -> dict[str, Any]:
        return {
            "state": self._state,
            "ready": self._state == "ready",
            "corpus": {
                "documents": self._manifest.get("document_count", 0),
                "nodes": self._manifest.get("node_count", 0),
                "sha256": self._manifest.get("corpus_sha256"),
            },
            "models": {
                "embedding": self.config.embedding_model,
                "reranker": self.config.reranker_model,
                "device": "cpu",
                "generative_llm": "disabled",
            },
            "pipeline": self.pipeline_provenance(),
            "load_ms": self._load_ms,
        }

    def _load_corpus(self) -> list[dict[str, Any]]:
        if not self.config.corpus_path.is_file():
            raise FileNotFoundError(f"Local corpus is missing: {self.config.corpus_path}")
        records = []
        seen = set()
        source_ids = set()
        with self.config.corpus_path.open(encoding="utf-8-sig") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                record = json.loads(line)
                for key in ("id", "source_id", "title", "url", "text"):
                    if not isinstance(record.get(key), str) or not record[key].strip():
                        raise ValueError(f"Corpus row {line_number} has an invalid {key}.")
                if record["id"] in seen:
                    raise ValueError(f"Duplicate corpus document: {record['id']}")
                if record["source_id"] in source_ids:
                    raise ValueError(f"Duplicate corpus source_id: {record['source_id']}")
                parsed_url = urlparse(record["url"])
                internal_document = record["url"] == f"document://{record['source_id']}"
                if (not internal_document and (parsed_url.scheme not in ("http", "https") or not parsed_url.hostname
                        or parsed_url.username is not None or parsed_url.password is not None
                        or any(ord(c)<32 or ord(c)==127 for c in record["url"]))):
                    raise ValueError(f"Corpus row {line_number} has an unsafe source URL.")
                seen.add(record["id"])
                source_ids.add(record["source_id"])
                records.append(record)
        if not records:
            raise ValueError("The local corpus is empty.")
        return records

    def build_or_load(self) -> dict[str, Any]:
        with self._lock, self.runtime.lock:
            if self._state == "ready":
                return self.status()
            started = time.perf_counter()
            try:
                self._build_or_load()
            except Exception:
                self._state = "error"
                raise
            self._load_ms = round((time.perf_counter() - started) * 1000, 2)
            self._state = "ready"
            return self.status()

    def _build_or_load(self) -> None:
        self._state = "loading_models"
        self.config.apply_runtime_environment()
        records = self._load_corpus()
        runtime = self.runtime.load()
        self._reranker = runtime.reranker
        self._tokenizer = runtime.tokenizer
        self._embedding = runtime.embedding
        self._embedding_tokenizer = runtime.embedding_tokenizer
        self._context_tokenizer = runtime.context_tokenizer
        disabled_llm = runtime.disabled_llm

        from llama_index.core import Document, StorageContext, VectorStoreIndex, load_index_from_storage
        from llama_index.core.retrievers import QueryFusionRetriever
        from llama_index.core.retrievers.fusion_retriever import FUSION_MODES
        from llama_index.core.schema import MetadataMode, TextNode
        from llama_index.core.vector_stores import MetadataFilter, MetadataFilters
        from llama_index.retrievers.bm25 import BM25Retriever
        from .document_nodes import build_nodes, has_textual_evidence, NODE_BUILDER_VERSION

        index_config = {
            "schema_version": 2,
            "node_builder": NODE_BUILDER_VERSION,
            "node_builder_sha256": _sha256_file(Path(__file__).with_name("document_nodes.py")),
            "evidence_roles_sha256": _sha256_file(Path(__file__).with_name("evidence_roles.py")),
            "model_projection_sha256": hashlib.sha256(inspect.getsource(_model_projection).encode()).hexdigest(),
            "corpus_sha256": _sha256_file(self.config.corpus_path),
            "embedding_model": self.config.embedding_model,
            "embedding_file_sha256": _sha256_file(
                self.config.embedding_path / "model_optimized.onnx"
            ),
            "reranker_model": self.config.reranker_model,
            "reranker_tokenizer_sha256": _json_hash(self._tokenizer.get_vocab()),
            "chunk_tokens": self.config.chunk_tokens,
            "chunk_overlap": self.config.chunk_overlap,
            "packages": {
                package: version(package)
                for package in (
                    "llama-index-core", "llama-index-retrievers-bm25",
                    "llama-index-embeddings-fastembed", "fastembed",
                    "sentence-transformers", "transformers", "markdown-it-py", "scikit-learn",
                )
            },
        }
        self._pipeline_artifacts = {
            "packages": index_config["packages"],
            "embedding_file_sha256": index_config["embedding_file_sha256"],
            "reranker_files_sha256": {
                path.name: _sha256_file(path)
                for path in sorted(self.config.reranker_path.iterdir())
                if path.is_file() and path.suffix in (".json", ".safetensors", ".bin", ".txt")
            },
            "runtime_source_sha256": {
                "retrieval.py": _sha256_file(Path(__file__)),
                "config.py": _sha256_file(Path(__file__).with_name("config.py")),
                "document_nodes.py": _sha256_file(Path(__file__).with_name("document_nodes.py")),
                "query_constraints.py": _sha256_file(Path(__file__).with_name("query_constraints.py")),
                "_vendor_flashtext.py": _sha256_file(Path(__file__).with_name("_vendor_flashtext.py")),
                "evidence_selection.py": _sha256_file(Path(__file__).with_name("evidence_selection.py")),
                "evidence_context.py": _sha256_file(Path(__file__).with_name("evidence_context.py")),
                "evidence_priority.py": _sha256_file(Path(__file__).with_name("evidence_priority.py")),
                "evidence_roles.py": _sha256_file(Path(__file__).with_name("evidence_roles.py")),
                "primary_candidates.py": _sha256_file(Path(__file__).with_name("primary_candidates.py")),
                "document_discovery.py": _sha256_file(Path(__file__).with_name("document_discovery.py")),
                "discovery_anchors.py": _sha256_file(Path(__file__).with_name("discovery_anchors.py")),
                "adaptive_evidence.py": _sha256_file(Path(__file__).with_name("adaptive_evidence.py")),
                "local_reranker.py": _sha256_file(Path(__file__).with_name("local_reranker.py")),
                "model_runtime.py": _sha256_file(Path(__file__).with_name("model_runtime.py")),
            },
        }
        index_directory = self.config.index_root / _json_hash(index_config)[:24]
        manifest_path = index_directory / "manifest.json"
        documents = []
        for record in records:
            metadata = dict(record.get("metadata") or {})
            metadata.update({
                "source_id": record["source_id"],
                "title": record["title"],
                "url": record["url"],
            })
            excluded = [key for key in metadata if key != "title"]
            document = Document(
                id_=record["id"],
                text=record["text"],
                metadata=metadata,
                excluded_embed_metadata_keys=excluded,
                excluded_llm_metadata_keys=excluded,
            )
            documents.append(document)
            self._documents[record["source_id"]] = record

        if manifest_path.is_file():
            self._state = "loading_index"
            self._manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            storage = StorageContext.from_defaults(persist_dir=str(index_directory / "vector"))
            index = load_index_from_storage(storage, embed_model=self._embedding)
            bm25 = BM25Retriever.from_persist_dir(str(index_directory / "bm25"))
            bm25.similarity_top_k = min(self.config.retriever_top_k, self._manifest["node_count"])
            self._source_nodes = {key:TextNode.from_dict(value) for key,value in
                json.loads((index_directory / "source_nodes.json").read_text(encoding="utf-8")).items()}
        else:
            self._state = "building_index"
            source_nodes = build_nodes(documents,
                tokenizer=lambda text: self._tokenizer.encode(text, add_special_tokens=False),
                chunk_tokens=self.config.chunk_tokens, chunk_overlap=self.config.chunk_overlap)
            self._source_nodes = {node.node_id:node for node in source_nodes}
            nodes = []
            for raw in source_nodes:
                if not has_textual_evidence(raw):
                    continue
                nodes.append(_model_projection(raw))
            max_embedding_tokens = 0
            max_passage_tokens = 0
            for node in nodes:
                content = node.get_content(metadata_mode=MetadataMode.EMBED)
                passage_length = len(self._tokenizer.encode(content, add_special_tokens=False))
                embedding_length = len(self._embedding_tokenizer.encode(content).ids)
                if passage_length + self.config.max_query_tokens + 3 > 512:
                    raise ValueError(f"Node {node.node_id} would be truncated by the reranker.")
                if embedding_length > 512:
                    raise ValueError(f"Node {node.node_id} would be truncated by the embedder.")
                if node.start_char_idx is None or node.end_char_idx is None:
                    raise ValueError(f"Node {node.node_id} has no verifiable source offsets.")
                source = self._documents[node.metadata["source_id"]]["text"]
                if source[node.start_char_idx:node.end_char_idx] != self._source_nodes[node.node_id].text:
                    raise ValueError(f"Node {node.node_id} does not match its source text.")
                max_embedding_tokens = max(max_embedding_tokens, embedding_length)
                max_passage_tokens = max(max_passage_tokens, passage_length)
            if not nodes:
                raise ValueError("The document parser produced no source nodes.")
            index = VectorStoreIndex(nodes, embed_model=self._embedding, show_progress=False)
            bm25 = BM25Retriever.from_defaults(
                nodes=nodes,
                similarity_top_k=min(self.config.retriever_top_k, len(nodes)),
                language="en",
                verbose=False,
            )
            index_directory.mkdir(parents=True, exist_ok=True)
            index.storage_context.persist(persist_dir=str(index_directory / "vector"))
            bm25.persist(str(index_directory / "bm25"))
            (index_directory / "source_nodes.json").write_text(json.dumps(
                {key:node.to_dict() for key,node in self._source_nodes.items()}, ensure_ascii=False), encoding="utf-8")
            self._manifest = {
                **index_config,
                "document_count": len(documents),
                "node_count": len(nodes),
                "max_embedding_tokens": max_embedding_tokens,
                "max_passage_tokens": max_passage_tokens,
                "index_id": index_directory.name,
            }
            manifest_path.write_text(
                json.dumps(self._manifest, indent=2, ensure_ascii=False), encoding="utf-8"
            )

        vector = index.as_retriever(similarity_top_k=min(
            self.config.retriever_top_k, self._manifest["node_count"]
        ))
        self._fusion = QueryFusionRetriever(
            [vector, bm25],
            llm=disabled_llm,
            num_queries=1,
            mode=FUSION_MODES.RECIPROCAL_RANK,
            similarity_top_k=min(self.config.retriever_top_k*2, self._manifest["node_count"]),
            use_async=False,
            verbose=False,
        )
        embeddings = index.vector_store.data.embedding_dict
        self._model_nodes = {node_id:index.docstore.get_node(node_id) for node_id in embeddings}
        for node_id,node in self._model_nodes.items():
            node.embedding = embeddings[node_id]
        self._exclusion_titles = tuple(dict.fromkeys(
            str(node.metadata.get('subject_title', '')) for node in self._source_nodes.values()
            if node.metadata.get('subject_title')
        ))
        from .primary_candidates import build_primary_lane
        self._primary['global'] = build_primary_lane(index,self._model_nodes,disabled_llm)
        for source_id in self._documents:
            source_nodes = [n for n in self._model_nodes.values()
                if n.metadata["source_id"] == source_id
                and n.metadata.get("subject_source_id", source_id) == source_id]
            if not source_nodes:
                continue
            self._primary[source_id] = build_primary_lane(index,self._model_nodes,disabled_llm,source_id=source_id)
            k = min(96 if self.config.adaptive_evidence else 32, len(source_nodes))
            scoped_vector = index.as_retriever(similarity_top_k=k,
                filters=MetadataFilters(filters=[MetadataFilter(key="source_id", value=source_id),
                    MetadataFilter(key="subject_source_id", value=source_id)]))
            scoped_bm25 = BM25Retriever.from_defaults(nodes=source_nodes, similarity_top_k=k, language="en", verbose=False)
            self._scoped[source_id] = QueryFusionRetriever([scoped_vector,scoped_bm25], llm=disabled_llm,
                num_queries=1, mode=FUSION_MODES.RECIPROCAL_RANK, similarity_top_k=k, use_async=False, verbose=False)

        if self.config.document_discovery_slots:
            self._build_or_load_discovery(documents, index_directory, disabled_llm)

    def _build_or_load_discovery(self, documents, index_directory, disabled_llm):
        """Persist optional summary embeddings separately; never replace detail nodes."""
        from llama_index.core import StorageContext, VectorStoreIndex, load_index_from_storage
        from llama_index.core.retrievers import QueryFusionRetriever
        from llama_index.core.retrievers.fusion_retriever import FUSION_MODES
        from llama_index.core.schema import MetadataMode
        from llama_index.retrievers.bm25 import BM25Retriever
        from .document_discovery import build_discovery_nodes, DISCOVERY_VERSION

        signature = {
            'version': DISCOVERY_VERSION, 'helper_sha256': _sha256_file(Path(__file__).with_name('document_discovery.py')),
            'parent_index_id': self._manifest['index_id'], 'corpus_sha256': self._manifest['corpus_sha256'],
            'embedding_file_sha256': self._pipeline_artifacts['embedding_file_sha256'],
            'summary_tokens': 256, 'max_headings': 10, 'max_description_tokens': 128,
            'packages': self._pipeline_artifacts['packages'],
        }
        directory = index_directory / 'discovery' / _json_hash(signature)[:24]
        manifest_path = directory / 'manifest.json'
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            storage = StorageContext.from_defaults(persist_dir=str(directory / 'vector'))
            index = load_index_from_storage(storage, embed_model=self._embedding)
            bm25 = BM25Retriever.from_persist_dir(str(directory / 'bm25'))
        else:
            summaries = build_discovery_nodes(documents, self._source_nodes,
                lambda text: self._tokenizer.encode(text, add_special_tokens=False), max_tokens=256)
            if not summaries:
                self._discovery_manifest = {'available': False, 'reason': 'no_summary_nodes'}
                return
            lengths = [len(self._embedding_tokenizer.encode(
                node.get_content(metadata_mode=MetadataMode.EMBED)).ids) for node in summaries]
            if max(lengths) > 512:
                raise ValueError('A document-discovery summary would be truncated by the embedder.')
            index = VectorStoreIndex(summaries, embed_model=self._embedding, show_progress=False)
            bm25 = BM25Retriever.from_defaults(nodes=summaries, similarity_top_k=min(8, len(summaries)),
                                               language='en', verbose=False)
            directory.mkdir(parents=True, exist_ok=True)
            index.storage_context.persist(persist_dir=str(directory / 'vector'))
            bm25.persist(str(directory / 'bm25'))
            manifest = {**signature, 'discovery_index_id': directory.name,
                        'summary_count': len(summaries), 'max_embedding_tokens': max(lengths)}
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        k = min(8, manifest['summary_count'])
        bm25.similarity_top_k = k
        self._discovery = QueryFusionRetriever([index.as_retriever(similarity_top_k=k), bm25],
            llm=disabled_llm, num_queries=1, mode=FUSION_MODES.RECIPROCAL_RANK,
            similarity_top_k=k, use_async=False, verbose=False)
        self._discovery_manifest = manifest
        self._pipeline_artifacts['document_discovery_index'] = manifest
        if self.config.adaptive_evidence:
            from copy import copy
            target_k = min(16, manifest['summary_count'])
            target_bm25 = copy(bm25)
            target_bm25.similarity_top_k = target_k
            self._targeted_discovery = QueryFusionRetriever(
                [index.as_retriever(similarity_top_k=target_k), target_bm25],
                llm=disabled_llm, num_queries=1, mode=FUSION_MODES.RECIPROCAL_RANK,
                similarity_top_k=target_k, use_async=False, verbose=False)
            self._discovery_summaries = {node.metadata['source_id']: node
                for node in index.docstore.docs.values() if node.metadata.get('discovery_only')}

    def retrieve(self, question: str) -> dict[str, Any]:
        if not isinstance(question, str) or not question.strip():
            raise ValueError("Enter a question before searching.")
        question = question.strip()
        if len(question) > self.config.max_question_characters:
            raise ValueError(f"Questions are limited to {self.config.max_question_characters} characters.")
        with self._lock, self.runtime.lock:
            if self._state != "ready":
                raise RuntimeError("The local retrieval engine has not been loaded.")
            for name, expected_hash in self._pipeline_artifacts.get('runtime_source_sha256', {}).items():
                if _sha256_file(Path(__file__).with_name(name)) != expected_hash:
                    raise RuntimeError('Retrieval code changed after model loading; restart the local service before searching.')
            from llama_index.core.schema import MetadataMode, QueryBundle
            from .query_constraints import query_hints, title_is_excluded, focused_query
            from .evidence_selection import choose_evidence, choose_grouped_evidence
            from .evidence_priority import preference_scores, prioritize_candidates
            from .primary_candidates import merge_primary_candidates
            from .document_discovery import ranked_source_ids
            from .discovery_anchors import source_anchor_nodes, retain_overview_descriptions
            from .adaptive_evidence import (routing_hints, evidence_limits, distinct_subjects,
                retain_source_and_detail, scoped_query, ranking_projection)

            started = time.perf_counter()
            query_tokens = len(self._tokenizer.encode(question, add_special_tokens=False))
            if query_tokens > self.config.max_query_tokens:
                raise ValueError(
                    f"This question has {query_tokens} model tokens; the current lab supports "
                    f"up to {self.config.max_query_tokens}. Split it into shorter questions."
                )
            hint_builder = routing_hints if self.config.adaptive_evidence else query_hints
            hints = hint_builder(question, self._documents.values(), exclusion_titles=self._exclusion_titles)
            overview = _wants_document_discovery(question, False)
            targeted_discovery = bool(self.config.adaptive_evidence and hints.broad_discovery and not overview)
            pair_limit, core_limit = evidence_limits(self.config, len(hints.comparison_source_ids), targeted_discovery)
            broad_query = hints.broad_discovery or _wants_document_discovery(question, False)
            primary_lane_enabled = bool(self.config.primary_candidate_slots
                and not hints.comparison_source_ids
                and (_wants_document_discovery(question, False) or re.search(
                    r'\b(?:options|products|items|models|choices|alternatives|formulas|suggest|recommend)\b',
                    question, re.I)))
            embedding_query = self.config.embedding_query_prefix + hints.retrieval_query
            embedding_query_tokens = len(self._embedding_tokenizer.encode(embedding_query).ids)
            if embedding_query_tokens > 512:
                raise ValueError("This question exceeds the embedding model's input limit.")
            retrieval_started = time.perf_counter()
            query_bundle = QueryBundle(query_str=hints.retrieval_query, custom_embedding_strs=[embedding_query])
            wide = self._fusion.retrieve(query_bundle)
            wide = prioritize_candidates(wide, question, self.config.evidence_role_weight)
            scoped_audit, scoped_queries, unavailable_scopes = {}, {}, []
            primary_audit = {}
            discovery_audit = {'enabled': False, 'source_ids': [], 'discovery_slots_used': 0}
            candidate_origins = {}
            jobs = {}
            omit_title_groups = set()
            comparison_anchors = {}
            document_pairs = 0
            document_rerank_ms = 0.0
            # The tested literal-property split lost cross-property facts. Keep
            # the complete requested task for each explicit subject instead.
            aspects = ()
            cells = []
            for aspect in (aspects or ('',)):
                for source_id in hints.comparison_source_ids:
                    if source_id not in self._scoped:
                        if source_id not in unavailable_scopes:
                            unavailable_scopes.append(source_id)
                        continue
                    focus = (f"{self._documents[source_id]['title']}. {aspect}" if aspect else
                        focused_query(hints.retrieval_query, self._documents[source_id]['title'],
                            [self._documents[s]['title'] for s in hints.comparison_source_ids]))
                    omit_title = False
                    if self.config.adaptive_evidence:
                        focus, omit_title = scoped_query(hints.retrieval_query, self._documents[source_id]['title'],
                            [self._documents[s]['title'] for s in hints.comparison_source_ids], focus)
                    if (len(self._tokenizer.encode(focus, add_special_tokens=False)) > self.config.max_query_tokens
                            or len(self._embedding_tokenizer.encode(self.config.embedding_query_prefix+focus).ids) > 512):
                        focus = question
                    cells.append((source_id, aspect, focus, omit_title))
            if unavailable_scopes:
                cells.append((None, '', hints.retrieval_query, False))
            # The bound is scored PAIRS, including a passage seen under two
            # facets. Decomposition never multiplies the cross-encoder budget.
            for index, (source_id, aspect, focus, omit_title) in enumerate(cells):
                key = f'{source_id or "global-fallback"}/{index}'
                quota = pair_limit // len(cells) + (index < pair_limit % len(cells))
                if omit_title:
                    omit_title_groups.add(key)
                if quota <= 0:
                    continue
                scoped_queries[key] = focus
                scoped_bundle = QueryBundle(query_str=focus,
                    custom_embedding_strs=[self.config.embedding_query_prefix+focus]) if source_id else query_bundle
                scoped = self._scoped[source_id].retrieve(scoped_bundle) if source_id else wide
                lane = self._primary.get(source_id or 'global')
                if primary_lane_enabled and lane:
                    primary, lane_audit = lane.retrieve(scoped_bundle, question)
                    scoped, merge_audit = merge_primary_candidates(scoped,primary,question,
                        max_candidates=quota,primary_cap=max(1,quota*self.config.primary_candidate_slots//self.config.rerank_candidates))
                    primary_audit[key] = {'retrieval':lane_audit,'merge':merge_audit}
                scoped = prioritize_candidates(scoped, focus, self.config.evidence_role_weight)
                if self.config.adaptive_evidence and source_id in self._discovery_summaries:
                    anchors = source_anchor_nodes(self._discovery_summaries[source_id],
                        self._source_nodes, self._model_nodes, self._documents, limit=1)
                    from .adaptive_evidence import preserve_retrieved_anchor_spans
                    anchors = preserve_retrieved_anchor_spans(scoped, anchors)
                    comparison_anchors[source_id] = [item.node.node_id for item in anchors]
                    scoped = [*anchors, *scoped]

                scoped_audit[key] = [item.node.node_id for item in scoped]
                chosen, seen = [], set()
                for item in scoped:
                    fact = (item.node.metadata.get('subject_source_id', item.node.metadata['source_id']),
                        ' '.join(item.node.text.split()))
                    if fact in seen or title_is_excluded(item.node.metadata.get('subject_title', item.node.metadata['title']), hints):
                        continue
                    seen.add(fact)
                    item.node.embedding = self._model_nodes[item.node.node_id].embedding
                    chosen.append(item)
                    if len(chosen) >= quota:
                        break
                if chosen:
                    jobs[key] = (focus, chosen)
            if not jobs:
                candidates, seen, source_counts = [], set(), Counter()
                def add(candidate):
                    if len(candidates) >= self.config.rerank_candidates:
                        return
                    source_id = candidate.node.metadata.get('subject_source_id', candidate.node.metadata['source_id'])
                    fact = (source_id, ' '.join(candidate.node.text.split()))
                    if fact in seen or title_is_excluded(candidate.node.metadata.get('subject_title', candidate.node.metadata['title']), hints):
                        return
                    seen.add(fact)
                    candidate.node.embedding = self._model_nodes[candidate.node.node_id].embedding
                    candidates.append(candidate)
                    source_counts[source_id] += 1
                if broad_query:
                    # Protect strong global hits before reserving source variety.
                    for item in wide[:self.config.rerank_candidates // 2]:
                        add(item)
                    per_source = max(4, self.config.rerank_candidates // 8)
                    for item in wide:
                        if source_counts[item.node.metadata.get('subject_source_id', item.node.metadata['source_id'])] < per_source:
                            add(item)
                for item in wide:
                    add(item)
                lane = self._primary.get('global')
                if primary_lane_enabled and lane:
                    primary, lane_audit = lane.retrieve(query_bundle, question)
                    primary = [item for item in primary if not title_is_excluded(
                        item.node.metadata.get('subject_title',item.node.metadata['title']),hints)]
                    candidates, merge_audit = merge_primary_candidates(candidates,primary,question,
                        max_candidates=self.config.rerank_candidates,primary_cap=self.config.primary_candidate_slots)
                    for item in candidates:
                        item.node.embedding = self._model_nodes[item.node.node_id].embedding
                    primary_audit['global'] = {'retrieval':lane_audit,'merge':merge_audit}
                primary_origins = {row['node_id']: row['lane'] for row in
                    primary_audit.get('global', {}).get('merge', {}).get('selected', [])}
                if (self.config.document_discovery_slots and self._discovery is not None
                        and not hints.comparison_source_ids
                        and (overview or targeted_discovery)):
                    had_embedding = query_bundle.embedding is not None
                    if targeted_discovery and self._targeted_discovery is not None:
                        from llama_index.core.schema import NodeWithScore
                        discovered = self._targeted_discovery.retrieve(query_bundle)
                        global_sources = distinct_subjects(wide, self._documents, 4)
                        existing_sources = {item.node.metadata['source_id'] for item in discovered}
                        for source_id in global_sources:
                            if source_id not in existing_sources and source_id in self._discovery_summaries:
                                discovered.append(NodeWithScore(node=self._discovery_summaries[source_id]))
                        document_pairs = len(discovered)
                        document_started = time.perf_counter()
                        discovered = self._reranker.postprocess_nodes(discovered, query_bundle=query_bundle)
                        document_rerank_ms = (time.perf_counter() - document_started) * 1000
                    else:
                        discovered = self._discovery.retrieve(query_bundle)
                        global_sources = []
                    allowed = [source_id for source_id in self._scoped if not title_is_excluded(
                        self._documents[source_id]['title'], hints)]
                    source_ids = ranked_source_ids(discovered, allowed, max_sources=8 if targeted_discovery else 4)
                    eligible = {item.node.metadata['source_id'] for item in discovered}
                    for source_id in global_sources:
                        if source_id in allowed and source_id in eligible and source_id not in source_ids:
                            source_ids.append(source_id)
                    details = {}
                    anchor_audit = {}
                    for source_id in source_ids:
                        hits = self._scoped[source_id].retrieve(query_bundle)
                        summary = next(item.node for item in discovered if item.node.metadata['source_id']==source_id)
                        anchors = (source_anchor_nodes(summary,self._source_nodes,self._model_nodes,self._documents,
                            limit=1 if targeted_discovery else 3)
                            if summary.metadata.get('discovery_witnesses') else [])
                        anchor_audit[source_id] = [item.node.node_id for item in anchors]
                        details[source_id] = [item for item in [*anchors,*hits] if
                            item.node.metadata.get('source_id') == source_id
                            and item.node.metadata.get('subject_source_id', source_id) == source_id
                            and item.node.node_id in self._model_nodes
                            and not title_is_excluded(item.node.metadata.get('subject_title',
                                item.node.metadata['title']), hints)]
                    candidates, merge_audit = _merge_discovered_candidates(candidates, details,
                        pair_limit, min(32, pair_limit // 2) if targeted_discovery else self.config.document_discovery_slots)
                    for item in candidates:
                        item.node.embedding = self._model_nodes[item.node.node_id].embedding
                    discovery_audit = {'enabled': True, 'source_ids': source_ids,
                        'source_anchor_nodes':anchor_audit,
                        'summary_ranks': [{'node_id': item.node.node_id, 'source_id': item.node.metadata['source_id'],
                                          'score': float(item.score or 0.0)} for item in discovered],
                        'detail_candidates': {source_id: [item.node.node_id for item in items]
                                              for source_id, items in details.items()},
                        'embedding_available_before': had_embedding, 'embedding_reused': had_embedding,
                        'targeted': targeted_discovery, 'summary_scored_pairs': document_pairs,
                        'index_id': self._discovery_manifest.get('discovery_index_id'), **merge_audit}
                origins = discovery_audit.get('selected_origins', {})
                candidate_origins = {item.node.node_id: (origins.get(item.node.node_id, 'global')
                    if origins.get(item.node.node_id, 'global') != 'global'
                    else primary_origins.get(item.node.node_id, 'global')) for item in candidates}
                # Explicit excluded entities are enforced as title filters.
                # Repeating their names in a relevance query can reward the
                # very item the user rejected; keep the original in the record.
                jobs['global'] = (hints.retrieval_query, candidates)
            retrieval_ms = (time.perf_counter() - retrieval_started) * 1000 - document_rerank_ms
            candidate_audit = []
            for key, (ranking_query, candidates) in jobs.items():
                for candidate in ranking_projection(candidates, key in omit_title_groups):
                    pair_tokens = len(self._tokenizer(
                        ranking_query, candidate.node.get_content(metadata_mode=MetadataMode.EMBED),
                        truncation=False, add_special_tokens=True)["input_ids"])
                    if pair_tokens > 512:
                        raise ValueError("A query/passage pair exceeds the reranker limit; no text was truncated.")
                    candidate_audit.append({
                        "node_id": candidate.node.node_id, "source_id": candidate.node.metadata["source_id"],
                        "subject_source_id": candidate.node.metadata.get('subject_source_id', candidate.node.metadata['source_id']),
                        "fusion_score": float(candidate.score or 0.0), "pair_tokens": pair_tokens,
                        "ranking_query": ranking_query, "query_group": key,
                        "title_omitted_for_ambiguous_scope": key in omit_title_groups,
                        "candidate_origin": candidate_origins.get(candidate.node.node_id,
                            'source_scoped' if key != 'global' else 'global'),
                    })
            if len(candidate_audit) > pair_limit:
                raise ValueError('Query decomposition exceeded the scored-pair budget.')
            rerank_started = time.perf_counter()
            ranked_groups = {key:self._reranker.postprocess_nodes(ranking_projection(candidates, key in omit_title_groups), query_bundle=QueryBundle(focus))
                for key,(focus,candidates) in jobs.items()}
            rerank_ms = (time.perf_counter() - rerank_started) * 1000
            ranked_audit = [{"node_id":r.node.node_id, "source_id":r.node.metadata["source_id"],
                "score":float(r.score), "evidence_role":r.node.metadata.get('evidence_role','UNKNOWN'),
                "query_group":key, "rank_in_group":i+1}
                for key, group in ranked_groups.items() for i,r in enumerate(group)]
            selection_scores = ({key:preference_scores(group, jobs[key][0], self.config.evidence_role_weight)
                for key,group in ranked_groups.items()} if self.config.evidence_role_weight else None)
            if cells:
                ranked = choose_grouped_evidence(ranked_groups, core_limit,
                    selection_scores=selection_scores)
                if comparison_anchors:
                    from .adaptive_evidence import anchors_without_primary_evidence
                    comparison_anchors = anchors_without_primary_evidence(ranked, comparison_anchors)
                    ranked = retain_overview_descriptions(
                        [item for group in ranked_groups.values() for item in group],
                        ranked, comparison_anchors, core_limit)

            else:
                ranked = choose_evidence(ranked_groups['global'], core_limit,
                    diversity_strength=.45 if broad_query else .15,
                    source_penalty=.10 if broad_query else .04,
                    selection_scores=selection_scores['global'] if selection_scores else None)
                if discovery_audit['enabled']:
                    retain = retain_source_and_detail if targeted_discovery else retain_overview_descriptions
                    ranked = retain(ranked_groups['global'],ranked,
                        discovery_audit.get('source_anchor_nodes',{}),core_limit)
                    discovery_audit['context_policy'] = ('scored_source_and_detail' if targeted_discovery
                                                        else 'retain_scored_source_descriptions')
            from .evidence_context import fit_evidence_context
            assembled = fit_evidence_context(ranked, self._source_nodes, self._documents,
                self._context_tokenizer, self.config.context_token_budget, core_limit)
            evidence, context = assembled['evidence'], assembled['context']
            omitted_for_context_budget = len(assembled['audit'].get('omitted_core_node_ids', []))
            return {
                "question": question,
                "evidence": evidence,
                "context": context,
                "context_tokens": len(self._context_tokenizer.encode(context, disallowed_special=())),
                "context_sha256": hashlib.sha256(context.encode("utf-8")).hexdigest(),
                "corpus_sha256": self._manifest["corpus_sha256"],
                "pipeline": self.pipeline_provenance(),
                "timings": {
                    "retrieval_ms": round(retrieval_ms, 2),
                    "rerank_ms": round(rerank_ms + document_rerank_ms, 2),
                    "passage_rerank_ms": round(rerank_ms, 2),
                    "document_rerank_ms": round(document_rerank_ms, 2),
                    "total_ms": round((time.perf_counter() - started) * 1000, 2),
                },
                "audit": {
                    "candidates": candidate_audit,
                    "wide_candidates": [{"node_id":c.node.node_id,"source_id":c.node.metadata["source_id"]} for c in wide],
                    "scoped_candidates": scoped_audit,
                    "scoped_queries": scoped_queries,
                    "primary_candidate_lane": primary_audit,
                    "document_discovery": discovery_audit,
                    "reranked_candidates": ranked_audit,
                    "query_hints": {"retrieval_query":hints.retrieval_query,
                        "comparison_source_ids":hints.comparison_source_ids,
                        "excluded_title_terms":hints.excluded_title_terms,
                        "broad_discovery":broad_query and not cells},
                    "scored_pairs": len(candidate_audit),
                    "document_ranking_pairs": document_pairs,
                    "total_scored_pairs": len(candidate_audit) + document_pairs,
                    "detail_pair_limit": pair_limit,
                    "core_limit": core_limit,
                    "comparison_source_anchors": comparison_anchors,
                    "unique_candidates": len({c["node_id"] for c in candidate_audit}),
                    "literal_query_aspects": list(aspects),
                    "unavailable_scopes": unavailable_scopes,
                    "query_tokens": query_tokens,
                    "embedding_query_tokens": embedding_query_tokens,
                    "max_pair_tokens": max((row["pair_tokens"] for row in candidate_audit), default=0),
                    "omitted_for_context_budget": omitted_for_context_budget,
                    "context_assembly": assembled["audit"],
                    "silent_truncation": False,
                    "generative_provider_calls": 0,
                    "device": "cpu",
                    "index_id": self._manifest["index_id"],
                },
            }
