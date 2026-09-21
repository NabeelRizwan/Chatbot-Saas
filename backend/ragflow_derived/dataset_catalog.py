# Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
# Licensed under the Apache License, Version 2.0.
# Modified for Chatbot-SaaS: explicit scoped imports; see port manifest.
from __future__ import annotations
import asyncio
import json
import logging
import math
from enum import IntEnum
from ragflow_derived.full_runtime import settings, current, KnowledgebaseService, scoped_documents

class RetCode(IntEnum):
    SUCCESS = 0
    NOT_EFFECTIVE = 10
    EXCEPTION_ERROR = 100
    ARGUMENT_ERROR = 101
    DATA_ERROR = 102
    OPERATING_ERROR = 103
    CONNECTION_ERROR = 105
    RUNNING = 106
    PERMISSION_ERROR = 108
    AUTHENTICATION_ERROR = 109
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    SERVER_ERROR = 500
    FORBIDDEN = 403
    NOT_FOUND = 404
    CONFLICT = 409

def _compiled_index_or_none(tenant_id: str, kb_id: str):
    """Return (index_name, search_module) when the tenant index exists,
    else ``None``. Avoids 500s on brand-new tenants whose ES index hasn't
    been created yet."""
    from ragflow_derived.upstream import search as _rag_search

    index_nm = _rag_search.index_name(tenant_id)
    if not settings.docStoreConn.index_exist(index_nm, kb_id):
        return None
    return index_nm, _rag_search

_NAV_COMPILE_KWD = "dataset_nav"
_NAV_ROOT_PARENT = "root"
_NAV_FIELDS = [
    "id",
    "name",
    "type_kwd",
    "content_with_weight",
    "doc_count_int",
    "doc_ids_kwd",
    "doc_id",
    "depth_int",
    "parent_kwd",
]


def _first_str(val) -> str:
    """Extract the first string from a value that may be str, list, tuple, or set."""
    if isinstance(val, (list, tuple, set)):
        return str(next(iter(val), "") or "")
    return str(val or "")


def _resolve_embd_mdl(kb):
    KnowledgebaseService.accessible(kb.id, kb.tenant_id)
    return current().tools.embed_mdl



def _nav_item(row: dict) -> dict:
    """Shape one nav row into a UI node: name, description, doc count, type."""
    try:
        payload = json.loads(row.get("content_with_weight") or "{}")
    except Exception:
        payload = {}
    row_type = row.get("type_kwd")
    if isinstance(row_type, (list, tuple, set)):
        row_type = next(iter(row_type), None)
    is_cluster = (row_type or payload.get("type")) == "nav_cluster"
    return {
        "name": row.get("name") or "",
        "description": payload.get("description") or "",
        "keywords": list(payload.get("keywords") or []),
        "entities": list(payload.get("entities") or []),
        "graph_content": payload.get("graph_content") or "",
        # doc_id count under this node: the cluster`s tally, or 1 for a leaf.
        "doc_count": int(row.get("doc_count_int") or 0) if is_cluster else 1,
        "type": "cluster" if is_cluster else "doc",
        "doc_id": None if is_cluster else (row.get("doc_id") or row.get("name")),
        "has_children": is_cluster,
    }


async def _nav_search(dataset_id: str, tenant_id: str, condition: dict, page: int, page_size: int):
    """Run one nav-tree search and shape the hits into UI nodes."""
    if not KnowledgebaseService.accessible(dataset_id, tenant_id):
        return False, "no authorization"
    _, kb = KnowledgebaseService.get_by_id(dataset_id)

    pack = _compiled_index_or_none(kb.tenant_id, dataset_id)
    if pack is None:
        return True, {"total": 0, "items": []}
    index_nm, _ = pack

    from ragflow_derived.upstream.doc_store import OrderByExpr

    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 1000), 2000))
    offset = (page - 1) * page_size

    order_by = OrderByExpr()
    try:
        # Biggest clusters first; leaves (no doc_count_int) fall to the end.
        order_by.desc("doc_count_int")
    except Exception:
        order_by = OrderByExpr()

    try:
        res = settings.docStoreConn.search(
            select_fields=_NAV_FIELDS,
            highlight_fields=[],
            condition=condition,
            match_expressions=[],
            order_by=order_by,
            offset=offset,
            limit=page_size,
            index_names=index_nm,
            knowledgebase_ids=[dataset_id],
        )
        field_map = settings.docStoreConn.get_fields(res, _NAV_FIELDS)
    except Exception:
        logging.exception("dataset_nav: docStore search failed for kb=%s", dataset_id)
        return True, {"total": 0, "items": []}

    total = settings.docStoreConn.get_total(res)
    items = [_nav_item(row) for row in (field_map or {}).values()]
    return True, {"total": int(total or 0), "items": items}


async def list_nav_clusters(dataset_id: str, tenant_id: str, page: int = 1, page_size: int = 1000, q: str | None = None, top_k: int | None = None):
    """First level of the nav tree: the clusters with no parent.

    When ``q`` is provided, runs a tree-structured search (mode="navigation_tree")
    and returns enriched nav node items in the same ``_nav_item`` shape so the
    frontend tree search can reuse this endpoint.
    """
    if q and q.strip():
        success, result = await search_dataset_layers(dataset_id, tenant_id, q.strip(), "navigation_tree", top_k=top_k or 1000)
        if not success:
            return success, result
        result["items"] = await _enrich_nav_items(dataset_id, tenant_id, result.get("items", []))
        return True, {"total": result.get("total", 0), "items": result["items"]}
    condition = {
        "compile_kwd": [_NAV_COMPILE_KWD],
        "type_kwd": ["nav_cluster"],
        "parent_kwd": [_NAV_ROOT_PARENT],
    }
    return await _nav_search(dataset_id, tenant_id, condition, page, page_size)


async def list_nav_children(dataset_id: str, tenant_id: str, name: str, page: int = 1, page_size: int = 1000):
    """Direct children of the node ``name`` — sub-clusters and document leaves.

    One level at a time (lazy) so the tree loads hierarchically as the user
    expands each node.
    """
    if not isinstance(name, str) or not name.strip():
        return True, {"total": 0, "items": []}
    condition = {
        "compile_kwd": [_NAV_COMPILE_KWD],
        "parent_kwd": [name.strip()],
    }
    return await _nav_search(dataset_id, tenant_id, condition, page, page_size)


_LAYERS_HANDLERS: dict[str, str] = {
    "nav_doc": "_search_layers_nav_docs",
    "nav_cluster": "_search_layers_nav_clusters",
    "navigation_tree": "_search_layers_navigation_tree",
    "chunk": "_search_layers_chunks",
    "all": "_search_layers_all",
}

