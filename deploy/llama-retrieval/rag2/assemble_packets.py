"""Pure, model-free adapters for whole-evidence query-lane assembly.

This is lab adapter code, not a verbatim implementation of an upstream query
planner. Retrieval, evidence extraction, and within-query ranking stay frozen.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from hashlib import sha256
import json
from time import perf_counter


def digest_text(value):
    return sha256(value.encode("utf-8")).hexdigest()


def token_count(tokenizer, value):
    if callable(tokenizer):
        return len(tokenizer(value))
    try:
        return len(tokenizer.encode(value, disallowed_special=()))
    except TypeError:
        return len(tokenizer.encode(value))


def render_item(item):
    """Existing frozen evidence rendering, with only citation IDs reassigned."""
    subject = (f"Subject: {item['subject_title']}\n"
               if item['subject_source_id'] != item['source_id'] else "")
    roles = ", ".join(item["evidence_roles"])
    role = f"Structural evidence roles: {roles}\n" if roles else ""
    headers = "".join(
        f"Table header (source characters {h['start_char']}–{h['end_char']}):\n{h['text'].rstrip()}\n"
        for h in item["table_headers"] if h["included_in_context"])
    return (f"[Source {item['citation_id']}] {item['title']}\n{subject}"
            f"Section: {item['section']}\n{role}URL: {item['url']}\n{headers}{item['text']}")


def evidence_key(item):
    """Exact source/subject/span identity; overlaps are deliberately not merged."""
    headers = tuple(sorted((h["start_char"], h["end_char"])
                           for h in item["table_headers"] if h["included_in_context"]))
    return (item["source_id"], item["subject_source_id"],
            item["start_char"], item["end_char"], headers)


def key_digest(item):
    return digest_text(json.dumps(evidence_key(item), ensure_ascii=False))


def validate_item(item, documents):
    source = item["source_id"]
    if source not in documents:
        raise ValueError(f"Unknown evidence source: {source}")
    doc = documents[source]
    text = doc["text"]
    a, b = item["start_char"], item["end_char"]
    if (type(a) is not int or type(b) is not int or not 0 <= a < b <= len(text)
            or text[a:b] != item["text"]):
        raise ValueError("Evidence is not its exact original source slice.")
    if item["source_sha256"] != digest_text(text):
        raise ValueError("Evidence source digest mismatch.")
    if item["url"] != doc.get("url", "") or item["title"] != doc.get("title", source):
        raise ValueError("Evidence source title or URL mismatch.")
    subject = item["subject_source_id"]
    if subject in documents and item["subject_title"] != documents[subject]["title"]:
        raise ValueError("Evidence subject identity mismatch.")
    for header in item["table_headers"]:
        left, right = header["start_char"], header["end_char"]
        if (type(left) is not int or type(right) is not int
                or not 0 <= left < right <= len(text) or text[left:right] != header["text"]
                or header["source_id"] != source or header["url"] != doc.get("url", "")
                or type(header["included_in_context"]) is not bool):
            raise ValueError("Table header source provenance mismatch.")
    for span in item.get("evidence_role_spans", []):
        left, right = span["start_char"], span["end_char"]
        if (type(left) is not int or type(right) is not int
                or not a <= left < right <= b):
            raise ValueError("Evidence role span escapes its source slice.")


def validate_result(result, documents, tokenizer, max_tokens=None):
    evidence = result["evidence"]
    ids = [item["citation_id"] for item in evidence]
    if ids != [str(i) for i in range(1, len(evidence) + 1)]:
        raise ValueError("Citation IDs must be unique and sequential.")
    for item in evidence:
        validate_item(item, documents)
    if "\n\n".join(map(render_item, evidence)) != result["context"]:
        raise ValueError("Whole evidence blocks do not reconstruct the exact context.")
    count = token_count(tokenizer, result["context"])
    if count != result["context_tokens"] or digest_text(result["context"]) != result["context_sha256"]:
        raise ValueError("Context token count or digest mismatch.")
    if max_tokens is not None and count > max_tokens:
        raise ValueError("Context exceeds its declared token budget.")
    return {"source_verified": True, "whole_blocks": True,
            "evidence_count": len(evidence),
            "unique_evidence_count": len({evidence_key(item) for item in evidence}),
            "unique_source_count": len({item["source_id"] for item in evidence}),
            "unique_subject_count": len({item["subject_source_id"] for item in evidence})}


def union_intervals(intervals):
    merged = []
    for left, right in sorted(intervals):
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
        else:
            merged.append((left, right))
    return merged


def span_covered(left, right, intervals):
    return any(a <= left and right <= b for a, b in union_intervals(intervals))


def covered_chars(left, right, intervals):
    return sum(max(0, min(right, b) - max(left, a)) for a, b in union_intervals(intervals))


def assemble_lanes(lanes, documents, tokenizer, budget, *, append_only=False):
    """Round robin in lane order; a lane gets one complete accepted block per turn.

    Each lane has {name, query_id, result}; the first is the original query.
    Duplicate/over-budget blocks are recorded and skipped, never shortened.
    Append-only mode retains the original context and evidence byte-for-byte,
    then round robins focused lanes. It can retain original duplicate evidence.
    """
    started = perf_counter()
    if not lanes or type(budget) is not int or budget < 1:
        raise ValueError("Lanes and a positive integer budget are required.")
    for lane in lanes:
        validate_result(lane["result"], documents, tokenizer)
    base = lanes[0]["result"]
    evidence = deepcopy(base["evidence"]) if append_only else []
    context = base["context"] if append_only else ""
    if token_count(tokenizer, context) > budget:
        raise ValueError("The immutable baseline exceeds the append-only budget.")
    selected, omitted = [], []
    seen = {evidence_key(item) for item in evidence}
    coverage = {}

    def remember(item):
        identity = (item["source_id"], item["subject_source_id"])
        spans = coverage.setdefault(identity, [])
        spans.append((item["start_char"], item["end_char"]))
        spans.extend((h["start_char"], h["end_char"]) for h in item["table_headers"]
                     if h["included_in_context"])
    for item in evidence:
        remember(item)

    def receipt(lane, item, rank):
        return {"lane": lane["name"], "query_id": lane["query_id"],
                "lane_rank": rank, "original_citation_id": item["citation_id"],
                "source_id": item["source_id"], "subject_source_id": item["subject_source_id"],
                "start_char": item["start_char"], "end_char": item["end_char"],
                "evidence_key_sha256": key_digest(item)}

    if append_only:
        for rank, item in enumerate(base["evidence"], 1):
            selected.append({**receipt(lanes[0], item, rank), "citation_id": item["citation_id"],
                             "selection": "immutable_baseline"})
    active = deque((lane, deque(enumerate(lane["result"]["evidence"], 1)))
                   for lane in (lanes[1:] if append_only else lanes))
    while active:
        lane, queue = active.popleft()
        while queue:
            rank, original = queue.popleft()
            audit = receipt(lane, original, rank)
            key = evidence_key(original)
            if key in seen:
                omitted.append({**audit, "reason": "exact_source_subject_spans_duplicate"})
                continue
            covered = coverage.get((original["source_id"], original["subject_source_id"]), [])
            body_covered = span_covered(original["start_char"], original["end_char"], covered)
            headers_covered = all(span_covered(h["start_char"], h["end_char"], covered)
                                  for h in original["table_headers"] if h["included_in_context"])
            if body_covered and headers_covered:
                omitted.append({**audit, "reason": "fully_contained_in_selected_source_subject_span_union"})
                continue
            item = deepcopy(original)
            item["citation_id"] = str(len(evidence) + 1)
            trial = context + ("\n\n" if context else "") + render_item(item)
            count = token_count(tokenizer, trial)
            if count > budget:
                omitted.append({**audit, "reason": "whole_block_exceeds_remaining_budget",
                                "candidate_total_tokens": count})
                continue
            previous_tokens = token_count(tokenizer, context)
            evidence.append(item)
            context = trial
            seen.add(key)
            selected.append({**audit, "citation_id": item["citation_id"],
                             "selection": "round_robin", "marginal_tokens": count - previous_tokens,
                             "body_characters_already_present": covered_chars(item["start_char"], item["end_char"], covered)})
            remember(item)
            break
        if queue:
            active.append((lane, queue))
    result = {"question": base.get("question"), "context": context, "evidence": evidence,
              "context_tokens": token_count(tokenizer, context), "context_sha256": digest_text(context),
              "corpus_sha256": base.get("corpus_sha256"), "pipeline": deepcopy(base.get("pipeline"))}
    validation = validate_result(result, documents, tokenizer, budget)
    if append_only and (not context.startswith(base["context"])
                        or evidence[:len(base["evidence"])] != base["evidence"]):
        raise AssertionError("Append-only assembly changed the baseline prefix.")
    audit = {"adapter": "whole-evidence-lane-roundrobin-v1", "budget": budget,
             "append_only": append_only, "baseline_context_sha256": base["context_sha256"],
             "baseline_prefix_preserved": context.startswith(base["context"]),
             "baseline_evidence_prefix_preserved": evidence[:len(base["evidence"])] == base["evidence"],
             "lane_order": [lane["name"] for lane in lanes], "selected": selected, "omitted": omitted,
             "deduplication": "exact source + subject + body/header spans, then fully contained source/subject span union with headers covered; partial overlaps remain whole",
             "unique_source_subject_characters": sum(b-a for spans in coverage.values() for a,b in union_intervals(spans)),
             "validation": validation,
             "assembly_and_validation_ms": (perf_counter() - started) * 1000}
    return {"result": result, "assembly": audit}
