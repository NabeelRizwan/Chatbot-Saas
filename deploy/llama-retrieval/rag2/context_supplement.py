"""Experimental append-only source spans; no retrieval/model changes.

Two controls: ``core`` appends already-reranked raw nodes; ``section`` first
tries the complete, short parser section containing that node. Baseline
context and evidence are retained verbatim. This is NOT a claim that rank
or structural completeness establishes factual relevance or answer coverage.

The rendering/evidence schema follows the project's evidence_context.py and
backend/services/llama_rag/knowledge.py. This module is lab-only: that backend
currently enforces an independent 4,000-token limit.
"""
from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
from math import isfinite
from time import perf_counter


def _field(value, key, default=None):
    return value.get(key, default) if isinstance(value, Mapping) else getattr(value, key, default)


def _encode(tokenizer, text):
    if callable(tokenizer):
        return tokenizer(text)
    try:
        return tokenizer.encode(text, disallowed_special=())
    except TypeError:
        return tokenizer.encode(text)


def _subject(node):
    return str(node.metadata.get('subject_source_id') or node.metadata['source_id'])


def _checked(node, documents):
    source = str(node.metadata['source_id'])
    if source not in documents:
        raise ValueError('Unknown source.')
    document = documents[source]
    text = _field(document, 'text')
    a, b = node.start_char_idx, node.end_char_idx
    if (not isinstance(text, str) or type(a) is not int or type(b) is not int
            or not 0 <= a < b <= len(text) or text[a:b] != node.text
            or node.metadata.get('url', '') != _field(document, 'url', '')):
        raise ValueError('Source text, offset, or URL mismatch.')
    return source, document, text, a, b


def _covered(a, b, intervals, text):
    """Only source interval coverage counts; no semantic/text deduplication."""
    cursor = a
    for left, right in sorted(intervals):
        if right <= cursor or left >= b:
            continue
        if left > cursor and text[cursor:left].strip():
            return False
        cursor = max(cursor, right)
        if cursor >= b:
            return True
    return not text[cursor:b].strip()


def _headers(node, source, document, text, a, b):
    m = node.metadata
    keys = ('table_header', 'table_header_start_char_idx', 'table_header_end_char_idx',
            'table_start_char_idx', 'table_end_char_idx')
    if not any(key in m for key in keys):
        return []
    header, start, end, table_start, table_end = [m.get(key) for key in keys]
    if (not isinstance(header, str) or not header.strip()
            or any(type(value) is not int for value in (start, end, table_start, table_end))
            or not 0 <= table_start == start < end <= table_end <= len(text)
            or text[start:end] != header
            or not table_start <= node.start_char_idx < node.end_char_idx <= table_end):
        raise ValueError('Table header provenance mismatch.')
    included = not (a <= start + len(header) - len(header.lstrip())
                    and end - len(header) + len(header.rstrip()) <= b)
    return [{'text': header, 'start_char': start, 'end_char': end,
             'source_id': source, 'url': _field(document, 'url', ''),
             'included_in_context': included}]


def _header_text(item):
    return ''.join(f"Table header (source characters {h['start_char']}–{h['end_char']}):\n{h['text'].rstrip()}\n"
                   for h in item['table_headers'] if h['included_in_context'])


def render_item(item):
    subject = (f"Subject: {item['subject_title']}\n"
               if item['subject_source_id'] != item['source_id'] else '')
    roles = ', '.join(item['evidence_roles'])
    role = f'Structural evidence roles: {roles}\n' if roles else ''
    return (f"[Source {item['citation_id']}] {item['title']}\n{subject}"
            f"Section: {item['section']}\n{role}URL: {item['url']}\n"
            f"{_header_text(item)}{item['text']}")