# Document router behind the "navigation_tree" mode.  Callers always ask for
# mode="navigation_tree", so swapping strategy needs no change on their side.
#
#   "nav_doc" (default) — flat hybrid search over the nav_doc rows.  No cluster
#       level is consulted, so nothing is pruned, but the comparison still runs
#       on document-level embeddings.  Those rows embed ``graph_text`` — the
#       document's full entity/relation listing — not a one-line summary, so
#       this is not the "compressed representation first" case that SCT measures.
#   "chunk_agg" — PageIndex ``semantics`` recipe: hybrid search over the raw
#       chunk index, hits rolled up per document with
#       DocScore = sum(chunk scores) / sqrt(hits + 1).  Sound in principle, but
#       chunk-level similarity is easy to clear: a document passes the 0.2 floor
#       on a single marginally related chunk, so the top-k roster fills with
#       weakly related documents, and the wider routing fans out every later
#       stage.  Measured 2026-09-02: 12/12 questions routed a full 12 documents,
#       evidence pool 42-67 passages, 166s per question against a 180s budget,
#       with several timeouts yielding no answer at all.
#   "compiled_agg" — page_index entity rows only; "fusion" — chunk + compiled.
#   "tree" — BFS beam descent over the nav cluster tree.  This is what main
#       branch does.  Kept as the A/B baseline; drop it, and
#       ``search_nav_tree_descent`` with it, once a winner is settled.

# Cap on how many documents a flat router hands back.  The cluster beam descent
# that main uses returns ~2 by construction (its per-level pruning keeps only
# the most relevant branches), while the flat nav_doc sweep returns every row
# above the 0.2 floor — measured 2026-09-02: beam avg 2.0 vs nav_doc avg 6.2.
# Routing to 3x the documents made the RAGAgent carry 3x the evidence in every
# round, so each dynamic LLM call grew 14k -> 18.8k tokens and per-question time
# grew ~25%.  Beam is not capped at 2 either (it occasionally routes 6 for
# multi-hop), so allow a little headroom above its median rather than a hard 2.
_NAV_DOC_FOCUS_LIMIT = 3

# Candidate pool for "chunk_agg".  DocScore only means something when a document
# can collect several hits, so the pool has to be wide enough for that; across a
# 2400-document corpus a pool of a few dozen chunks yields almost entirely
# single-hit documents, which collapses DocScore into plain best-chunk ranking.
# This is ``rerank_candidates_count`` — the pool the fusion actually draws from.
# ``page_size`` is deliberately the same value so the whole pool is returned for
# aggregation, and it must stay <= the pool or ``retrieval`` raises
# (page * page_size > rerank_candidates_count).
_NAV_CHUNK_AGG_POOL = 256
_NAV_CHUNK_AGG_VEC_WEIGHT = 0.3

# Candidate pool of compiled entity rows for the "compiled_agg" / "fusion"
# routers.  ``get_vector`` builds its own MatchDenseExpr and never routes through
# ``retrieval``, so ``rerank_candidates_count`` does not apply here — but HNSW
# needs ``num_candidates`` >= the pool or the search degenerates.
_NAV_COMPILED_POOL = 256
_NAV_COMPILED_SIMILARITY = 0.1
# Entity types aggregated separately.  A document carries far more facts than
# titles, so pooling them would let fact hits drown out title hits; splitting
# keeps the coarser title signal usable.  ``entity_type_kwd`` does not exist on
# compilation rows (it belongs to graphrag), so the type is read from the
# payload after the fetch.
_NAV_COMPILED_TITLE_TYPES = ("title",)
_NAV_COMPILED_FACT_TYPES = ("fact", "conclusion")
# Weights applied when the fusion router combines the three legs.  Only used
# when documents are hit by several legs.
_NAV_FUSION_WEIGHTS = {"chunk": 1.0, "title": 0.8, "fact": 0.9}

# Section bridge (stage 3): resolve each hit fact to its owning title.  The
# relation type carrying TOC containment in the page_index template, plus caps
# on how many names are resolved and how many relation rows may be scanned.
_NAV_INCLUDE_RELATION = "include"
_NAV_BRIDGE_NAMES_LIMIT = 64
_NAV_BRIDGE_FANOUT = 4
# Compiled products (tree/entity/relation rows) are written with
# available_int=1, so they fall inside the chunk filter and would otherwise
# inflate a document's hit count.  The project convention is that plain
# retrieval reads document chunks only and compiled products are served by their
# own tools, so exclude them here too.  Flip to False to A/B letting compiled
# rows act as extra per-document entries in the aggregation.
_NAV_CHUNK_AGG_EXCLUDE_COMPILED = True


async def search_dataset_layers(
    dataset_id: str,
    tenant_id: str,
    query: str,
    mode: str,
    *,
    top_k: int | None = None,
    doc_scope: list[str] | None = None,
) -> tuple[bool, dict]:
    """Unified search across different knowledge layers of a dataset.

    Args:
        mode: One of ``"chunk"``, ``"nav_doc"``, ``"nav_cluster"``, ``"navigation_tree"``, ``"all"``.
            - chunk: raw document chunks (via the main retrieval pipeline)
            - nav_doc: navigation tree document leaves
            - nav_cluster: navigation tree cluster nodes
            - navigation_tree: document routing, strategy chosen by
              ``_NAV_TREE_ROUTER`` (chunk aggregation by default)
            - all: union of all modes, deduplicated by doc_id with best score
        doc_scope: Optional set of documents to restrict the search to.  None or
            empty means all documents of the dataset.  Forwarded to every mode:
            nav modes filter the compiled nav rows by doc, ``chunk`` restricts
            the retriever via ``doc_ids``.  Applied query-time so scoped rows
            are never dropped by the ``top_k`` truncation.

        Items are shaped as ``{"doc_id": str, "score": float}``.
    """
    from ragflow_derived.upstream.advanced_rag.knowlege_compile.dataset_nav import search_dataset_nav

    if not KnowledgebaseService.accessible(dataset_id, tenant_id):
        return False, {"error": "no authorization", "code": RetCode.PERMISSION_ERROR}
    if mode not in _LAYERS_HANDLERS:
        return False, {"error": f"unknown mode: {mode}, expected one of {list(_LAYERS_HANDLERS.keys())}", "code": RetCode.ARGUMENT_ERROR}
    _, kb = KnowledgebaseService.get_by_id(dataset_id)

    doc_scope = scoped_documents(doc_scope)
    embd_mdl = _resolve_embd_mdl(kb)

    logging.debug(
        "search_dataset_layers: dispatching scoped mode=%s for dataset=%s, scoped_docs=%d",
        mode,
        dataset_id,
        len([d for d in (doc_scope or []) if str(d).strip()]),
    )
    if mode == "nav_doc":
        return await _search_layers_nav_docs(tenant_id, dataset_id, query, top_k, embd_mdl, search_dataset_nav, doc_scope=doc_scope)
    elif mode == "nav_cluster":
        return await _search_layers_nav_clusters(tenant_id, dataset_id, query, top_k, embd_mdl, search_dataset_nav, doc_scope=doc_scope)
    elif mode == "navigation_tree":
        return await _search_layers_navigation_tree(tenant_id, dataset_id, query, top_k, embd_mdl, kb, router="tree", doc_scope=doc_scope)
    elif mode == "chunk":
        return await _search_layers_chunks(tenant_id, dataset_id, query, top_k, embd_mdl, kb, doc_scope=doc_scope)
    elif mode == "all":
        return await _search_layers_all(tenant_id, dataset_id, query, top_k, embd_mdl, kb, search_dataset_nav, doc_scope=doc_scope)
    else:
        return False, {"error": f"unknown mode: {mode}", "code": RetCode.ARGUMENT_ERROR}


