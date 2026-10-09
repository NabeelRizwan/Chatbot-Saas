"""Bounded adjacent context using LlamaIndex's official node postprocessor.

PrevNextNodePostprocessor (MIT) discovers bounded adjacent nodes. This adapter checks
their provenance, reserves selected evidence, and fits optional context into the
remaining budget. No generative model or provider is used.

https://github.com/run-llama/llama_index/blob/main/llama-index-core/llama_index/core/postprocessor/node.py
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.postprocessor import PrevNextNodePostprocessor
from llama_index.core.schema import NodeRelationship, NodeWithScore, TextNode
from llama_index.core.storage.docstore import SimpleDocumentStore

CONTEXT_BUILDER_VERSION = "bounded-source-context-v4"


class ContextBudgetExceeded(ValueError):
    """Selected whole passages cannot fit the requested context budget."""


def fit_evidence_context(ranked, source_nodes, documents, tokenizer, max_tokens, max_count):
    """Reserve whole cores before expansion; report every budget omission.

    Source validation errors remain fatal. Only a typed budget overflow permits
    selection of fewer cores, preserving rank order and complete source text.
    """
    try:
        return build_evidence_context(ranked, source_nodes, documents, tokenizer, max_tokens, max_count)
    except ContextBudgetExceeded:
        accepted, omitted = [], []
        for item in ranked[:max_count]:
            try:
                build_evidence_context([*accepted, item], source_nodes, documents, tokenizer,
                                       max_tokens, max_count, expand_neighbors=False)
            except ContextBudgetExceeded:
                omitted.append(item.node.node_id)
            else:
                accepted.append(item)
        if ranked and not accepted:
            raise ContextBudgetExceeded('No complete evidence passage fits the context budget.')
        result = build_evidence_context(accepted, source_nodes, documents, tokenizer, max_tokens, max_count)
        result['audit']['omitted_core_node_ids'] = omitted
        result['audit']['budget_policy'] = 'whole cores in selection order; optional neighbors use remaining space'
        return result


def _field(document: Any, key: str, default: Any = None) -> Any:
    if isinstance(document, Mapping):
        return document.get(key, default)
    return getattr(document, key, getattr(document, "metadata", {}).get(key, default))


def _encoder(tokenizer: Any):
    if callable(tokenizer):
        return tokenizer

    def encode(text: str):
        try:
            return tokenizer.encode(text, disallowed_special=())
        except TypeError:
            return tokenizer.encode(text)

    return encode


def _validate(node: TextNode, documents: Mapping[str, Any]) -> tuple[str, str]:
    source_id = str(node.metadata.get("source_id", ""))
    if source_id not in documents:
        raise ValueError("Source node refers to an unavailable source document.")
    text = _field(documents[source_id], "text")
    start, end = node.start_char_idx, node.end_char_idx
    if not isinstance(text, str) or not isinstance(start, int) or not isinstance(end, int):
        raise ValueError("Source node has no verifiable text or offsets.")
    if not 0 <= start < end <= len(text) or text[start:end] != node.text:
        raise ValueError("Source node does not match its original document slice.")
    url = _field(documents[source_id], "url")
    if url and node.metadata.get("url") != url:
        raise ValueError("Source node URL does not match its original document.")
    _table_headers(node, text)
    return source_id, text


def _table_headers(node: TextNode, source_text: str) -> list[dict[str, Any]]:
    """Validate separately sourced table labels without altering a row span."""
    metadata = node.metadata
    keys = ("table_header", "table_header_start_char_idx", "table_header_end_char_idx",
            "table_start_char_idx", "table_end_char_idx")
    if not any(key in metadata for key in keys):
        return []
    header = metadata.get("table_header")
    start, end = metadata.get(keys[1]), metadata.get(keys[2])
    table_start, table_end = metadata.get(keys[3]), metadata.get(keys[4])
    if (not isinstance(header, str) or not header.strip()
            or not all(isinstance(value, int) and not isinstance(value, bool)
                       for value in (start, end, table_start, table_end))
            or not 0 <= table_start == start < end <= table_end <= len(source_text)
            or source_text[start:end] != header
            or not table_start <= node.start_char_idx < node.end_char_idx <= table_end):
        raise ValueError("Table header does not match its original source span.")
    return [{"start_char": start, "end_char": end, "text": header}]


def _touches(text: str, left_end: int, right_start: int) -> bool:
    return right_start <= left_end or not text[left_end:right_start].strip()


def _subject(node: TextNode) -> str:
    return str(node.metadata.get("subject_source_id") or node.metadata.get("source_id", ""))


def _merge(intervals: list[dict[str, Any]], documents: Mapping[str, Any], priority: list[str]):
    merged: list[dict[str, Any]] = []
    for source_id in priority:
        text = _field(documents[source_id], "text")
        group = sorted((item for item in intervals if item["source_id"] == source_id),
                       key=lambda item: (item["start"], item["end"]))
        source_segments: list[dict[str, Any]] = []
        for interval in group:
            if (source_segments
                    and source_segments[-1]["subject_source_id"] == interval["subject_source_id"]
                    and _touches(text, source_segments[-1]["end"], interval["start"])):
                current = source_segments[-1]
                current["end"] = max(current["end"], interval["end"])
                for field in ("core_node_ids", "expanded_node_ids", "sections", "evidence_roles"):
                    current[field] = list(dict.fromkeys([*current[field], *interval[field]]))
                for header in interval["table_headers"]:
                    if header not in current["table_headers"]:
                        current["table_headers"].append(header)
                current["scores"].extend(interval["scores"])
            else:
                source_segments.append({key: value.copy() if isinstance(value, list) else value
                                        for key, value in interval.items()})
        merged.extend(source_segments)
    return merged


def _render(intervals, documents, priority, encode):
    evidence, blocks = [], []
    for segment in _merge(intervals, documents, priority):
        if not segment["core_node_ids"]:
            raise ValueError("Adjacent context must remain attached to selected evidence.")
        source_id = segment["source_id"]
        document = documents[source_id]
        source_text = _field(document, "text")
        text = source_text[segment["start"]:segment["end"]]
        title, url = _field(document, "title", source_id), _field(document, "url", "")
        subject_id = segment["subject_source_id"]
        subject_title = _field(documents.get(subject_id, {}), "title", segment["subject_title"])
        citation_id = str(len(evidence) + 1)
        section = segment["sections"][0] if segment["sections"] else ""
        headers = [{**header, "source_id": source_id, "url": url,
                    "included_in_context": not (
                        segment["start"] <= header["start_char"] + len(header["text"]) - len(header["text"].lstrip())
                        and header["end_char"] - len(header["text"]) + len(header["text"].rstrip()) <= segment["end"])}
                   for header in sorted(segment["table_headers"], key=lambda item: item["start_char"])]
        header_context = "".join(
            f"Table header (source characters {header['start_char']}–{header['end_char']}):\n{header['text'].rstrip()}\n"
            for header in headers if header["included_in_context"]
        )
        node_id = "context-" + hashlib.sha256(
            f"{source_id}:{subject_id}:{segment['start']}:{segment['end']}:{header_context}:{text}".encode("utf-8")
        ).hexdigest()
        item = {
            "citation_id": citation_id, "node_id": node_id, "source_id": source_id,
            "title": title, "section": section, "url": url, "text": text,
            "subject_source_id": subject_id, "subject_title": subject_title,
            "start_char": segment["start"], "end_char": segment["end"],
            "source_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
            "score": max(segment["scores"], default=0.0),
            "core_node_ids": segment["core_node_ids"],
            "expanded_node_ids": segment["expanded_node_ids"],
            "sections": segment["sections"],
            "table_headers": headers,
            "evidence_roles": segment['evidence_roles'],
        }
        evidence.append(item)
        subject_label = f"Subject: {subject_title}\n" if subject_id != source_id else ""
        roles = ', '.join(segment['evidence_roles'])
        role_label = f"Structural evidence roles: {roles}\n" if roles else ''
        blocks.append(f"[Source {citation_id}] {title}\n{subject_label}Section: {section}\n{role_label}URL: {url}\n{header_context}{text}")
    context = "\n\n".join(blocks)
    return {"evidence": evidence, "context": context, "context_tokens": len(encode(context))}


def build_evidence_context(
    selected: Sequence[NodeWithScore],
    source_nodes: Mapping[str, TextNode],
    documents: Mapping[str, Any],
    context_tokenizer: Any,
    max_tokens: int,
    max_selected_count: int,
    *,
    max_neighbor_tokens: int = 128,
    expand_neighbors: bool = True,
    neighbor_hops: int = 3,
) -> dict[str, Any]:
    """Reserve selected spans, then add up to three adjacent nodes per direction.

    Core evidence is never silently removed or truncated. If it cannot fit, this
    raises ValueError so the caller must explicitly change selection or budget.
    Neighbors receive at most ``max_neighbor_tokens`` each. For a long neighbor,
    official SentenceSplitter supplies its nearest complete chunk. Opportunities
    are distance-first across selected cores and both directions. Expansion cannot
    cross a source/subject boundary or omitted text gap, including a clipped long neighbor.

    Adjacent/overlapping ranges become one exact source slice. Source groups keep
    their first selected rank, with ranges ordered by source position within each
    group. Synthetic context IDs are accompanied by original core/neighbor IDs.
    """
    if max_tokens < 1 or max_selected_count < 0 or max_neighbor_tokens < 1:
        raise ValueError("Context and neighbor budgets must be positive; selected count must be nonnegative.")
    if not isinstance(neighbor_hops, int) or isinstance(neighbor_hops, bool) or not 0 <= neighbor_hops <= 3:
        raise ValueError("Neighbor hops must be an integer from zero through three.")
    encode = _encoder(context_tokenizer)
    by_id = {}
    for item in selected:
        by_id.setdefault(item.node.node_id, item)
    unique = list(by_id.values())
    if len(unique) > max_selected_count:
        raise ValueError("Selected evidence exceeds the declared maximum; no core was removed.")
    priority, cores, intervals = [], [], []
    for item in unique:
        if item.node.node_id not in source_nodes:
            raise ValueError("Selected model node has no corresponding raw source node.")
        raw = source_nodes[item.node.node_id]
        source_id, source_text = _validate(raw, documents)
        if source_id not in priority:
            priority.append(source_id)
        cores.append(raw)
        intervals.append({
            "source_id": source_id, "start": raw.start_char_idx, "end": raw.end_char_idx,
            "subject_source_id": _subject(raw),
            "subject_title": raw.metadata.get("subject_title", raw.metadata.get("title", source_id)),
            "core_node_ids": [raw.node_id], "expanded_node_ids": [],
            "sections": [raw.metadata["section"]] if raw.metadata.get("section") else [],
            "evidence_roles": [raw.metadata.get('evidence_role','UNKNOWN')],
            "scores": [float(item.score)] if item.score is not None else [],
            "table_headers": _table_headers(raw, source_text),
        })
    result = _render(intervals, documents, priority, encode)
    if result["context_tokens"] > max_tokens:
        raise ContextBudgetExceeded(
            f"Selected core evidence needs {result['context_tokens']} context tokens, exceeding {max_tokens}; "
            "no comparison source or core passage was silently dropped."
        )
    audit = {
        "builder": CONTEXT_BUILDER_VERSION,
        "selected_core_node_ids": [node.node_id for node in cores],
        "core_context_tokens": result["context_tokens"],
        "max_neighbor_tokens": max_neighbor_tokens,
        "neighbor_hops": neighbor_hops,
        "accepted_neighbors": [], "rejected_neighbors": [],
    }
    if not expand_neighbors or not cores or not neighbor_hops:
        return {**result, "audit": audit}

    # Validate every edge before exposing the bounded graph to the official
    # postprocessor. Sanitized copies prevent malformed second/third-hop links
    # reaching the document store; persisted source relationships stay intact.
    local_nodes, neighbor_pairs = {}, []

    def store_safe(node):
        if node.node_id not in local_nodes:
            safe = node.model_copy(deep=True)
            safe.relationships.pop(NodeRelationship.PREVIOUS, None)
            safe.relationships.pop(NodeRelationship.NEXT, None)
            local_nodes[node.node_id] = safe
        return local_nodes[node.node_id]

    directions = ((NodeRelationship.PREVIOUS, "previous"), (NodeRelationship.NEXT, "next"))
    walkers = {(core.node_id, direction): core for core in cores for _, direction in directions}
    for core in cores:
        store_safe(core)
    for distance in range(1, neighbor_hops + 1):
        for core in cores:
            source_id, source_text = _validate(core, documents)
            for relation, direction in directions:
                current = walkers[(core.node_id, direction)]
                if current is None:
                    continue
                link = current.relationships.get(relation)
                if not link:
                    walkers[(core.node_id, direction)] = None
                    continue
                neighbor_id = link.node_id
                neighbor = source_nodes.get(neighbor_id)
                reason = None
                if neighbor is None:
                    reason = "missing_source_node"
                else:
                    try:
                        neighbor_source, _ = _validate(neighbor, documents)
                        if neighbor_source != source_id:
                            reason = "different_source"
                        elif _subject(neighbor) != _subject(core):
                            reason = "different_subject"
                        elif direction == "previous" and not (
                            neighbor.start_char_idx < current.start_char_idx
                            and _touches(source_text, neighbor.end_char_idx, current.start_char_idx)
                        ):
                            reason = "not_adjacent_previous"
                        elif direction == "next" and not (
                            neighbor.end_char_idx > current.end_char_idx
                            and _touches(source_text, current.end_char_idx, neighbor.start_char_idx)
                        ):
                            reason = "not_adjacent_next"
                    except ValueError:
                        reason = "invalid_source_provenance"
                if reason:
                    walkers[(core.node_id, direction)] = None
                    audit["rejected_neighbors"].append({
                        "core_node_id": core.node_id, "node_id": neighbor_id,
                        "direction": direction, "distance": distance, "reason": reason,
                    })
                else:
                    store_safe(neighbor)
                    store_safe(current).relationships[relation] = link
                    walkers[(core.node_id, direction)] = neighbor
                    neighbor_pairs.append((distance, core, neighbor, direction))
    docstore = SimpleDocumentStore()
    docstore.add_documents(list(local_nodes.values()))
    expanded = PrevNextNodePostprocessor(docstore=docstore, num_nodes=neighbor_hops, mode="both").postprocess_nodes(
        [NodeWithScore(node=local_nodes[core.node_id]) for core in cores]
    )
    permitted = {item.node.node_id for item in expanded}
    splitter = SentenceSplitter(chunk_size=max_neighbor_tokens, chunk_overlap=0, tokenizer=encode)
    considered = set()
    # Pairs were discovered breadth-first: distance, original core rank, then
    # previous/next. Distant context cannot consume budget before every core has
    # had its nearer opportunities in both directions.
    for distance, core, neighbor, direction in neighbor_pairs:
        if neighbor.node_id not in permitted:
            continue
        source_id = str(core.metadata["source_id"])
        source_text = _field(documents[source_id], "text")
        start, end = neighbor.start_char_idx, neighbor.end_char_idx
        if direction == "previous":
            end = min(end, core.start_char_idx)
        else:
            start = max(start, core.end_char_idx)
        if start >= end or not source_text[start:end].strip():
            continue
        nearby = source_text[start:end]
        chunks = splitter.split_text(nearby)
        if not chunks:
            continue
        chunk = chunks[-1] if direction == "previous" else chunks[0]
        offset = nearby.rfind(chunk) if direction == "previous" else nearby.find(chunk)
        if offset < 0:
            raise ValueError("Neighbor splitter returned non-source text.")
        start, end = start + offset, start + offset + len(chunk)
        key = (source_id, start, end)
        if key in considered:
            continue
        considered.add(key)
        # Exact whitespace around the selected neighbor fragment can be restored
        # by merging; substantive omitted text must never be bridged implicitly.
        current = _merge(intervals, documents, priority)
        if any(segment["source_id"] == source_id and segment["subject_source_id"] == _subject(core)
               and segment["start"] <= start and end <= segment["end"]
               for segment in current):
            continue
        attached = any(segment["source_id"] == source_id and segment["subject_source_id"] == _subject(core) and (
            (end <= segment["start"] and _touches(source_text, end, segment["start"]))
            or (start >= segment["end"] and _touches(source_text, segment["end"], start))
            or (start < segment["end"] and end > segment["start"])
        ) for segment in current)
        if not attached:
            audit["rejected_neighbors"].append({"node_id": neighbor.node_id, "reason": "noncontiguous_fragment"})
            continue
        interval = {
            "source_id": source_id, "start": start, "end": end,
            "subject_source_id": _subject(core),
            "subject_title": core.metadata.get("subject_title", core.metadata.get("title", source_id)),
            "core_node_ids": [], "expanded_node_ids": [neighbor.node_id],
            "sections": [], "scores": [],
            "evidence_roles": [neighbor.metadata.get('evidence_role','UNKNOWN')],
            "table_headers": _table_headers(neighbor, source_text),
        }
        proposal = _render([*intervals, interval], documents, priority, encode)
        if proposal["context_tokens"] <= max_tokens:
            intervals.append(interval)
            result = proposal
            audit["accepted_neighbors"].append({
                "core_node_id": core.node_id, "node_id": neighbor.node_id,
                "direction": direction, "distance": distance, "start_char": start, "end_char": end,
            })
        else:
            audit["rejected_neighbors"].append({"node_id": neighbor.node_id, "reason": "context_budget"})
    audit["final_context_tokens"] = result["context_tokens"]
    audit["merged_citation_count"] = len(result["evidence"])
    return {**result, "audit": audit}
