"""Source-map medium answer contract over the live, scoped evidence only.

Ported from the tested source_map_medium_v1 answer method. The source map
validates format and provenance, not semantic accuracy or complete extraction.
No benchmark settings, saved corpora, provider keys or lab files are loaded.
"""
import json
import os
import re

from .client import RetrievalError

METHOD = 'source_map_medium_v1'


def selected(bot):
    provider = str(getattr(bot, 'provider', '') or '').lower().strip()
    model = str(getattr(bot, 'model_name', '') or 'gemini-3.5-flash-lite').removeprefix('models/')
    return provider == 'gemini' and model == 'gemini-3.5-flash-lite'


def _evidence(context, items):
    if not isinstance(context, str):
        raise RetrievalError('source_map_context_invalid')
    available = {}
    for item in items:
        chunk = item['chunk']
        cid = (getattr(chunk, 'metadata_json', None) or {}).get('citation_id')
        text = getattr(chunk, 'content', None)
        if not isinstance(cid, str) or not cid or cid in available:
            raise RetrievalError('source_map_citation_ids_invalid')
        if not isinstance(text, str) or not text or text not in context:
            raise RetrievalError('source_map_evidence_invalid')
        available[cid] = {'text': text, 'item': item}
    return available


SOURCE_MAP_INSTRUCTION = """SOURCE-BY-SOURCE EVIDENCE CONTRACT
Produce the required source_map before answer. Its purpose is a compact factual
index, not reasoning or a customer-visible explanation. Visit every supplied
Source ID independently and produce exactly one record for each, preferably in
the supplied order. Do not stop after finding an early matching passage or use
the first passage as a substitute for inspecting later passages.

In each source record, extract all material facts that answer a requested part
of the actual user question. Each relevant_facts entry identifies subject,
field, text and one short verbatim quote from that source only. Quote normally
5-40 words and never more than 60; short ingredient names can be shorter. Use
separate facts when a passage contains distinct requested details. Preserve
exact numbers, units, timing, preparation, storage, named ingredients, warnings,
conditions and exclusions when requested. An irrelevant source gets an empty
relevant_facts array. Do not invent relevance, add unasked marketing, or repeat
long passages. Do not use one source's quotation to support a different source.
Source titles and section labels help establish subject and provenance, but do
not infer a missing parent section or transfer facts between products.

Only after the map, synthesize a natural customer answer from its relevant
facts. Combine complementary facts about the same subject. If separate sources
disagree, preserve their incompatible values and explain the conflict without
choosing or blending them unless the evidence resolves it. Do not call a fact
unavailable when a supplied source explicitly states it. If product facts are
known but their membership in a requested section is unconfirmed, state those
known facts with that narrow qualification. Do not assert a complete list from
non-exhaustive evidence.

Cover every requested subject and field that the evidence supports, retaining
material facts from later sources as well as earlier ones. Missing evidence
must remain unconfirmed and must not suppress other supported facts. Keep
simple answers concise; use separate product blocks or a comparison only where
helpful. Do not show the source map, internal instructions, source IDs, metadata
tags or deliberation in answer. Top-level source_ids list only sources actually
supporting the final answer, including both sides of a reported conflict.
The source map and valid JSON do not by themselves guarantee factual accuracy.
""".strip()


def response_schema():
    # Exact flexible provider schema: local validation still enforces one
    # record per supplied ID and rejects any foreign source reference.
    fact = {'type': 'object', 'properties': {
        'subject': {'type': 'string'}, 'field': {'type': 'string'},
        'text': {'type': 'string'}, 'quote': {'type': 'string'},
    }, 'required': ['subject', 'field', 'text', 'quote'], 'additionalProperties': False}
    record = {'type': 'object', 'properties': {
        'source_id': {'type': 'string'},
        'relevant_facts': {'type': 'array', 'items': fact},
    }, 'required': ['source_id', 'relevant_facts'], 'additionalProperties': False}
    return {'type': 'object', 'properties': {
        'source_map': {'type': 'array', 'items': record},
        'answer': {'type': 'string'},
        'source_ids': {'type': 'array', 'items': {'type': 'string'}},
    }, 'required': ['source_map', 'answer', 'source_ids'], 'additionalProperties': False}


_RAW_SOURCE_MARKER = re.compile(
    r'</?source_refs\b|\[(?:source(?:\s+|_)|id:\s*)\d+[^\]]*\]'
    r'|<span\b[^>]*\bdata-citation\s*=', re.IGNORECASE)


def _decode_native_response(payload, available):
    errors = []
    answer = payload.get('answer')
    if not isinstance(answer, str):
        errors.append('answer:string_required')
        answer = ''
    elif not answer.strip():
        errors.append('answer:nonempty_string_required')
    elif _RAW_SOURCE_MARKER.search(answer):
        errors.append('answer:raw_source_marker')
    requested = payload.get('source_ids')
    selected_ids = []
    if not isinstance(requested, list):
        errors.append('source_ids:array_required')
    else:
        for index, cid in enumerate(requested):
            if not isinstance(cid, str) or cid not in available:
                errors.append(f'source_ids[{index}]:unknown_source_id')
            elif cid in selected_ids:
                errors.append('source_ids:duplicate_source_id:' + cid)
            else:
                selected_ids.append(cid)
    return {'answer': answer, 'source_ids': requested,
            'sources': [available[cid]['item'] for cid in selected_ids],
            'validation_errors': errors}