async def _search_layers_nav_docs(tenant_id, dataset_id, query, top_k, embd_mdl, search_fn, *, doc_scope=None):
    items = await _nav_search_result(
        tenant_id,
        dataset_id,
        query,
        top_k,
        embd_mdl,
        search_fn,
        type_kwd="nav_doc",
        doc_scope=doc_scope,
    )
    return True, {"mode": "nav_doc", "total": len(items), "items": items}


async def _search_layers_nav_clusters(tenant_id, dataset_id, query, top_k, embd_mdl, search_fn, *, doc_scope=None):
    items = await _nav_search_result(
        tenant_id,
        dataset_id,
        query,
        top_k,
        embd_mdl,
        search_fn,
        type_kwd="nav_cluster",
        doc_scope=doc_scope,
    )
    return True, {"mode": "nav_cluster", "total": len(items), "items": items}


def _nav_focus_items(items: list) -> list:
    """Truncate a flat routing to the most relevant documents, in place.

    The flat sweep returns every row above the floor; the cluster descent main
    uses stays focused by its per-level pruning.  See ``_NAV_DOC_FOCUS_LIMIT``
    for the measured reason this matters.
    """
    limit = _NAV_DOC_FOCUS_LIMIT
    if not limit or len(items) <= limit:
        return items
    items.sort(key=lambda it: float(it.get("score", 0.0)), reverse=True)
    del items[limit:]
    return items


def _nav_label_items(items: list) -> list:
    """Give each routed item the ``_nav`` summary navigation.py reads.

    ``search_dataset_nav`` returns the leaf row flat (``name``/``description`` at
    the top level), but navigation.py reads the route label from
    ``item["_nav"]["description"]``, so without this a route comes back
    unlabelled.  The rows already carry the summary, so this costs no extra
    query — unlike the chunk router, which has to look one up.
    """
    for item in items:
        if not isinstance(item, dict) or item.get("_nav"):
            continue
        item["_nav"] = {
            "doc_id": str(item.get("doc_id") or "").strip(),
            "description": str(item.get("description") or item.get("name") or "").strip(),
        }
    return items


async def _search_layers_navigation_tree(tenant_id, dataset_id, query, top_k, embd_mdl, kb=None, *, router: str = "chunk_agg", doc_scope=None):
    """Route to documents using the requested navigation-tree strategy.

    Every strategy returns the same item shape — ``doc_id``, a 0..1 ``score``,
    and ``_nav`` carrying the document summary — so callers stay agnostic to
    which one is active.
    """
    if router == "nav_doc":
        from ragflow_derived.upstream.advanced_rag.knowlege_compile.dataset_nav import search_dataset_nav

        items = await _nav_search_result(
            tenant_id,
            dataset_id,
            query,
            top_k,
            embd_mdl,
            search_dataset_nav,
            type_kwd="nav_doc",
            doc_scope=doc_scope,
        )
        _nav_focus_items(items)
        _nav_label_items(items)
        return True, {"mode": "navigation_tree", "total": len(items), "items": items}

    if router == "tree":
        from ragflow_derived.upstream.advanced_rag.knowlege_compile.dataset_nav import search_nav_tree_descent

        items = await search_nav_tree_descent(
            tenant_id,
            dataset_id,
            query,
            embd_mdl,
            top_k=top_k,
            doc_scope=doc_scope,
        )
        return True, {"mode": "navigation_tree", "total": len(items), "items": items}

    if router in ("compiled_agg", "fusion"):
        ok, payload = await _search_layers_compiled_agg(tenant_id, dataset_id, query, top_k, embd_mdl, kb, doc_scope=doc_scope)
        if router == "compiled_agg":
            return ok, payload
        # Fusion keeps going: the compiled leg ranks alongside the chunk leg.
        return await _search_layers_fusion(tenant_id, dataset_id, query, top_k, embd_mdl, kb, compiled=payload, doc_scope=doc_scope)

    return await _search_layers_chunk_agg(tenant_id, dataset_id, query, top_k, embd_mdl, kb, doc_scope=doc_scope)


