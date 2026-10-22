"""Bounded semantic second pass over complete, already-retrieved source blocks.

This module does not import or call a model, retriever, embedding API, or network
client. prepare_candidates() freezes at most 32 query/block pairs; the caller
scores them using the already loaded cross encoder and passes the scores to
assemble(). The original context and evidence are immutable prefixes.
"""
from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy
from hashlib import sha256
import json
from math import isfinite
from time import perf_counter

from markdown_it import MarkdownIt
from .context_blocks_six_span_control import prepare_block_index, _evidence
from .context_supplement import _checked, _covered, _encode, _field, _subject, render_item
from .context_structural import body_text_signal

_PARSER = MarkdownIt('commonmark', {'html': False}).enable('table')
VERSION = 'bounded-semantic-source-blocks-v1'


def _json_hash(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def readable_block(text):
    """Readable model view only; exact source Markdown remains in evidence.

    Keep visible prose, labels, list items, code and all table cells. Remove
    image captions, image URLs and link destinations, not linked visible words.
    Table rows retain explicit cell separators. No model tokens are truncated.
    """
    lines, row = [], None
    for token in _PARSER.parse(text):
        if token.type == 'tr_open':
            row = []
        elif token.type == 'tr_close':
            lines.append(' | '.join(row or []))
            row = None
        elif token.type == 'inline':
            parts = []
            for child in token.children or []:
                if child.type in {'text', 'code_inline'}:
                    parts.append(child.content)
                elif child.type in {'softbreak', 'hardbreak'}:
                    parts.append('\n')
                # Images (including factual alt text) are not added to this
                # ordinary-source-text scoring view. Raw citations keep them.
            value = ''.join(parts).strip()
            if row is not None:
                row.append(value)
            elif value:
                lines.append(value)
        elif token.type in {'fence', 'code_block'} and token.content.strip():
            lines.append(token.content.rstrip())
    return '\n'.join(lines)


class _Sources:
    """Deterministic round robin among verified subjects in one query group."""
    def __init__(self, ordered):
        subjects = {}
        for item in ordered:
            subjects.setdefault(item['item']['subject_source_id'], deque()).append(item)
        self.lanes = deque(subjects.values())

    def pop(self):
        if not self.lanes:
            return None
        lane = self.lanes.popleft()
        value = lane.popleft()
        if lane:
            self.lanes.append(lane)
        return value


def _baseline(base, tokenizer):
    if '\n\n'.join(map(render_item, base['evidence'])) != base['context']:
        raise ValueError('Baseline evidence does not reconstruct its context.')
    if len(base['evidence']) > 64:
        raise ValueError('Baseline evidence inventory exceeds the service bound.')
    covered = defaultdict(list)
    for index, item in enumerate(base['evidence'], 1):
        if item['citation_id'] != str(index):
            raise ValueError('Baseline citations are not sequential.')
        covered[(item['source_id'], item['subject_source_id'])].append((item['start_char'], item['end_char']))
    return covered, len(_encode(tokenizer, base['context']))


def _query(base, group):
    audit = base.get('audit', {})
    explicit = audit.get('scoped_queries', {}).get(group)
    if explicit is not None:
        query = explicit
    elif group == 'global':
        query = audit.get('query_hints', {}).get('retrieval_query') or base.get('question')
    else:
        # An unresolved scoped lane must not silently switch to another task.
        raise ValueError('Scoped query group has no recorded ranking query.')
    if not isinstance(query, str) or not query.strip():
        raise ValueError('A recorded ranking query is required.')
    return query


def prepare_candidates(base, groups, nodes, docs, tokenizer, index=None, *,
                       pair_tokenizer=None, max_pairs=32, max_block_tokens=240):
    """Return {proposals, audit} without performing inference.

    Each proposal contains key/query/model_text/item/group/parent_rank/node_id/
    pair_tokens/prepared_sha256. `item` follows the existing source evidence
    schema with an empty citation ID. The exact cross-encoder tokenizer is
    required; query plus full title/block must fit 512 tokens without truncation.
    """
    started = perf_counter()
    if type(max_pairs) is not int or not 0 <= max_pairs <= 32:
        raise ValueError('Additional pair budget must be an integer from zero through32.')
    if type(max_block_tokens) is not int or not 1 <= max_block_tokens <= 320:
        raise ValueError('Block budget must be an integer from one through320.')
    if pair_tokenizer is None:
        raise ValueError('Supply the loaded cross-encoder tokenizer for exact pair-limit verification.')
    if sum(map(len, groups.values())) > 96:
        raise ValueError('Original scored-pair inventory exceeds96.')
    covered, base_tokens = _baseline(base, tokenizer)
    prepared = index if index is not None else prepare_block_index(nodes, docs)
    pools, rejected, seen, checked_sources = {}, [], set(), set()
    eligible_per_group = {}
    for group, candidates in groups.items():
        query = _query(base, group)
        if any(c.score is None or not isfinite(float(c.score)) for c in candidates):
            raise ValueError('Original candidate scores must be finite.')
        eligible = []
        for rank, candidate in enumerate(sorted(candidates, key=lambda c: -float(c.score)), 1):
            node_id = candidate.node.node_id
            raw = nodes[node_id]
            source, document, text, ca, cb = _checked(raw, docs)
            subject = _subject(raw)
            if candidate.node.metadata['source_id'] != source or _subject(candidate.node) != subject:
                raise ValueError('Scored/raw node identity mismatch.')
            if source != subject:
                rejected.append({'node_id': node_id, 'group': group, 'reason': 'linked_subject'})
                continue
            if source not in checked_sources:
                if prepared['document_sha256'].get(source) != sha256(text.encode()).hexdigest():
                    raise ValueError('Prepared source content changed.')
                checked_sources.add(source)
            section = prepared['sections'].get((source, raw.metadata.get('section_start_char_idx'),
                                                raw.metadata.get('section_end_char_idx')))
            if not section or section['subject'] != subject:
                rejected.append({'node_id': node_id, 'group': group, 'reason': 'unproven_section'})
                continue
            for unit in section['units']:
                a, b = unit['start'], unit['end']
                signature = (group, source, subject, a, b)
                if signature in seen or a >= cb or b <= ca or not text[max(a, ca):min(b, cb)].strip():
                    continue
                seen.add(signature)
                reason = None
                if _covered(a, b, covered[(source, subject)], text):
                    reason = 'already_covered'
                elif len(_encode(tokenizer, text[a:b])) > max_block_tokens:
                    reason = 'complete_block_token_limit'
                signal = body_text_signal(text[a:b])
                ordinary = signal['eligible'] or (unit['label_retained'] and signal['plain_words'] > 0
                                                  and signal['plain_fraction'] >= .25)
                if reason is None and not ordinary:
                    reason = 'not_ordinary_source_text'
                if reason:
                    rejected.append({'node_id': node_id, 'group': group, 'reason': reason,
                                     'start_char': a, 'end_char': b})
                    continue
                body = readable_block(text[a:b])
                if not body.strip():
                    continue
                model_text = f"document_title: {_field(document, 'title', source)}\n\n{body}"
                encoded = pair_tokenizer(query, model_text, truncation=False, add_special_tokens=True)
                ids = encoded['input_ids']
                if not isinstance(ids, (list, tuple)) or any(not isinstance(value, int) for value in ids):
                    raise ValueError('Pair tokenizer must return one unbatched sequence of input IDs.')
                if len(ids) > 512:
                    rejected.append({'node_id': node_id, 'group': group, 'reason': 'pair_token_limit',
                                     'pair_tokens': len(ids), 'start_char': a, 'end_char': b})
                    continue
                item = _evidence(candidate, raw, unit, section['members'], docs)
                proposal = {'key': _json_hash([*signature, query, model_text]), 'query': query,
                            'model_text': model_text, 'item': item, 'group': group,
                            'parent_rank': rank, 'node_id': node_id, 'pair_tokens': len(ids)}
                proposal['prepared_sha256'] = _json_hash(proposal)
                eligible.append(proposal)
        eligible_per_group[group] = len(eligible)
        if eligible:
            pools[group] = _Sources(eligible)
    proposals, quotas = [], {}
    active = list(pools)
    for position, group in enumerate(active):
        quota = max_pairs // len(active) + (position < max_pairs % len(active))
        quotas[group] = quota
        for _ in range(quota):
            proposal = pools[group].pop()
            if proposal is None:
                break
            proposals.append(proposal)
    # Reuse unfilled quotas, without letting one short group waste capacity.
    while len(proposals) < max_pairs:
        before = len(proposals)
        for group in active:
            proposal = pools[group].pop()
            if proposal is not None:
                proposals.append(proposal)
            if len(proposals) == max_pairs:
                break
        if before == len(proposals):
            break
    audit = {'version': VERSION, 'max_pairs': max_pairs, 'prepared_pairs': len(proposals),
             'max_block_tokens': max_block_tokens, 'pair_limit': 512,
             'max_pair_tokens': max((p['pair_tokens'] for p in proposals), default=0),
             'baseline_tokens': base_tokens, 'eligible_per_group': eligible_per_group,
             'initial_group_quotas': quotas, 'rejected': rejected,
             'prepared_index_reused': index is not None,
             'preparation_ms': round((perf_counter()-started)*1000, 3),
             'inference_calls': 0, 'new_retrieval_calls': 0, 'new_embedding_calls': 0}
    return {'proposals': proposals, 'audit': audit}


def assemble(base, proposals, scores, tokenizer, *, extra_tokens=1200,
             max_spans=6, max_total_tokens=5200):
    """Append complete scored blocks; never pool logits across query groups."""
    started = perf_counter()
    if type(extra_tokens) is not int or not 0 <= extra_tokens <= 1200:
        raise ValueError('Extra token budget must be between zero and1200.')
    if type(max_spans) is not int or not 0 <= max_spans <= 6:
        raise ValueError('At most six semantic supplements are supported.')
    if type(max_total_tokens) is not int or not 1 <= max_total_tokens <= 5200:
        raise ValueError('Total token budget must be between one and5200.')
    if len(proposals) > 32 or len(proposals) != len(scores):
        raise ValueError('Scores must match the bounded proposal inventory exactly.')
    if len({p['key'] for p in proposals}) != len(proposals):
        raise ValueError('Duplicate prepared pair keys.')
    covered, base_tokens = _baseline(base, tokenizer)
    if base_tokens > max_total_tokens:
        raise ValueError('Baseline exceeds the configured output budget.')
    ceiling = min(max_total_tokens, base_tokens+extra_tokens)
    grouped = {}
    for proposal, score in zip(proposals, scores):
        if not isfinite(float(score)):
            raise ValueError('Block scores must be finite.')
        expected = proposal['prepared_sha256']
        if _json_hash({k: v for k, v in proposal.items() if k != 'prepared_sha256'}) != expected:
            raise ValueError('Prepared proposal changed after scoring input was frozen.')
        row = deepcopy(proposal)
        row['block_score'] = float(score)
        grouped.setdefault(row['group'], []).append(row)
    pools = {group: _Sources(sorted(rows, key=lambda p: -p['block_score']))
             for group, rows in grouped.items()}
    result = deepcopy(base)
    accepted, rejected = [], []
    count_limit = min(max_spans, 64-len(base['evidence']))
    while pools and len(accepted) < count_limit and extra_tokens:
        for group in list(pools):
            while len(accepted) < count_limit:
                proposal = pools[group].pop()
                if proposal is None:
                    pools.pop(group)
                    break
                item = proposal['item']
                key = (item['source_id'], item['subject_source_id'])
                # Compare source intervals without needing another corpus read.
                # Only complete containment suppresses a prepared block here.
                if any(a <= item['start_char'] and item['end_char'] <= b for a, b in covered[key]):
                    rejected.append({'key': proposal['key'], 'reason': 'already_covered'})
                    continue
                item['citation_id'] = str(len(result['evidence'])+1)
                item['score'] = proposal['block_score']
                context = result['context'] + ('\n\n' if result['context'] else '') + render_item(item)
                tokens = len(_encode(tokenizer, context))
                if tokens > ceiling:
                    rejected.append({'key': proposal['key'], 'reason': 'total_token_limit'})
                    continue
                prior_tokens = len(_encode(tokenizer, result['context']))
                result['context'] = context
                result['evidence'].append(item)
                covered[key].append((item['start_char'], item['end_char']))
                accepted.append({'key': proposal['key'], 'group': group, 'node_id': proposal['node_id'],
                                 'parent_rank': proposal['parent_rank'], 'block_score': proposal['block_score'],
                                 'marginal_tokens': tokens-prior_tokens})
                break
    result['context_tokens'] = len(_encode(tokenizer, result['context']))
    result['context_sha256'] = sha256(result['context'].encode()).hexdigest()
    result.setdefault('audit', {})['semantic_block_supplement'] = {
        'version': VERSION, 'baseline_sha256': sha256(base['context'].encode()).hexdigest(),
        'baseline_tokens': base_tokens, 'token_ceiling': ceiling, 'span_limit': max_spans,
        'additional_scored_pairs': len(proposals), 'accepted': accepted, 'rejected': rejected,
        'baseline_prefix_preserved': result['context'].startswith(base['context']),
        'assembly_ms': round((perf_counter()-started)*1000, 3)}
    assert result['context'].startswith(base['context'])
    assert result['evidence'][:len(base['evidence'])] == base['evidence']
    return result
