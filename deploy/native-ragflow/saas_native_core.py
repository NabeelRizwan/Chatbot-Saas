# Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
# Adapted from api/apps/restful_apis/chunk_api.py at
# a024bea0cd93f39e6652a42bf84dd20c55bc560b. Apache-2.0 (LICENSE).
"""Bounded W128 adapter around unchanged native search; no generation calls."""
import hashlib
import json
from pathlib import Path
import re

UPSTREAM = "a024bea0cd93f39e6652a42bf84dd20c55bc560b"
MODEL = "BAAI/bge-small-en-v1.5"
POLICY = {"version": "native-w128-v1", "upstream": UPSTREAM,
          "candidates": 128, "knn_top_k": 1024, "knn_num_candidates": 2048,
          "similarity_threshold": .1, "vector_similarity_weight": .3,
          "embedding": MODEL, "parent_expansion": "before_bge"}


class NativeBoundaryError(RuntimeError):
    pass


def require(value, code):
    if not value:
        raise NativeBoundaryError(code)


def native_id(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{32}", value), "IDENTITY_INVALID")
    return value


def source_integrity():
    manifest = json.loads(Path("/stock-native/source-manifest.json").read_text())
    require(manifest["commit"] == UPSTREAM, "UPSTREAM_REVISION_INVALID")
    for name, expected in manifest["files"].items():
        require(hashlib.sha256((Path("/ragflow") / name).read_bytes()).hexdigest() == expected,
                "UPSTREAM_SOURCE_CHANGED")


def scope(tenant, dataset, documents):
    from common.constants import LLMType
    from api.db.joint_services.tenant_model_service import resolve_model_config
    from api.db.services.knowledgebase_service import KnowledgebaseService
    from api.db.services.document_service import DocumentService
    native_id(tenant)
    native_id(dataset)
    require(isinstance(documents, list) and 0 < len(documents) <= 10000 and
            len(set(documents)) == len(documents), "DOCUMENT_SCOPE_INVALID")
    for doc in documents:
        native_id(doc)
    found, kb = KnowledgebaseService.get_by_id(dataset)
    require(found and kb.tenant_id == tenant and kb.status == "1", "DATASET_SCOPE_INVALID")
    # RAGFlow stores either a model reference or a tenant-model UUID. Resolve
    # both through its own ownership-aware resolver, never compare a UUID to a name.
    config = resolve_model_config(tenant, LLMType.EMBEDDING, kb.embd_id)
    require(config["llm_name"] == MODEL and config["llm_factory"] == "HuggingFace", "EMBEDDING_PROFILE_INVALID")
    rows = {}
    for doc_id in documents:
        found, doc = DocumentService.get_by_id(doc_id)
        require(found and doc.kb_id == dataset and doc.status == "1" and
                float(doc.progress or 0) == 1, "DOCUMENT_NOT_READY")
        rows[doc_id] = (str(doc.update_time), doc.name, doc.chunk_num, doc.parser_id,
                        json.dumps(doc.parser_config, sort_keys=True))
    return kb, rows


async def retrieve(tenant, payload):
    from common import settings
    from common.constants import LLMType
    from api.db.services.llm_service import LLMBundle
    from rag.app.tag import label_question
    from api.db.joint_services.tenant_model_service import resolve_model_config
    require(isinstance(payload, dict) and set(payload) == {"question", "dataset_id", "document_ids"},
            "REQUEST_INVALID")
    question = payload["question"]
    require(isinstance(question, str) and question.strip() and len(question) <= 16384, "QUERY_INVALID")
    dataset, documents = payload["dataset_id"], payload["document_ids"]
    kb, before = scope(tenant, dataset, documents)
    model_config = resolve_model_config(tenant, LLMType.EMBEDDING, kb.embd_id)
    require(model_config["llm_factory"] == "HuggingFace", "EMBEDDING_FACTORY_INVALID")
    # The frozen experiments used this same native HuggingFaceEmbed directly.
    # Query retrieval is read-only; native account token counters are not written.
    with LLMBundle(tenant, model_config) as bundle:
        result = await settings.retriever.retrieval(
            question, bundle.mdl, [tenant], [dataset], 1, 128, .1, .3,
            doc_ids=documents, knn_top_k=1024, knn_num_candidates=2048,
            rerank_mdl=None, highlight=False, rank_feature=label_question(question, [kb]),
            rerank_candidates_count=128)
    chunks = settings.retriever.retrieval_by_children(result["chunks"], [tenant])
    _, after = scope(tenant, dataset, documents)
    require(before == after, "SOURCE_CHANGED_DURING_RETRIEVAL")
    require(isinstance(chunks, list) and len(chunks) <= 128, "NATIVE_RESULT_INVALID")
    output, seen = [], set()
    for chunk in chunks:
        kb_ids = chunk["kb_id"] if isinstance(chunk["kb_id"], list) else [chunk["kb_id"]]
        require(kb_ids == [dataset] and chunk["doc_id"] in documents and
                isinstance(chunk["content_with_weight"], str) and chunk["content_with_weight"].strip() and
                chunk["chunk_id"] not in seen, "SOURCE_SCOPE_INVALID")
        seen.add(chunk["chunk_id"])
        output.append({key: chunk.get(key) for key in (
            "chunk_id", "doc_id", "kb_id", "docnm_kwd", "content_with_weight",
            "similarity", "term_similarity", "vector_similarity", "image_id", "positions")})
        output[-1]["kb_id"] = dataset
    return {"policy": POLICY, "tenant_id": tenant, "dataset_id": dataset, "chunks": output}


def manifest(tenant, payload):
    """Snapshot complete native passages, including linked parent rows, without vectors."""
    from common import settings
    from rag.nlp.search import index_name
    require(isinstance(payload, dict) and set(payload) == {"dataset_id", "document_id"}, "REQUEST_INVALID")
    dataset, document = payload["dataset_id"], payload["document_id"]
    _, before = scope(tenant, dataset, [document])
    es = settings.docStoreConn.es
    fields = ["doc_id", "kb_id", "docnm_kwd", "content_with_weight", "available_int", "mom_id", "position_int", "img_id"]
    response = es.search(index=index_name(tenant), size=500, scroll="1m", sort=["_doc"],
        source=fields, query={"bool": {"filter": [{"term": {"kb_id": dataset}}, {"term": {"doc_id": document}}],
                                   "must_not": [{"exists": {"field": "compile_kwd"}}]}}, track_total_hits=True)
    scroll = response.get("_scroll_id")
    chunks = []
    try:
        total = response["hits"]["total"]["value"]
        require(0 < total <= 20000, "MANIFEST_SIZE_INVALID")
        while response["hits"]["hits"]:
            for hit in response["hits"]["hits"]:
                row = hit["_source"]
                kb_ids = row["kb_id"] if isinstance(row["kb_id"], list) else [row["kb_id"]]
                require(kb_ids == [dataset] and row["doc_id"] == document, "MANIFEST_SCOPE_INVALID")
                text = row["content_with_weight"]
                require(isinstance(text, str) and bool(text.strip()), "MANIFEST_CONTENT_INVALID")
                chunks.append({"id": hit["_id"], "content": text, "title": row.get("docnm_kwd", ""),
                               "sha256": hashlib.sha256(text.encode()).hexdigest(),
                               "metadata": {key: row.get(key) for key in ("mom_id", "available_int", "position_int", "img_id")}})
            require(len(chunks) <= total, "MANIFEST_CHANGED")
            if len(chunks) == total:
                break
            response = es.scroll(scroll_id=scroll, scroll="1m")
            scroll = response.get("_scroll_id", scroll)
        require(len(chunks) == total and len({row["id"] for row in chunks}) == total, "MANIFEST_INCOMPLETE")
    finally:
        if scroll:
            es.clear_scroll(scroll_id=scroll)
    _, after = scope(tenant, dataset, [document])
    require(before == after, "SOURCE_CHANGED_DURING_MANIFEST")
    chunks.sort(key=lambda row: row["id"])
    digest = hashlib.sha256(json.dumps(chunks, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"policy": POLICY, "tenant_id": tenant, "dataset_id": dataset, "document_id": document,
            "manifest_sha256": digest, "chunks": chunks}