async def _search_layers_chunk_agg(tenant_id, dataset_id, query, top_k, embd_mdl, kb=None, *, doc_scope=None):
    """Route to documents by rolling up raw-chunk hybrid hits (PageIndex style).

    Retrieval runs over the chunk index — uncompressed text — and the hits are
    aggregated per document with PageIndex's DocScore::

        DocScore = sum(chunk scores) / sqrt(hits + 1)

    The numerator rewards a document that matches several chunks; the
    square-root denominator damps that reward so a long document cannot win on
    volume alone.

    Ordering uses DocScore, but the reported ``score`` is the document's best
    chunk similarity: callers threshold on it (``_NAV_MIN_DOC_SCORE``), and
    keeping a single chunk's similarity preserves the 0..1 scale those
    thresholds were set against.
    """
    from ragflow_derived.full_runtime import settings

    kwargs = {}
    if doc_scope:
        kwargs["doc_ids"] = [str(d) for d in doc_scope if str(d).strip()]

    pool = _NAV_CHUNK_AGG_POOL
    # Term-only and dense scores live on different scales, so the weight (not the
    # threshold) carries the "is there an embedding model" decision.
    vector_weight = _NAV_CHUNK_AGG_VEC_WEIGHT if embd_mdl else 0
    try:
        ranks = await settings.retriever.retrieval(
            query,
            embd_mdl,
            [tenant_id],
            [dataset_id],
            1,
            # page_size == the pool, so every fused candidate reaches the
            # aggregation below.
            pool,
            # No similarity floor: ranking is done by DocScore, so the pool must
            # stay wide enough for a document to collect several hits.  A floor
            # here would pre-empt the aggregation.
            0.0,
            vector_weight,
            # knn_top_k is left at its default: it caps how many neighbours the
            # vector leg feeds into fusion, and narrowing it to top_k would
            # shrink the pool this strategy depends on.
            rerank_candidates_count=pool,
            must_not={"exists": "compile_kwd"} if _NAV_CHUNK_AGG_EXCLUDE_COMPILED else None,
            **kwargs,
        )
    except Exception:
        logging.exception("search_dataset_layers: chunk-agg retrieval failed for kb=%s", dataset_id)
        return False, {"error": "chunk retrieval failed", "code": RetCode.SERVER_ERROR}

    agg = _nav_aggregate_chunks(ranks.get("chunks", []))
    if not agg:
        return True, {"mode": "navigation_tree", "total": 0, "items": []}

    ranked = sorted(agg.items(), key=lambda kv: _nav_doc_score(kv[1]), reverse=True)
    # Cap by the caller's top_k and by the focus limit.  Without the focus cap
    # this router returned every document above the floor (measured 6-12),
    # routing the RAGAgent into 3x the evidence and inflating every dynamic LLM
    # call — the same regression the nav_doc router had, fixed here the same way.
    limit = _NAV_DOC_FOCUS_LIMIT or (top_k or _NAV_CHUNK_AGG_POOL)
    if limit > 0:
        ranked = ranked[:limit]

    summaries = await _nav_doc_summaries(kb, [doc_id for doc_id, _ in ranked])
    items = [
        {
            "doc_id": doc_id,
            "score": round(entry["best"], 4),
            "_nav": {"doc_id": doc_id, "description": summaries.get(doc_id, "")},
            # Aggregation detail, surfaced for tuning the fetch multiplier.
            "_agg": {"doc_score": round(_nav_doc_score(entry), 4), "hits": entry["hits"]},
        }
        for doc_id, entry in ranked
    ]
    return True, {"mode": "navigation_tree", "total": len(items), "items": items}


async def _search_layers_compiled_agg(tenant_id, dataset_id, query, top_k, embd_mdl, kb=None, *, doc_scope=None):
    """Route to documents through compiled ``page_index`` entity rows.

    Complements the chunk leg rather than replacing it: chunks are verbatim text
    and win on exact matches (numbers, proper nouns), while ``fact`` /
    ``conclusion`` rows are atomic propositions that win on concept matches the
    surface form misses.  Each covers the other's failure mode.

    Compiled rows carry no ``available_int``, which is the project's marker for
    "visible to the generic retriever" (not a deletion flag), so they are absent
    from the chunk index and have to be read through the store seam directly --
    the same seam ``dataset_nav`` and wiki use.

    Returns ``ok=False`` only on a store failure; an empty result set is a
    legitimate outcome (a KB without page_index products) and is reported
    ``ok=True`` with ``total=0`` so the caller can fall back.
    """
    pack = _compiled_index_or_none(kb.tenant_id, kb.id) if kb is not None else None
    if pack is None:
        return True, {"mode": "navigation_tree", "total": 0, "items": []}
    from ragflow_derived.upstream.doc_store import OrderByExpr
    from ragflow_derived.upstream.search import MatchTextExpr

    index_nm, _ = pack

    pool = _NAV_COMPILED_POOL
    condition = {
        "compile_kwd": ["page_index"],
        "knowledge_graph_kwd": ["entity"],
        # Exclude the KB-wide merged rows written by the Build button.
        "scope_kwd": ["doc"],
    }
    if doc_scope:
        condition["doc_id"] = [str(d) for d in doc_scope if str(d).strip()]

    fields = ["content_with_weight", "source_chunk_ids", "doc_id", "name_kwd"]
    try:
        # Compiled rows tokenize their description into content_ltks, so a
        # keyword match is a real fallback when no embedding model is configured
        # or embedding fails -- the leg degrades instead of dropping out.
        exprs = []
        if embd_mdl:
            try:
                exprs.append(
                    await settings.retriever.get_vector(
                        query,
                        embd_mdl,
                        top_k=pool,
                        # HNSW ef_search -- must be >= top_k or the ANN search
                        # collapses.  Positional passing here would hit
                        # num_candidates with the similarity threshold.
                        num_candidates=pool,
                        similarity=_NAV_COMPILED_SIMILARITY,
                    )
                )
            except Exception:
                logging.exception("dataset_nav: compiled vector build failed for kb=%s", kb.id)
        if not exprs:
            exprs.append(MatchTextExpr(["content_ltks", "content_sm_ltks"], query, pool))
        res = await thread_pool_exec(
            settings.docStoreConn.search,
            select_fields=fields,
            highlight_fields=[],
            condition=condition,
            match_expressions=exprs,
            order_by=OrderByExpr(),
            offset=0,
            limit=pool,
            index_names=index_nm,
            knowledgebase_ids=[kb.id],
        )
        field_map = settings.docStoreConn.get_fields(res, fields)
    except Exception:
        logging.exception("dataset_nav: compiled-agg retrieval failed for kb=%s", kb.id)
        return False, {"error": "compiled retrieval failed", "code": RetCode.SERVER_ERROR}

    buckets = _nav_bucket_compiled_rows(field_map or {})
    ranked = _nav_rank_compiled_buckets(buckets, top_k)
    if not ranked:
        return True, {"mode": "navigation_tree", "total": 0, "items": []}

    # Compile rows can outlive a deleted document -- the doc-existence check in
    # retrieval() is a fallback, not the primary delete mechanism, and this leg
    # reads the store directly, so it has to apply the check itself.
    alive = await _nav_existing_doc_ids([doc_id for doc_id, _ in ranked])
    ranked = [(d, e) for d, e in ranked if d in alive]
    if not ranked:
        return True, {"mode": "navigation_tree", "total": 0, "items": []}

    summaries = await _nav_doc_summaries(kb, [doc_id for doc_id, _ in ranked])
    # Label each document with the TOC sections that scored for it, so the caller
    # gets an entry point into the document instead of starting
    # navigate_structure from scratch.  Purely additive: it never prunes.
    fact_names_by_doc = buckets.get("fact_names") or {}
    bridge = await _nav_bridge_sections(kb, [n for names in fact_names_by_doc.values() for n in names], doc_scope=doc_scope)
    items = [
        {
            "doc_id": doc_id,
            "score": round(entry["best"], 4),
            "_nav": {
                "doc_id": doc_id,
                "description": summaries.get(doc_id, ""),
                "matched_sections": _nav_matched_sections(bridge, fact_names_by_doc.get(doc_id) or []),
            },
            # Report the value ranking actually used.  Recomputing DocScore here
            # would mix the title and fact hit counts and disagree with ordering.
            "_agg": {"fused": round(entry["score"], 4), "hits": entry["hits"], "legs": sorted(entry["legs"])},
        }
        for doc_id, entry in ranked
    ]
    return True, {"mode": "navigation_tree", "total": len(items), "items": items}


