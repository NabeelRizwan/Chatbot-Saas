"""Supplement-only ablation: require ordinary source text outside media/links.

Baseline context, candidate generation, model inputs and CE scores are unchanged.
The generic Markdown screen suppresses media/gallery/link-control passages for
new supplemental slots. It is a structural heuristic, not truth/relevance or
relation entailment. Image-only facts remain eligible as a fallback after
ordinary source text has had its chance to use the bounded extra allowance.
"""
from __future__ import annotations

import re
from time import perf_counter
from markdown_it import MarkdownIt

from .context_supplement import supplement_context as _original, _checked

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


def supplement_context(base, ranked_groups, source_nodes, documents, tokenizer,
                       extra_tokens=1200, *, strategy='body-section', **kwargs):
    started = perf_counter()
    if strategy not in {'body-core', 'body-section', 'core', 'section'}:
        raise ValueError('Unknown structural screen strategy.')
    if sum(map(len, ranked_groups.values())) > kwargs.get('max_candidates', 96):
        raise ValueError('Scored candidate bound exceeded.')
    filtered, fallback, audit, signal_cache = {}, {}, [], {}
    for group, candidates in ranked_groups.items():
        retained, media = [], []
        for candidate in candidates:
            node_id = candidate.node.node_id
            raw = source_nodes[node_id]
            _checked(raw, documents)
            if node_id not in signal_cache:
                signal_cache[node_id] = body_text_signal(raw.text)
            signal = signal_cache[node_id]
            audit.append({'node_id': node_id, 'query_group': group, **signal})
            if signal['eligible']:
                retained.append(candidate)
            else:
                media.append(candidate)
        filtered[group] = retained
        fallback[group] = media
    result = _original(base, filtered, source_nodes, documents, tokenizer,
                       extra_tokens, strategy=strategy.removeprefix('body-'), **kwargs)
    first_audit = result['audit']['supplement']
    for accepted in first_audit['accepted']:
        accepted['structural_stage'] = 'ordinary_source_text'
    added = len(first_audit['accepted'])
    remaining = max(0, first_audit['token_ceiling'] - result['context_tokens'])
    remaining_spans = max(0, min(6, kwargs.get('max_spans', 6)) - added)
    if remaining and remaining_spans and any(fallback.values()):
        fallback_options = {**kwargs, 'max_spans': remaining_spans}
        result = _original(result, fallback, source_nodes, documents, tokenizer,
                           remaining, strategy=strategy.removeprefix('body-'), **fallback_options)
        last_audit = result['audit']['supplement']
        for accepted in last_audit['accepted']:
            accepted['structural_stage'] = 'media_or_link_fallback'
        result['audit']['supplement'] = {
            **first_audit,
            'accepted': [*first_audit['accepted'], *last_audit['accepted']],
            'rejected': [*first_audit['rejected'], *last_audit['rejected']]}
    result['audit']['supplement']['version'] = 'draft-structural-source-spans-v2'
    result['audit']['supplement']['body_screen'] = audit
    result['audit']['supplement']['body_screen_policy'] = {
        'min_plain_words': 6, 'min_plain_fraction': 0.25,
        'purpose': 'supplemental source text outside headings, media captions, and link labels'}
    result['audit']['supplement']['elapsed_ms'] = round((perf_counter() - started) * 1000, 3)
    return result
