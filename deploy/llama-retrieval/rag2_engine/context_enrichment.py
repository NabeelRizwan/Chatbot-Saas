"""Append complete source blocks after an immutable base context.

MarkdownIt line maps identify whole paragraph runs, lists and tables. No rows,
sentences, numbers, negations or qualifiers are reconstructed. Ambiguous or
oversized units are skipped. prepare_block_index() can run once at engine load;
pass prepared_index=... to avoid reparsing immutable sources on every question.
"""
from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy
from hashlib import sha256
from math import isfinite
import re
from time import perf_counter

from markdown_it import MarkdownIt
from .source_context_contract import (_checked, _covered, _encode, _field, _headers,
                                _header_text, _subject, render_item)


_PARSER = MarkdownIt('commonmark', {'html': False}).enable('table')
_WORDS = re.compile(r'[^\W_]+', re.UNICODE)


def body_text_signal(text):
    """Count visible words outside headings, image captions, and linked text.

    Do not edit any emitted evidence: this projection is used only to decide
    which already-scored nodes may consume the *additional* context allowance.
    """
    plain, visible = [], []
    heading_depth = 0
    for token in _PARSER.parse(text):
        if token.type == 'heading_open':
            heading_depth += 1
        elif token.type == 'heading_close':
            heading_depth -= 1
        elif token.type == 'inline' and not heading_depth:
            link_depth = 0
            for child in token.children or []:
                if child.type == 'link_open':
                    link_depth += 1
                elif child.type == 'link_close':
                    link_depth = max(0, link_depth - 1)
                elif child.type == 'image':
                    visible.extend(_WORDS.findall(child.content))
                elif child.type in {'text', 'code_inline'}:
                    words = _WORDS.findall(child.content)
                    visible.extend(words)
                    if not link_depth:
                        plain.extend(words)
    fraction = len(plain) / len(visible) if visible else 0.0
    return {'plain_words': len(plain), 'visible_words': len(visible),
            'plain_fraction': fraction,
            'eligible': len(plain) >= 6 and fraction >= 0.25}


def _is_label(block, text):
    if block['type'] == 'heading_open':
        return True
    # Even a one-item list can be a complete value ("Base:\n- Steel").
    # Keep lists indivisible; the unit builder already attaches following prose.
    if block['type'] != 'paragraph_open':
        return False
    parsed = _PARSER.parse(text[block['start']:block['end']])
    if any(t.type in {'image', 'link_open'} for tok in parsed for t in (tok.children or [])):
        return False
    inlines = [t for t in parsed if t.type == 'inline']
    if len(inlines) != 1 or '\n' in inlines[0].content.strip():
        return False
    value = ''.join(c.content for c in inlines[0].children or [] if c.type in {'text', 'code_inline'}).strip()
    words = _WORDS.findall(value)
    if (not 1 <= len(words) <= 8 or any(c.isdigit() for c in value)
            or value.endswith(('.', '?', '!', ';')) or not words[0][0].isalpha()):
        return False
    connectors = {'a', 'an', 'and', 'as', 'at', 'by', 'for', 'from', 'in', 'of', 'on', 'or', 'the', 'to', 'with'}
    return (value.endswith(':')
            or all(w[0].isupper() or w.casefold() in connectors for w in words))