async def _search_layers_fusion(tenant_id, dataset_id, query, top_k, embd_mdl, kb=None, *, compiled=None, doc_scope=None):
    """Combine the chunk leg and the compiled leg into one routing decision.

    The two legs measure different things and are not directly comparable: chunk
    ``_score`` is Infinity's normalized weighted sum, while the compiled leg is a
    raw cosine.  Each leg is therefore normalized by its own maximum before
    being combined, so neither leg's scale can dominate the other.
    """
    ok, chunk_payload = await _search_layers_chunk_agg(tenant_id, dataset_id, query, top_k, embd_mdl, kb, doc_scope=doc_scope)
    if not ok:
        return ok, chunk_payload

    compiled_items = (compiled or {}).get("items") or []
    if not compiled_items:
        # No page_index products (or a raptor KB): the chunk leg alone decides.
        # Tag the items so callers see one shape whichever path produced them.
        for item in chunk_payload.get("items") or []:
            item.setdefault("_agg", {}).setdefault("legs", ["chunk"])
        return ok, chunk_payload

    legs = [("chunk", chunk_payload.get("items") or [], _NAV_FUSION_WEIGHTS["chunk"]), ("compiled", compiled_items, 1.0)]
    fused = _nav_fuse_legs(legs, top_k)

    summaries = await _nav_doc_summaries(kb, [doc_id for doc_id, _ in fused])
    items = [
        {
            "doc_id": doc_id,
            # Reported score stays on the 0..1 scale callers threshold on, so it
            # is taken from the highest-scoring leg rather than the fused value.
            "score": round(info["best"], 4),
            "_nav": {"doc_id": doc_id, "description": summaries.get(doc_id, "")},
            "_agg": {"fused": round(info["fused"], 4), "legs": sorted(info["legs"])},
        }
        for doc_id, info in fused
    ]
    return True, {"mode": "navigation_tree", "total": len(items), "items": items}


def _nav_fuse_legs(legs: list[tuple[str, list, float]], top_k) -> list[tuple[str, dict]]:
    """Fuse per-document leg rankings, each normalized by its own maximum."""
    normalized = []
    for name, items, weight in legs:
        peak = max((float(i.get("score") or 0.0) for i in items), default=0.0)
        if peak <= 0:
            continue
        normalized.append((name, [(i.get("doc_id"), float(i.get("score") or 0.0) / peak * weight) for i in items], weight))

    merged: dict[str, dict] = {}
    for name, entries, _ in normalized:
        for doc_id, value in entries:
            if not doc_id:
                continue
            info = merged.get(doc_id)
            if info is None:
                merged[doc_id] = {"fused": value, "best": value, "legs": {name}}
                continue
            info["fused"] += value
            info["legs"].add(name)
            if value > info["best"]:
                info["best"] = value

    ranked = sorted(merged.items(), key=lambda kv: kv[1]["fused"], reverse=True)
    if top_k is not None and top_k > 0:
        ranked = ranked[:top_k]
    return ranked


def _nav_bucket_compiled_rows(field_map: dict) -> dict[str, dict]:
    """Split fetched compiled rows into a title bucket and a fact bucket.

    The row ``type`` lives inside the ``content_with_weight`` payload —
    ``entity_type_kwd`` is a graphrag field and is not written by the
    compilation path — so rows are binned after the fetch.

    Fact names are kept per document, because the section bridge has to label a
    document with the sections that scored for *it* — a flat list would attach
    one document's sections to another.
    """
    title_bucket: dict[str, dict] = {}
    fact_bucket: dict[str, dict] = {}
    fact_names: dict[str, list[str]] = {}
    for row in field_map.values():
        doc_id = str(row.get("doc_id") or "").strip()
        if not doc_id:
            continue
        try:
            payload = json.loads(str(row.get("content_with_weight") or "{}"))
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        rtype = str(payload.get("type") or "").strip().lower()
        if rtype in _NAV_COMPILED_TITLE_TYPES:
            bucket = title_bucket
        elif rtype in _NAV_COMPILED_FACT_TYPES:
            bucket = fact_bucket
            # Kept for the section bridge, which labels a hit fact with its
            # owning title.  The raw fetch order is the store's relevance order,
            # which is the right priority for choosing which sections to show.
            name = str(payload.get("name") or "").strip()
            if name:
                fact_names.setdefault(doc_id, []).append(name)
        else:
            continue
        score = float(row.get("similarity") or row.get("_score") or 0.0)
        entry = bucket.get(doc_id)
        if entry is None:
            bucket[doc_id] = {"total": score, "best": score, "hits": 1}
            continue
        entry["total"] += score
        entry["hits"] += 1
        if score > entry["best"]:
            entry["best"] = score
    return {"title": title_bucket, "fact": fact_bucket, "fact_names": fact_names}


def _nav_rank_compiled_buckets(buckets: dict, top_k) -> list[tuple[str, dict]]:
    """Fuse the title and fact buckets into one per-document ranking.

    A document hit by both legs is stronger than one hit by either alone, so the
    scores are summed rather than maxed — but each bucket is ranked by its own
    DocScore first, which is what keeps facts from swamping titles.
    """
    merged: dict[str, dict] = {}
    for leg, bucket in (("title", buckets.get("title") or {}), ("fact", buckets.get("fact") or {})):
        weight = _NAV_FUSION_WEIGHTS.get(leg, 1.0)
        for doc_id, entry in bucket.items():
            contribution = _nav_doc_score(entry) * weight
            cur = merged.get(doc_id)
            if cur is None:
                merged[doc_id] = {
                    "score": contribution,
                    "best": entry["best"],
                    "total": entry["total"],
                    "hits": entry["hits"],
                    "legs": {leg},
                }
                continue
            cur["score"] += contribution
            cur["total"] += entry["total"]
            cur["hits"] += entry["hits"]
            cur["legs"].add(leg)
            if entry["best"] > cur["best"]:
                cur["best"] = entry["best"]

    ranked = sorted(merged.items(), key=lambda kv: kv[1]["score"], reverse=True)
    if top_k is not None and top_k > 0:
        ranked = ranked[:top_k]
    return ranked