def _span(candidate, source_nodes, documents, section_index, tokenizer, strategy, limit):
    node = source_nodes[candidate.node.node_id]
    source, document, text, a, b = _checked(node, documents)
    if (candidate.node.metadata['source_id'] != node.metadata['source_id']
            or _subject(candidate.node) != _subject(node)):
        raise ValueError('Scored node identity differs from raw source node.')
    members, kind = [node], 'core'
    if strategy == 'section':
        sa, sb = (node.metadata.get(key) for key in
                  ('section_start_char_idx', 'section_end_char_idx'))
        if (type(sa) is int and type(sb) is int and 0 <= sa <= a < b <= sb <= len(text)
                and len(_encode(tokenizer, text[sa:sb])) <= limit):
            section = section_index[(source, sa, sb)]
            # Require the parser's whole section to be backed by exact nodes of
            # one subject. Never bridge a linked card, variant, or unknown gap.
            for member in section:
                _checked(member, documents)
            if (section and all(_subject(member) == _subject(node)
                                and sa <= member.start_char_idx < member.end_char_idx <= sb
                                for member in section)
                    and _covered(sa, sb, [(m.start_char_idx, m.end_char_idx)
                                         for m in section], text)):
                a, b, members, kind = sa, sb, section, 'section'
    if len(_encode(tokenizer, text[a:b])) > limit:
        return None, 'span_token_limit'
    # Fragmented table rows are not a relation-complete supplement unless the
    # complete verified table section was restored above.
    if kind == 'core' and node.metadata.get('table_row_fragmented'):
        return None, 'fragmented_table_row'
    roles = list(dict.fromkeys(m.metadata.get('evidence_role', 'UNKNOWN') for m in members))
    sections = list(dict.fromkeys(m.metadata.get('section', '') for m in members))
    headers = _headers(node, source, document, text, a, b)
    role_spans = [{'start_char': m.start_char_idx, 'end_char': m.end_char_idx,
                   'node_id': m.node_id,
                   'evidence_role': m.metadata.get('evidence_role', 'UNKNOWN'),
                   'evidence_role_basis': m.metadata.get('evidence_role_basis', 'unclassified')}
                  for m in members]
    item = {'citation_id': '', 'source_id': source,
            'title': _field(document, 'title', source), 'url': _field(document, 'url', ''),
            'subject_source_id': _subject(node),
            'subject_title': _field(documents.get(_subject(node), {}), 'title',
                                    node.metadata.get('subject_title', '')),
            'section': node.metadata.get('section', ''), 'sections': sections,
            'text': text[a:b], 'start_char': a, 'end_char': b,
            'source_sha256': sha256(text.encode()).hexdigest(), 'score': float(candidate.score),
            'core_node_ids': [node.node_id],
            'expanded_node_ids': [m.node_id for m in members if m.node_id != node.node_id],
            'table_headers': headers, 'evidence_roles': roles,
            'evidence_role_spans': role_spans}
    item['node_id'] = 'context-' + sha256(
        f"{source}:{_subject(node)}:{a}:{b}:{_header_text(item)}:{item['text']}".encode()).hexdigest()
    return item, kind


