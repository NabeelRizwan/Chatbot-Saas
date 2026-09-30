# Copyright 2024 The InfiniFlow Authors. All Rights Reserved.
# Modifications: full-passage SaaS ranking integration, 2026.
# Licensed under Apache-2.0; see LICENSE-APACHE-2.0.
"""Scoped SaaS retrieval composition; final answer generation stays unchanged.

Title/prose assembly and stable score order adapt RAGFlow generator.py/search.py
at a024bea0cd93f39e6652a42bf84dd20c55bc560b. SaaS source headers and scopes retain
the host platform's format. ORM source objects are never copied or rewritten.
"""

from collections.abc import Mapping
import json
from math import isfinite

from services.structural_chunking import count_tokens

from .client import BGEClient
from .config import Config, CANDIDATES_PER_FOCUS, CONTEXT_MAX_CHARS, NATIVE_POOL_SIZE, SOURCE_TOKEN_BUDGET, policy_identity
from .errors import CombinedRetrievalError
from .merge import interleave
from .planner import focused_queries


def value(obj, key, default=None):
    return obj.get(key, default) if isinstance(obj, Mapping) else getattr(obj, key, default)


def identity(item):
    doc_id, chunk_id = value(item.get("document"), "id"), value(item.get("chunk"), "id")
    if type(doc_id) is not int or doc_id <= 0 or type(chunk_id) is not int or chunk_id <= 0:
        # This path admits stored source chunks only, not legacy generated
        # structured-evidence snippets with negative synthetic IDs.
        raise CombinedRetrievalError("source_identity_invalid")
    return doc_id, chunk_id