def _nav_matched_sections(bridge: dict[str, str], fact_names: list[str]) -> list[str]:
    """Titles owning this document's hit facts, in hit order and de-duplicated."""
    sections: list[str] = []
    for name in fact_names:
        title = bridge.get(str(name).strip().lower())
        if title and title not in sections:
            sections.append(title)
    return sections


async def _nav_bridge_sections(kb, fact_names: list[str], doc_scope=None) -> dict[str, str]:
    """Map each hit fact to the title that includes it.

    Routing then answers *which document* and *where in it to look first*:
    the caller gets a per-document entry point instead of starting
    ``navigate_structure`` from scratch.

    The TOC is used here purely as a **label**.  It never prunes the candidate
    set — that is the top-down routing failure mode.  The lookup happens after
    the documents are already chosen.

    Returns ``{fact_name: title_name}``; facts without an owning title are
    omitted.
    """
    if not fact_names or kb is None:
        return {}
    pack = _compiled_index_or_none(kb.tenant_id, kb.id)
    if pack is None:
        return {}
    index_nm, _ = pack

    from ragflow_derived.upstream.doc_store import OrderByExpr

    names = [str(n).strip().lower() for n in fact_names if str(n).strip()]
    # Cap the terms query: a wide IN list is slow and the bridge only needs to
    # label the top hits, not every candidate.
    names = list(dict.fromkeys(names))[:_NAV_BRIDGE_NAMES_LIMIT]

    condition = {
        "compile_kwd": ["page_index"],
        "knowledge_graph_kwd": ["relation"],
        "scope_kwd": ["doc"],
        "to_entity_kwd": names,
    }
    if doc_scope:
        condition["doc_id"] = [str(d) for d in doc_scope if str(d).strip()]

    fields = ["content_with_weight", "from_entity_kwd", "to_entity_kwd", "doc_id"]
    try:
        res = await thread_pool_exec(
            settings.docStoreConn.search,
            select_fields=fields,
            highlight_fields=[],
            condition=condition,
            match_expressions=[],
            order_by=OrderByExpr(),
            offset=0,
            limit=len(names) * _NAV_BRIDGE_FANOUT,
            index_names=index_nm,
            knowledgebase_ids=[kb.id],
        )
        field_map = settings.docStoreConn.get_fields(res, fields)
    except Exception:
        logging.exception("dataset_nav: section bridge lookup failed for kb=%s", kb.id)
        return {}

    bridge: dict[str, str] = {}
    for row in (field_map or {}).values():
        to_name = str(row.get("to_entity_kwd") or "").strip().lower()
        title = str(row.get("from_entity_kwd") or "").strip()
        if not to_name or not title or to_name in bridge:
            continue
        try:
            payload = json.loads(str(row.get("content_with_weight") or "{}"))
        except (TypeError, ValueError):
            continue
        # Only the structural edge counts; semantic relations would mislabel.
        if isinstance(payload, dict) and str(payload.get("type") or "").strip().lower() == _NAV_INCLUDE_RELATION:
            bridge[to_name] = title
    return bridge


async def _nav_existing_doc_ids(doc_ids: list[str]) -> set[str]:
    """Keep only documents that still exist.

    Compiled rows are not necessarily cleaned up when a document is deleted, so
    this leg has to repeat the existence check that ``retrieval`` applies to
    chunk results.
    """
    if not doc_ids:
        return set()
    try:
        return await settings.retriever._existing_doc_ids(list(doc_ids))
    except Exception:
        logging.exception("dataset_nav: doc existence check failed")
        return set(doc_ids)


def _nav_aggregate_chunks(chunks: list) -> dict[str, dict]:
    """Roll chunk hits up per document: total, best and hit count per doc."""
    agg: dict[str, dict] = {}
    for c in chunks:
        doc_id = str(c.get("doc_id") or "").strip()
        if not doc_id:
            continue
        score = float(c.get("similarity") or c.get("score") or 0.0)
        entry = agg.get(doc_id)
        if entry is None:
            agg[doc_id] = {"total": score, "best": score, "hits": 1}
            continue
        entry["total"] += score
        entry["hits"] += 1
        if score > entry["best"]:
            entry["best"] = score
    return agg


def _nav_doc_score(entry: dict) -> float:
    """PageIndex DocScore: hit scores summed, damped by hit count.

    The sum rewards a document matching several chunks; the square-root
    denominator damps it so a long document cannot win on volume alone.
    """
    return entry["total"] / math.sqrt(entry["hits"] + 1)


async def _nav_doc_summaries(kb, doc_ids):
    """Batch-load the nav_doc ``description`` of ``doc_ids`` in one store query.

    Chunk-level routing finds a document without reading any nav row, but the
    caller still needs a label for it.  The nav_doc row already holds the
    document's overall summary, so read them in a single terms query rather
    than making the caller load the document for a label.
    """
    if not doc_ids or kb is None:
        return {}
    pack = _compiled_index_or_none(kb.tenant_id, kb.id)
    if pack is None:
        return {}
    index_nm, _ = pack

    from ragflow_derived.upstream.doc_store import OrderByExpr

    # Single terms query shared by the whole batch; _nav_search would repeat the
    # access check and KB load the caller already performed.
    limit = max(1, min(len(doc_ids), 2000))
    condition = {
        "compile_kwd": [_NAV_COMPILE_KWD],
        "type_kwd": ["nav_doc"],
        "doc_id": [str(d) for d in doc_ids][:limit],
    }
    try:
        res = await thread_pool_exec(
            settings.docStoreConn.search,
            select_fields=_NAV_FIELDS,
            highlight_fields=[],
            condition=condition,
            match_expressions=[],
            order_by=OrderByExpr(),
            offset=0,
            limit=limit,
            index_names=index_nm,
            knowledgebase_ids=[kb.id],
        )
        field_map = settings.docStoreConn.get_fields(res, _NAV_FIELDS)
    except Exception:
        logging.exception("dataset_nav: nav_doc summary lookup failed for kb=%s", kb.id)
        return {}
    summaries = {}
    for row in (field_map or {}).values():
        item = _nav_item(row)
        doc_id = str(item.get("doc_id") or "").strip()
        if doc_id:
            summaries[doc_id] = str(item.get("description") or "").strip()
    return summaries