def supplement_context(base, ranked_groups, source_nodes, documents, tokenizer,
                       extra_tokens=1200, *, strategy='core', max_total_tokens=5200,
                       max_spans=6, max_span_tokens=320, max_candidates=96):
    """Return a new assembly with the complete baseline as a byte prefix.

    Each (existing query group, parser-verified subject) gets one successful
    addition per round. Scores are ordered only inside an existing query group.
    No absolute logit floor, percentile confidence, lexical facet classifier,
    shortening, or generated relation labels are introduced.
    """
    started = perf_counter()
    if strategy not in {'core', 'section'}:
        raise ValueError('Unknown supplement strategy.')
    for value in (extra_tokens, max_total_tokens, max_spans, max_span_tokens, max_candidates):
        if type(value) is not int or value < 0:
            raise ValueError('Supplement limits must be nonnegative integers.')
    if not max_total_tokens or not max_span_tokens or not max_candidates:
        raise ValueError('Total, span, and candidate bounds must be positive.')
    if sum(map(len, ranked_groups.values())) > max_candidates:
        raise ValueError('Scored candidate bound exceeded.')
    result = deepcopy(base)
    baseline = base['context']
    if '\n\n'.join(map(render_item, base['evidence'])) != baseline:
        raise ValueError('Baseline evidence does not reconstruct its context.')
    base_tokens = len(_encode(tokenizer, baseline))
    if base_tokens > max_total_tokens or len(base['evidence']) > 64:
        raise ValueError('Baseline exceeds the experimental output bound.')
    ceiling = min(max_total_tokens, base_tokens + extra_tokens)
    covered = defaultdict(list)
    for item in base['evidence']:
        covered[(item['source_id'], item['subject_source_id'])].append((item['start_char'], item['end_char']))
    section_index = defaultdict(list)
    for node in source_nodes.values():
        key = (str(node.metadata['source_id']), node.metadata.get('section_start_char_idx'),
               node.metadata.get('section_end_char_idx'))
        section_index[key].append(node)
    for members in section_index.values():
        members.sort(key=lambda node: (node.start_char_idx, node.end_char_idx, node.node_id))
    queues = {}
    for group, items in ranked_groups.items():
        if any(item.score is None or not isfinite(float(item.score)) for item in items):
            raise ValueError('Scored candidates require finite scores.')
        for candidate in sorted(items, key=lambda item: -float(item.score)):
            queues.setdefault((group, _subject(candidate.node)), deque()).append(candidate)
    accepted, rejected, seen = [], [], set()
    max_spans = min(max_spans, 6, 64 - len(base['evidence']))
    while queues and len(accepted) < max_spans and extra_tokens:
        for lane, queue in list(queues.items()):
            while queue and len(accepted) < max_spans:
                candidate = queue.popleft()
                node_id = candidate.node.node_id
                if node_id in seen:
                    continue
                seen.add(node_id)
                item, kind = _span(candidate, source_nodes, documents, section_index,
                                   tokenizer, strategy, max_span_tokens)
                if item is None:
                    rejected.append({'node_id': node_id, 'reason': kind})
                    continue
                source_text = _field(documents[item['source_id']], 'text')
                key = (item['source_id'], item['subject_source_id'])
                if _covered(item['start_char'], item['end_char'], covered[key], source_text):
                    rejected.append({'node_id': node_id, 'reason': 'already_covered'})
                    continue
                item['citation_id'] = str(len(result['evidence']) + 1)
                context = result['context'] + ('\n\n' if result['context'] else '') + render_item(item)
                tokens = len(_encode(tokenizer, context))
                if tokens > ceiling:
                    rejected.append({'node_id': node_id, 'reason': 'total_token_limit'})
                    continue
                prior_tokens = len(_encode(tokenizer, result['context']))
                result['evidence'].append(item)
                result['context'], result['context_tokens'] = context, tokens
                covered[key].append((item['start_char'], item['end_char']))
                accepted.append({'node_id': node_id, 'query_group': lane[0], 'subject': lane[1],
                                 'kind': kind, 'marginal_tokens': tokens - prior_tokens})
                break
            if not queue:
                queues.pop(lane, None)
    result['context_tokens'] = len(_encode(tokenizer, result['context']))
    result['context_sha256'] = sha256(result['context'].encode()).hexdigest()
    result.setdefault('audit', {})['supplement'] = {
        'version': 'draft-frozen-source-spans-v1', 'strategy': strategy,
        'baseline_sha256': sha256(baseline.encode()).hexdigest(),
        'baseline_tokens': base_tokens, 'token_ceiling': ceiling,
        'accepted': accepted, 'rejected': rejected,
        'elapsed_ms': round((perf_counter() - started) * 1000, 3),
        'baseline_prefix_preserved': result['context'].startswith(baseline),
        'additional_scored_pairs': 0}
    assert result['evidence'][:len(base['evidence'])] == base['evidence']
    assert result['context'].startswith(baseline)
    return result