def structural_units(text):
    """Relative offsets of indivisible source units, with explicit nearby labels.

    Paragraphs between structural boundaries stay together. A complete list or
    table also retains following paragraphs, so a following qualification is not
    silently detached. A preceding standalone label stays in the same exact
    contiguous interval. Oversized resulting units are skipped by the caller.
    """
    offsets = [0, *(m.end() for m in re.finditer(r'\r\n|\r|\n', text))]
    if offsets[-1] != len(text):
        offsets.append(len(text))
    blocks = []
    allowed = {'heading_open', 'paragraph_open', 'bullet_list_open', 'ordered_list_open',
               'table_open', 'blockquote_open', 'fence', 'code_block'}
    for token in _PARSER.parse(text):
        if token.level == 0 and token.map and token.type in allowed:
            a, b = token.map
            block = {'start': offsets[a], 'end': offsets[min(b, len(offsets)-1)], 'type': token.type}
            block['label'] = _is_label(block, text)
            blocks.append(block)
    units, index, label = [], 0, None
    while index < len(blocks):
        block = blocks[index]
        if (block['label'] and block['type'] == 'paragraph_open' and label
                and (label['type'] == 'heading_open'
                     or text[label['start']:label['end']].rstrip().endswith(':'))):
            block = {**block, 'label': False}
        if block['label']:
            # Consecutive structural labels use the nearest one. A heading is
            # still available as existing parser section metadata in the prompt.
            label = block
            index += 1
            continue
        first, last = block, block
        index += 1
        while index < len(blocks) and blocks[index]['type'] == 'paragraph_open' and not blocks[index]['label']:
            last = blocks[index]
            index += 1
        a = label['start'] if label and not text[label['end']:first['start']].strip() else first['start']
        b = last['end']
        body = text[first['start']:b]
        words = _WORDS.findall(body)
        # A bare identifier/value without an explicit adjoining label is not a
        # safe standalone relation. A complete statement such as "Seats four."
        # or a structured list retains its own subject/property wording.
        bare_value = bool(words) and (not any(any(c.isalpha() for c in w) for w in words)
            or (len(words) <= 3 and any(c.isdigit() for c in body)
                and not body.rstrip().endswith(('.', '!', '?'))
                and first['type'] == 'paragraph_open'))
        if words and (not bare_value or a < first['start']):
            units.append({'start': a, 'end': b, 'body_start': first['start'],
                          'kind': first['type'], 'label_retained': a < first['start']})
        label = None
    return units


def prepare_block_index(source_nodes, documents, *, max_section_chars=32000):
    if type(max_section_chars) is not int or max_section_chars < 1:
        raise ValueError('Section character bound must be positive.')
    started = perf_counter()
    sections = defaultdict(list)
    for node in source_nodes.values():
        m = node.metadata
        key = (str(m['source_id']), m.get('section_start_char_idx'), m.get('section_end_char_idx'))
        sections[key].append(node)
    result = {'sections': {}, 'document_sha256': {}, 'max_section_chars': max_section_chars}
    for key, members in sections.items():
        source, a, b = key
        if source not in documents:
            raise ValueError('Unknown source in block index.')
        text = _field(documents[source], 'text')
        result['document_sha256'].setdefault(source, sha256(text.encode()).hexdigest())
        if (type(a) is not int or type(b) is not int or not 0 <= a < b <= len(text)
                or b-a > max_section_chars):
            continue
        members.sort(key=lambda n: (n.start_char_idx, n.end_char_idx, n.node_id))
        for node in members:
            _checked(node, documents)
        subjects = {_subject(n) for n in members}
        if (len(subjects) != 1 or not all(a <= n.start_char_idx < n.end_char_idx <= b for n in members)
                or not _covered(a, b, [(n.start_char_idx, n.end_char_idx) for n in members], text)):
            continue
        units = [{**u, 'start': a+u['start'], 'end': a+u['end'], 'body_start': a+u['body_start']}
                 for u in structural_units(text[a:b])]
        result['sections'][key] = {'members': tuple(members), 'units': tuple(units),
                                   'subject': next(iter(subjects))}
    result['prepare_ms'] = round((perf_counter()-started)*1000, 3)
    return result