async def _nav_search_result(tenant_id, dataset_id, query, top_k, embd_mdl, search_fn, **kwargs):
    doc_scope = kwargs.pop("doc_scope", None)
    results = await search_fn(
        tenant_id,
        dataset_id,
        query,
        embd_mdl=embd_mdl,
        top_k=top_k,
        doc_scope=doc_scope,
        **kwargs,
    )
    scope_set = {str(d).strip() for d in doc_scope if str(d).strip()} if doc_scope else None
    items: list[dict] = []
    for r in results:
        raw_doc_id = r.get("doc_id")
        if isinstance(raw_doc_id, str) and raw_doc_id.strip():
            doc_id = raw_doc_id.strip()
        else:
            # Cluster row: pick the first doc_id that's in scope (if a scope
            # is set) so we never leak an out-of-scope doc_id into the results.
            doc_ids = r.get("doc_ids") or []
            if scope_set:
                doc_id = next((str(d).strip() for d in doc_ids if str(d).strip() in scope_set), "")
            else:
                doc_id = str(doc_ids[0]).strip() if doc_ids else ""
        if not doc_id:
            continue
        item = {
            "doc_id": doc_id,
            "score": round(float(r.get("score", 0.0)), 4),
        }
        # Preserve the full nav node info so callers can enrich without a
        # second ES round-trip.  Clusters have doc_id="" but carry name.
        if r.get("name") or r.get("description"):
            item["_nav"] = r
        items.append(item)
    return items


async def _search_layers_chunks(tenant_id, dataset_id, query, top_k, embd_mdl, kb, *, doc_scope=None):
    from ragflow_derived.full_runtime import settings

    tenant_ids = [tenant_id]

    kwargs = {}
    if doc_scope:
        kwargs["doc_ids"] = [str(d) for d in doc_scope if str(d).strip()]

    # Here page_size IS the result set: chunks are returned as evidence, not
    # aggregated into documents.  Keep it at the historical fetch size — raising
    # it to the chunk_agg pool inflated the evidence pool ~7x (25 -> 191 chunks
    # per question), which pushed every downstream LLM prompt and blew the
    # 180s per-question research budget.
    fetch_k = max(top_k, 10) * 3 if top_k is not None else 1024
    try:
        ranks = await settings.retriever.retrieval(
            query,
            embd_mdl,
            tenant_ids,
            [dataset_id],
            1,
            fetch_k,
            0.0,
            _NAV_CHUNK_AGG_VEC_WEIGHT,
            # The candidate pool only has to cover what is returned; it used to
            # sit at the 64 default while page_size grew with top_k, which
            # raises once page * page_size exceeds it.
            rerank_candidates_count=max(_NAV_CHUNK_AGG_POOL, fetch_k),
            # knn_top_k is left at its default: narrowing it to top_k caps how
            # many neighbours the vector leg feeds into fusion.
            # Chunk mode reports raw chunks; compiled rows are served by their
            # own tools, so they must not be attributed to a document here.
            must_not={"exists": "compile_kwd"} if _NAV_CHUNK_AGG_EXCLUDE_COMPILED else None,
            **kwargs,
        )
    except Exception:
        return False, {"error": "chunk retrieval failed", "code": RetCode.SERVER_ERROR}

    doc_scores: dict[str, float] = {}
    for c in ranks.get("chunks", []):
        doc_id = (c.get("doc_id") or "").strip()
        score = float(c.get("similarity") or c.get("score") or 0.0)
        if doc_id and score > doc_scores.get(doc_id, -1.0):
            doc_scores[doc_id] = score

    items = sorted(
        ({"doc_id": d, "score": round(s, 4)} for d, s in doc_scores.items()),
        key=lambda x: x["score"],
        reverse=True,
    )
    if top_k is not None and top_k > 0:
        items = items[:top_k]

    return True, {"mode": "chunk", "total": len(items), "items": items}


async def _search_layers_all(tenant_id, dataset_id, query, top_k, embd_mdl, kb, search_fn, *, doc_scope=None):
    """Run all modes and return the union of doc_ids, with best score per doc."""
    import asyncio as _asyncio

    # With _NAV_TREE_ROUTER="chunk_agg" the navigation_tree leg already reads the
    # chunk index, so it overlaps the chunk leg below.  The union still dedups by
    # doc_id and keeps the best score, so the overlap costs one extra retrieval
    # without affecting the result — mode="all" is for comparison, not production.
    result_lists = await _asyncio.gather(
        _search_layers_nav_docs(tenant_id, dataset_id, query, top_k, embd_mdl, search_fn, doc_scope=doc_scope),
        _search_layers_nav_clusters(tenant_id, dataset_id, query, top_k, embd_mdl, search_fn, doc_scope=doc_scope),
        _search_layers_navigation_tree(tenant_id, dataset_id, query, top_k, embd_mdl, kb, doc_scope=doc_scope),
        _search_layers_chunks(tenant_id, dataset_id, query, top_k, embd_mdl, kb, doc_scope=doc_scope),
        return_exceptions=True,
    )

    doc_scores: dict[str, dict] = {}
    for result in result_lists:
        if isinstance(result, Exception):
            continue
        ok, data = result
        if not ok:
            continue
        for item in data.get("items", []):
            doc_id = item.get("doc_id", "")
            score = float(item.get("score", 0.0))
            # Clusters have no doc_id; key by name so they survive dedup.
            key = doc_id or item.get("_nav", {}).get("name", "")
            if key and score > doc_scores.get(key, {}).get("score", -1.0):
                doc_scores[key] = item

    items = sorted(
        doc_scores.values(),
        key=lambda x: x["score"],
        reverse=True,
    )
    if top_k is not None and top_k > 0:
        items = items[:top_k]

    return True, {"mode": "all", "total": len(items), "items": items}