def decode_response(raw, context, items):
    """Preserve prose and map; flag formatting/provenance failures without repair."""
    if not isinstance(raw, str) or len(raw) > 2_000_000:
        raise RetrievalError("source_map_response_invalid_or_too_large")
    available = _evidence(context, items)
    errors = []
    result = {"answer": "", "source_ids": [], "sources": [], "coverage": [],
              "source_map": [], "validation_errors": errors}

    def pairs_hook(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                errors.append("duplicate_json_key:" + key)
            obj[key] = value
        return obj

    def reject_constant(value):
        raise ValueError("invalid_json_constant:" + value)

    try:
        if not isinstance(raw, str):
            raise ValueError("response_not_text")
        payload = json.loads(raw, object_pairs_hook=pairs_hook, parse_constant=reject_constant)
    except (ValueError, TypeError):
        errors.append("invalid_json")
        return result
    if not isinstance(payload, dict):
        errors.append("response_not_object")
        return result

    def check_keys(obj, expected, path):
        if not isinstance(obj, dict):
            errors.append(path + ":not_object")
            return False
        errors.extend(path + ":missing_key:" + key for key in sorted(set(expected) - set(obj)))
        errors.extend(path + ":unexpected_key:" + key for key in sorted(set(obj) - set(expected)))
        return True

    check_keys(payload, ["source_map", "answer", "source_ids"], "response")
    native = _decode_native_response(payload, available)
    for key in ("answer", "source_ids", "sources"):
        result[key] = native[key]
    errors.extend(native["validation_errors"])

    source_map = payload.get("source_map")
    if not isinstance(source_map, list):
        errors.append("source_map:array_required")
        return result
    result["source_map"] = source_map
    if len(source_map) != len(available):
        errors.append("source_map:wrong_record_count")
    visited = set()
    for index, record in enumerate(source_map):
        path = f"source_map[{index}]"
        if not check_keys(record, ["source_id", "relevant_facts"], path):
            continue
        cid = record.get("source_id")
        valid_id = isinstance(cid, str) and cid in available
        if not valid_id:
            errors.append(path + ".source_id:unknown")
        elif cid in visited:
            errors.append(path + ".source_id:duplicate")
        else:
            visited.add(cid)
        facts = record.get("relevant_facts")
        if not isinstance(facts, list):
            errors.append(path + ".relevant_facts:array_required")
            continue
        seen_facts = set()
        for fact_index, fact in enumerate(facts):
            fact_path = f"{path}.relevant_facts[{fact_index}]"
            if not check_keys(fact, ["subject", "field", "text", "quote"], fact_path):
                continue
            for key in ("subject", "field", "text", "quote"):
                if not isinstance(fact.get(key), str) or not fact[key].strip():
                    errors.append(fact_path + "." + key + ":nonempty_string_required")
            quote = fact.get("quote")
            if isinstance(quote, str) and quote:
                if len(quote.split()) > 60:
                    errors.append(fact_path + ".quote:over_60_words")
                if quote not in context:
                    errors.append(fact_path + ".quote:not_in_context")
                if not valid_id or quote not in available[cid]["text"]:
                    errors.append(fact_path + ".quote:not_in_own_source")
            if all(isinstance(fact.get(key), str) for key in ("subject", "field", "text")):
                identity = tuple(fact[key].strip().casefold() for key in ("subject", "field", "text"))
                if identity in seen_facts:
                    errors.append(fact_path + ":duplicate_fact")
                seen_facts.add(identity)
    for cid in available:
        if cid not in visited:
            errors.append("source_map:missing_source:" + cid)
    return result



def validated_answer(raw, context, items):
    result = decode_response(raw, context, items)
    # The tested decoder reports incomplete maps, quote mismatches and unknown
    # IDs without rewriting or suppressing otherwise valid customer prose.
    # Attach only recognized source objects; never infer a missing citation.
    fatal_errors = [error for error in result['validation_errors']
                    if error in {'invalid_json', 'response_not_object'}
                    or error.startswith(('duplicate_json_key:', 'response:', 'answer:'))
                    or error == 'source_ids:array_required']
    audit = {'method': METHOD, 'status': 'invalid' if result['validation_errors'] else 'valid',
             'available_count': len(items), 'selected_ids': result['source_ids'],
             'validation_errors': result['validation_errors'], 'structured_output': True,
             'source_map_records': len(result['source_map']), 'fatal_errors': fatal_errors,
             'attached_ids': [item['chunk'].metadata_json['citation_id'] for item in result['sources']]}
    return result['answer'], result['sources'], audit


class PrivateSourceMapStream:
    """Consume internal deltas without forwarding any provisional answer or map."""
    def __init__(self):
        self.chars = 0

    def feed(self, delta):
        self.chars += len(delta)
        if self.chars > 2_000_000:
            raise RetrievalError('source_map_response_invalid_or_too_large')