def _evidence(candidate, raw, unit, members, documents):
    source, document, text, _, _ = _checked(raw, documents)
    a, b = unit['start'], unit['end']
    overlapping = [n for n in members if n.start_char_idx < b and n.end_char_idx > a
                   and text[max(a, n.start_char_idx):min(b, n.end_char_idx)].strip()]
    for n in overlapping:
        member_source, _, _, _, _ = _checked(n, documents)
        if member_source != source or _subject(n) != _subject(raw):
            raise ValueError('Prepared block source/subject changed.')
    if not _covered(a, b, [(n.start_char_idx, n.end_char_idx) for n in overlapping], text):
        raise ValueError('Block lacks complete source-node provenance.')
    roles = list(dict.fromkeys(n.metadata.get('evidence_role', 'UNKNOWN') for n in overlapping))
    headers = _headers(raw, source, document, text, a, b)
    role_spans = [{'start_char': max(a, n.start_char_idx), 'end_char': min(b, n.end_char_idx),
                   'node_id': n.node_id, 'evidence_role': n.metadata.get('evidence_role', 'UNKNOWN'),
                   'evidence_role_basis': n.metadata.get('evidence_role_basis', 'unclassified')}
                  for n in overlapping]
    item = {'citation_id': '', 'source_id': source, 'subject_source_id': _subject(raw),
            'subject_title': _field(documents.get(_subject(raw), {}), 'title', raw.metadata.get('subject_title', '')),
            'title': _field(document, 'title', source), 'url': _field(document, 'url', ''),
            'section': raw.metadata.get('section', ''), 'sections': [raw.metadata.get('section', '')],
            'text': text[a:b], 'start_char': a, 'end_char': b,
            'source_sha256': sha256(text.encode()).hexdigest(), 'score': float(candidate.score),
            'core_node_ids': [raw.node_id],
            'expanded_node_ids': [n.node_id for n in overlapping if n.node_id != raw.node_id],
            'table_headers': headers, 'evidence_roles': roles, 'evidence_role_spans': role_spans}
    item['node_id'] = 'context-' + sha256(
        f"{source}:{_subject(raw)}:{a}:{b}:{_header_text(item)}:{item['text']}".encode()).hexdigest()
    return item