async def _enrich_nav_items(dataset_id: str, tenant_id: str, items: list[dict]) -> list[dict]:
    """Enrich ``{doc_id, score}`` items with full nav node info.

    Items that already carry a ``_nav`` payload (from nav_doc/nav_cluster/
    navigation_tree search) are shaped in-process.  Items without it (e.g.
    chunk hits) are batch-fetched from ES by ``doc_id``.

    For every matched doc, its parent cluster is also resolved and prepended
    to the result set (cluster score = max child score) so the frontend can
    highlight both the doc and its containing cluster in the tree.
    """
    from ragflow_derived.upstream.doc_store import OrderByExpr

    if not items:
        return items

    _, kb = KnowledgebaseService.get_by_id(dataset_id)
    pack = _compiled_index_or_none(kb.tenant_id, dataset_id) if kb else None
    if pack is None:
        return items
    index_nm, _ = pack

    # Phase 1: shape items that already have _nav; collect doc_ids for chunk-only hits.
    doc_items: list[dict] = []
    missing_doc_ids: list[str] = []
    for it in items:
        nav = it.get("_nav")
        if nav:
            is_cluster = nav.get("type") == "nav_cluster"
            item = {
                "name": nav.get("name") or "",
                "description": nav.get("description") or "",
                "keywords": nav.get("keywords") or [],
                "entities": nav.get("entities") or [],
                "graph_content": nav.get("graph_content") or "",
                "doc_count": nav.get("doc_count") or (0 if is_cluster else 1),
                "type": "cluster" if is_cluster else "doc",
                "doc_id": nav.get("doc_id"),
                "has_children": is_cluster,
                "score": it.get("score", 0.0),
            }
            # Capture parent_kwd for docs so we can fetch the parent cluster.
            if not is_cluster:
                pn = nav.get("parent_kwd") or []
                if isinstance(pn, (list, tuple, set)):
                    pn = next(iter(pn), "")
                if pn:
                    item["_parent_kwd"] = str(pn)
            doc_items.append(item)
        else:
            doc_id = it.get("doc_id", "")
            if doc_id:
                missing_doc_ids.append(doc_id)
            doc_items.append(it)

    # Phase 2: batch-fetch nav_doc rows for chunk-only hits (need parent_kwd).
    all_doc_ids = missing_doc_ids + [d["doc_id"] for d in doc_items if d.get("type") == "doc" and d.get("doc_id") and not d.get("_parent_kwd")]
    nav_rows_by_doc_id: dict[str, dict] = {}
    if all_doc_ids:
        try:
            res = settings.docStoreConn.search(
                select_fields=_NAV_FIELDS,
                highlight_fields=[],
                condition={"compile_kwd": [_NAV_COMPILE_KWD], "doc_id": all_doc_ids},
                match_expressions=[],
                order_by=OrderByExpr(),
                offset=0,
                limit=len(all_doc_ids),
                index_names=index_nm,
                knowledgebase_ids=[dataset_id],
            )
            field_map = settings.docStoreConn.get_fields(res, _NAV_FIELDS)
        except Exception:
            logging.exception("_enrich_nav_items: docStore search failed for kb=%s", dataset_id)
            field_map = None

        for row in (field_map or {}).values():
            did = row.get("doc_id") or row.get("name") or ""
            if isinstance(did, (list, tuple, set)):
                did = next(iter(did), "")
            if did:
                nav_rows_by_doc_id[str(did)] = row

    # Enrich chunk-only items with nav info + parent_kwd.
    for i, it in enumerate(doc_items):
        if it.get("type"):
            continue
        doc_id = it.get("doc_id", "")
        row = nav_rows_by_doc_id.get(doc_id)
        if row:
            nav_item = _nav_item(row)
            nav_item["score"] = it.get("score", 0.0)
            nav_item["_parent_kwd"] = _first_str(row.get("parent_kwd"))
            doc_items[i] = nav_item

    # Phase 3: get parent_kwd for _nav doc items (search_dataset_nav strips it).
    nav_doc_names = [d["name"] for d in doc_items if d.get("type") == "doc" and not d.get("_parent_kwd") and d.get("name")]
    if nav_doc_names:
        name_field = "name.keyword" if settings.DOC_ENGINE.lower() in {"elasticsearch", "opensearch"} else "name"
        try:
            res = settings.docStoreConn.search(
                select_fields=["name", "parent_kwd"],
                highlight_fields=[],
                condition={"compile_kwd": [_NAV_COMPILE_KWD], "type_kwd": ["nav_doc"], name_field: nav_doc_names},
                match_expressions=[],
                order_by=OrderByExpr(),
                offset=0,
                limit=len(nav_doc_names),
                index_names=index_nm,
                knowledgebase_ids=[dataset_id],
            )
            field_map = settings.docStoreConn.get_fields(res, ["name", "parent_kwd"])
        except Exception:
            field_map = None

        parent_by_name: dict[str, str] = {}
        for row in (field_map or {}).values():
            nm = _first_str(row.get("name"))
            pn = _first_str(row.get("parent_kwd"))
            if nm and pn:
                parent_by_name[nm] = pn

        for it in doc_items:
            if it.get("type") == "doc" and not it.get("_parent_kwd"):
                it["_parent_kwd"] = parent_by_name.get(it.get("name", ""), "")

    # Phase 4: batch-fetch parent cluster rows.
    parent_names = {it["_parent_kwd"] for it in doc_items if it.get("_parent_kwd")}
    cluster_by_name: dict[str, dict] = {}
    if parent_names:
        name_field = "name.keyword" if settings.DOC_ENGINE.lower() in {"elasticsearch", "opensearch"} else "name"
        try:
            res = settings.docStoreConn.search(
                select_fields=_NAV_FIELDS,
                highlight_fields=[],
                condition={"compile_kwd": [_NAV_COMPILE_KWD], "type_kwd": ["nav_cluster"], name_field: list(parent_names)},
                match_expressions=[],
                order_by=OrderByExpr(),
                offset=0,
                limit=len(parent_names),
                index_names=index_nm,
                knowledgebase_ids=[dataset_id],
            )
            field_map = settings.docStoreConn.get_fields(res, _NAV_FIELDS)
        except Exception:
            field_map = None

        for row in (field_map or {}).values():
            nm = _first_str(row.get("name"))
            if nm:
                cluster_by_name[nm] = _nav_item(row)

    # Phase 5: build result — clusters (max child score) then docs.
    cluster_scores: dict[str, float] = {}
    doc_parent: dict[int, str] = {}
    for i, it in enumerate(doc_items):
        pn = it.pop("_parent_kwd", "")
        doc_parent[i] = pn
        if pn and pn in cluster_by_name:
            cluster_scores[pn] = max(cluster_scores.get(pn, 0.0), it.get("score", 0.0))

    clusters = [{**nav_item, "score": round(cluster_scores.get(name, 0.0), 4)} for name, nav_item in cluster_by_name.items()]
    cluster_names = {c["name"] for c in clusters}

    # A matched doc whose parent cluster is also in the result is already
    # represented by that cluster's tree — don't surface it as a second,
    # separate root.  This keeps a search that hits both a cluster and its
    # child doc down to a single nav_cluster tree instead of two roots.
    standalone_docs = [it for i, it in enumerate(doc_items) if it.get("type") != "cluster" and doc_parent.get(i) not in cluster_names]
    return clusters + standalone_docs