def source_snapshot(item):
    chunk, document = item["chunk"], item["document"]
    snapshot = {"chunk": {k: value(chunk, k) for k in (
        "id", "document_id", "organization_id", "bot_id", "content", "metadata_json",
        "content_hash", "chunk_index", "token_count", "status", "website_id", "crawl_id",
        "document_version_id", "structure_revision_id",
        "embedding_provider", "embedding_model", "embedding_version")},
        "document": {k: value(document, k) for k in (
            "id", "organization_id", "bot_id", "title", "filename", "source_url", "canonical_url",
            "metadata_json", "source_type", "version", "website_id", "crawl_id", "content_hash",
            "status", "processing_status")}}
    try:
        # Independent value snapshot catches identity drift even when the ORM
        # identity map returns the same Python object in a later retrieval lane.
        return json.dumps(snapshot, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (ValueError, TypeError) as error:
        raise CombinedRetrievalError("source_metadata_invalid") from error


def _scope(bot, contract):
    execution = value(contract, "execution")
    hard = value(execution, "hard_scope")
    if hard is None or value(hard, "bot_id") != value(bot, "id") or value(hard, "organization_id") != value(bot, "organization_id"):
        raise CombinedRetrievalError("source_scope_invalid")
    if value(bot, "organization_id") is None:
        raise CombinedRetrievalError("source_scope_invalid")
    return hard


def _validate_rows(rows, bot, contract, hard):
    if not isinstance(rows, list) or len(rows) > NATIVE_POOL_SIZE:
        raise CombinedRetrievalError("native_candidate_contract_invalid")
    hard_ids = value(hard, "authorized_document_ids")
    source_ids = value(hard, "authorized_source_ids")
    effective = value(value(value(contract, "execution"), "scope_decision"), "effective_document_ids")
    permitted = value(contract, "permitted_document_ids")
    versions = {row[0]: (row[1], row[2]) for row in value(hard, "active_document_versions", ())}
    profile = value(hard, "embedding_profile")
    seen = set()
    for item in rows:
        if not isinstance(item, Mapping) or "chunk" not in item or "document" not in item:
            raise CombinedRetrievalError("source_shape_invalid")
        key = identity(item)
        if key in seen:
            raise CombinedRetrievalError("source_duplicate_identity")
        seen.add(key)
        chunk, document = item["chunk"], item["document"]
        if value(hard, "empty", False):
            raise CombinedRetrievalError("source_scope_escape")
        for scoped in (hard_ids, effective, permitted):
            if scoped is not None and key[0] not in scoped:
                raise CombinedRetrievalError("source_scope_escape")
        for source in (chunk, document):
            if value(source, "organization_id") != value(bot, "organization_id") or value(source, "bot_id") != value(bot, "id"):
                raise CombinedRetrievalError("source_tenant_escape")
            if value(source, "status") != "ready":
                raise CombinedRetrievalError("source_lifecycle_invalid")
        if value(document, "processing_status") != "completed" or value(chunk, "document_id") != key[0]:
            raise CombinedRetrievalError("source_document_invalid")
        if value(chunk, "crawl_id") != value(document, "crawl_id"):
            raise CombinedRetrievalError("source_version_mismatch")
        if value(chunk, "website_id") != value(document, "website_id"):
            raise CombinedRetrievalError("source_version_mismatch")
        if source_ids is not None and value(document, "website_id") not in source_ids:
            raise CombinedRetrievalError("source_scope_escape")
        if versions and versions.get(key[0]) != (value(document, "version"), value(document, "crawl_id")):
            raise CombinedRetrievalError("source_version_mismatch")
        if profile is not None and any(value(chunk, "embedding_" + field) != value(profile, field)
                                       for field in ("provider", "model", "version")):
            raise CombinedRetrievalError("source_embedding_profile_mismatch")
        text = value(chunk, "content")
        if not isinstance(text, str) or not text.strip():
            raise CombinedRetrievalError("source_content_invalid")
        title = value(document, "title") or value(document, "filename") or ""
        if not isinstance(title, str):
            raise CombinedRetrievalError("source_title_invalid")


def _add_sources(by_id, snapshots, rows):
    for item in rows:
        key, snapshot = identity(item), source_snapshot(item)
        if key in by_id and snapshots[key] != snapshot:
            raise CombinedRetrievalError("source_identity_changed")
        if key not in by_id:
            # Keep ORM objects intact, and do not add scoring fields to them.
            by_id[key], snapshots[key] = dict(item), snapshot


def format_context(items, budget_chars):
    """Admit a ranked prefix of complete sources, with exact host source labels.

    The first block that exceeds either ceiling stops admission. Source token
    accounting is the offline, verified cl100k tokenizer. Header/separator text
    additionally counts against the platform's character ceiling. No fallback
    word estimate, partial passage, source reordering or remote asset fetching.
    """
    if type(budget_chars) is not int or budget_chars < 0:
        raise CombinedRetrievalError("context_budget_invalid")
    budget_chars = min(budget_chars, CONTEXT_MAX_CHARS)
    selected, blocks, source_tokens, used_chars = [], [], 0, 0
    for item in items:
        document, chunk = item["document"], item["chunk"]
        text = value(chunk, "content")
        if not isinstance(text, str) or not text.strip():
            raise CombinedRetrievalError("source_content_invalid")
        title = value(document, "title") or value(document, "filename") or ""
        url = value(document, "source_url") or ""
        header = (f"### Source: {title} | URL: {url}" if title and url else
                  f"### Source: {title}" if title else f"### URL: {url}" if url else "")
        block = header + "\n" + text if header else text
        try:
            tokens = count_tokens(text)
        except Exception as error:
            raise CombinedRetrievalError("tokenizer_unavailable") from error
        if type(tokens) is not int or tokens < 1:
            raise CombinedRetrievalError("tokenizer_invalid_count")
        cost = len(block) + (7 if blocks else 0)
        if source_tokens + tokens > SOURCE_TOKEN_BUDGET or used_chars + cost > budget_chars:
            break
        selected.append(item)
        blocks.append(block)
        source_tokens += tokens
        used_chars += cost
    return selected, "\n\n---\n\n".join(blocks)


def collect_evidence(*, bot, question, query_contract, trace, retrieve_native, budget_chars):
    """Collect fresh scoped lanes, rank full passages, and fit whole evidence.

    ``retrieve_native(query, query_contract, 128)`` owns current database filters
    and returns stored chunk/document rows; planner output cannot alter scope.
    No database sessions, provider credentials or ORM objects enter a new worker.
    """
    if not isinstance(question, str) or not question.strip():
        raise CombinedRetrievalError("query_invalid")
    config = Config.from_env()
    hard = _scope(bot, query_contract)
    if trace is not None:
        trace.diagnostics["combined_rag"] = {**policy_identity(), "cacheable": True}
    if value(hard, "empty", False):
        if trace is not None:
            trace.diagnostics["combined_rag"].update(cacheable=False, empty_scope=True)
        return [], ""
    raw = retrieve_native(question, query_contract, NATIVE_POOL_SIZE)
    _validate_rows(raw, bot, query_contract, hard)
    queries = focused_queries(bot, question, config, trace)
    by_id, snapshots = {}, {}
    _add_sources(by_id, snapshots, raw)
    focused = []
    for query in queries:
        rows = raw if query == question else retrieve_native(query, query_contract, NATIVE_POOL_SIZE)
        _validate_rows(rows, bot, query_contract, hard)
        _add_sources(by_id, snapshots, rows)
        focused.append((query, rows))
    if raw and not any(rows for _query, rows in focused):
        # An unhelpful decomposition must not bypass the required learned
        # ranking stage. Use the complete original query with the native pool;
        # this is query-plan recovery, not an old-ranker or outage fallback.
        focused = [(question, raw)]
        if trace is not None:
            trace.diagnostics["combined_rag"].update(cacheable=False, empty_focus_fallback=True)
    scorer, lanes, pairs = BGEClient(config), [], 0
    for query, rows in focused:
        candidates = rows[:CANDIDATES_PER_FOCUS]
        if not candidates:
            continue
        documents = [f"Title: {value(row['document'], 'title') or value(row['document'], 'filename') or ''}\nContent:\n{value(row['chunk'], 'content')}" for row in candidates]
        scores = scorer.score(query, documents)
        if (not isinstance(scores, list) or len(scores) != len(candidates) or
                any(type(v) not in (int, float) or not isfinite(v) for v in scores)):
            raise CombinedRetrievalError("reranker_invalid_score")
        indices = sorted(range(len(candidates)), key=lambda i: -scores[i])
        lanes.append([identity(candidates[i]) for i in indices])
        pairs += len(candidates)
    # Same original-query tail as the tested policy; focused searches never
    # erase original candidates or rewrite their source identity.
    order = list(dict.fromkeys(interleave(lanes) + list(by_id)))
    ranked = [by_id[key] for key in order]
    for key, row in by_id.items():
        if snapshots[key] != source_snapshot(row):
            raise CombinedRetrievalError("source_identity_changed")
    selected, context = format_context(ranked, budget_chars)
    if trace is not None:
        trace.diagnostics["combined_rag"].update(
            native_candidates=len(raw), candidates=len(ranked), scored_pairs=pairs,
            lanes=len(lanes), selected=len(selected), context_chars=len(context))
    if ranked and not selected:
        raise CombinedRetrievalError("context_budget_exhausted")
    return selected, context