def supplement_context(base, ranked_groups, source_nodes, documents, tokenizer, extra_tokens=1200, *,
                       strategy='blocks', max_total_tokens=5200, max_spans=6, max_span_tokens=320,
                       max_candidates=96, prepared_index=None, prefer_own_subject=True):
    started = perf_counter()
    if strategy not in {'blocks', 'body-blocks'}:
        raise ValueError('Unknown block supplement strategy.')
    for value in (extra_tokens, max_total_tokens, max_spans, max_span_tokens, max_candidates):
        if type(value) is not int or value < 0:
            raise ValueError('Bounds must be nonnegative integers.')
    if not max_total_tokens or not max_span_tokens or not max_candidates:
        raise ValueError('Token/candidate bounds must be positive.')
    if sum(map(len, ranked_groups.values())) > max_candidates:
        raise ValueError('Scored pair bound exceeded.')
    result = deepcopy(base)
    baseline = base['context']
    if '\n\n'.join(map(render_item, base['evidence'])) != baseline:
        raise ValueError('Baseline evidence does not reconstruct its context.')
    base_tokens = len(_encode(tokenizer, baseline))
    if base_tokens > max_total_tokens or len(base['evidence']) > 64:
        raise ValueError('Baseline exceeds output bounds.')
    ceiling = min(max_total_tokens, base_tokens+extra_tokens)
    index = prepared_index if prepared_index is not None else prepare_block_index(source_nodes, documents)
    covered = defaultdict(list)
    for e in base['evidence']:
        covered[(e['source_id'], e['subject_source_id'])].append((e['start_char'], e['end_char']))
    tiers = [defaultdict(deque) for _ in range(3)]
    rejected, accepted, seen, checked_sources = [], [], set(), set()
    # Immutable source slices can recur across overlapping nodes/query groups.
    # Cache only their text-derived work; every candidate still enters the same
    # validation, rejection and queue logic in its original order.
    unit_token_counts, unit_body_signals = {}, {}
    broad = base.get('audit', {}).get('query_hints', {}).get('broad_discovery', False)
    for group, candidates in ranked_groups.items():
        if any(c.score is None or not isfinite(float(c.score)) for c in candidates):
            raise ValueError('Scores must be finite.')
        for rank, candidate in enumerate(sorted(candidates, key=lambda c: -float(c.score)), 1):
            raw = source_nodes[candidate.node.node_id]
            source, _, text, ca, cb = _checked(raw, documents)
            if source != candidate.node.metadata['source_id'] or _subject(raw) != _subject(candidate.node):
                raise ValueError('Scored/raw node identity mismatch.')
            if source not in checked_sources:
                if index['document_sha256'].get(source) != sha256(text.encode()).hexdigest():
                    raise ValueError('Prepared source content changed.')
                checked_sources.add(source)
            key = (source, raw.metadata.get('section_start_char_idx'), raw.metadata.get('section_end_char_idx'))
            section = index['sections'].get(key)
            if not section or section['subject'] != _subject(raw):
                rejected.append({'node_id': raw.node_id, 'reason': 'unproven_or_oversized_section'})
                continue
            for unit in section['units']:
                a, b = unit['start'], unit['end']
                # The unit must contain substantive text seen in this scored
                # core; merely sharing a distant section is not sufficient.
                if a >= cb or b <= ca or not text[max(a, ca):min(b, cb)].strip():
                    continue
                unit_key = (source, a, b)
                if unit_key not in unit_token_counts:
                    unit_token_counts[unit_key] = len(_encode(tokenizer, text[a:b]))
                if unit_token_counts[unit_key] > max_span_tokens:
                    rejected.append({'node_id': raw.node_id, 'reason': 'whole_block_token_limit',
                                     'start_char': a, 'end_char': b})
                    continue
                if unit_key not in unit_body_signals:
                    unit_body_signals[unit_key] = body_text_signal(text[a:b])
                signal = unit_body_signals[unit_key]
                ordinary = signal['eligible'] or (unit['label_retained'] and signal['plain_words'] > 0
                                                  and signal['plain_fraction'] >= .25)
                tier = (0 if not prefer_own_subject or broad or source == _subject(raw) else 1) if ordinary else 2
                tiers[tier][(group, _subject(raw))].append((candidate, raw, unit, section['members'], rank))
    for tier_number, lanes in enumerate(tiers):
        while lanes and len(accepted) < min(6, max_spans, 64-len(base['evidence'])) and extra_tokens:
            for lane, queue in list(lanes.items()):
                while queue and len(accepted) < min(6, max_spans, 64-len(base['evidence'])):
                    candidate, raw, unit, members, rank = queue.popleft()
                    key = (str(raw.metadata['source_id']), _subject(raw))
                    signature = (*key, unit['start'], unit['end'])
                    if signature in seen:
                        continue
                    seen.add(signature)
                    text = _field(documents[key[0]], 'text')
                    if _covered(unit['start'], unit['end'], covered[key], text):
                        rejected.append({'node_id': raw.node_id, 'reason': 'block_already_covered',
                                         'start_char': unit['start'], 'end_char': unit['end']})
                        continue
                    item = _evidence(candidate, raw, unit, members, documents)
                    item['citation_id'] = str(len(result['evidence'])+1)
                    context = result['context'] + ('\n\n' if result['context'] else '') + render_item(item)
                    tokens = len(_encode(tokenizer, context))
                    if tokens > ceiling:
                        rejected.append({'node_id': raw.node_id, 'reason': 'total_token_limit',
                                         'start_char': unit['start'], 'end_char': unit['end']})
                        continue
                    previous = len(_encode(tokenizer, result['context']))
                    result['context'] = context
                    result['evidence'].append(item)
                    covered[key].append((unit['start'], unit['end']))
                    accepted.append({'node_id': raw.node_id, 'query_group': lane[0], 'subject': lane[1],
                                     'rank_in_group': rank, 'kind': unit['kind'], 'tier': tier_number,
                                     'label_retained': unit['label_retained'],
                                     'start_char': unit['start'], 'end_char': unit['end'],
                                     'marginal_tokens': tokens-previous})
                    break
                if not queue:
                    lanes.pop(lane, None)
    result['context_tokens'] = len(_encode(tokenizer, result['context']))
    result['context_sha256'] = sha256(result['context'].encode()).hexdigest()
    result.setdefault('audit', {})['supplement'] = {
        'version': 'bounded-source-blocks-v1', 'strategy': strategy,
        'baseline_sha256': sha256(baseline.encode()).hexdigest(), 'baseline_tokens': base_tokens,
        'token_ceiling': ceiling, 'accepted': accepted, 'rejected': rejected,
        'baseline_prefix_preserved': result['context'].startswith(baseline), 'additional_scored_pairs': 0,
        'prepared_index_reused': prepared_index is not None,
        'index_prepare_ms': index['prepare_ms'] if prepared_index is None else 0,
        'elapsed_ms': round((perf_counter()-started)*1000, 3)}
    assert result['context'].startswith(baseline)
    assert result['evidence'][:len(base['evidence'])] == base['evidence']
    return result
