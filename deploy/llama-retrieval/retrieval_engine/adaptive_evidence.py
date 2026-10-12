"""Bounded routing and evidence coverage for multi-document questions."""
import re
from collections import Counter
from dataclasses import replace

from .query_constraints import query_hints, _title_mentions, folded_word, words, title_is_excluded, _literal_catalog_subjects


def routing_hints(question, documents, exclusion_titles=(), *, max_subjects=8):
    if not isinstance(max_subjects, int) or isinstance(max_subjects, bool) or not 2 <= max_subjects <= 8:
        raise ValueError('Comparison subjects must be an integer from2 through8.')
    documents = list(documents)
    hints = query_hints(question, documents, exclusion_titles=exclusion_titles)
    literal = _literal_catalog_subjects(question, documents, hints.excluded_title_terms)
    # Short capitalized model names and omitted accents are common website
    # aliases. A lead word must be unique across all corpus title vocabulary.
    counts = Counter(word for doc in documents for word in set(map(folded_word, words(doc['title']))))
    query_words = set(map(folded_word, words(question)))
    alias_ids = []
    for doc in documents:
        lead = re.search(r'[^\W_]+', doc['title'], re.UNICODE)
        if (lead and lead.group().isupper() and len(lead.group()) >= 4
                and counts[folded_word(lead.group())] == 1
                and folded_word(lead.group()) in query_words
                and not title_is_excluded(doc['title'], hints)):
            alias_ids.append(doc['source_id'])
    # Complete strict entity recognition before accepting a partial matcher.
    # Otherwise two long names can hide a third short/accent-folded model name.
    # These are explicit corpus identities; the scored-pair/context budgets do
    # not grow with this cap. Over-cap requests keep unrestricted retrieval.
    resolved = tuple(dict.fromkeys([*hints.comparison_source_ids, *literal, *alias_ids]))
    if len(resolved) > max_subjects:
        return replace(hints, comparison_source_ids=())
    if 2 <= len(resolved) <= max_subjects:
        return replace(hints, comparison_source_ids=resolved, broad_discovery=False)
    probe = query_hints('compare ' + question, documents, exclusion_titles=exclusion_titles)
    titles = [doc['title'] for doc in documents if doc['source_id'] in probe.comparison_source_ids]
    # One shared family name must not turn a single variant into a comparison.
    if len(probe.comparison_source_ids) >= 2 and len(_title_mentions(question, titles)) >= 2:
        return replace(hints, comparison_source_ids=probe.comparison_source_ids)
    if (hints.broad_discovery and not re.search(r'\b(?:options|products|suggest|recommend)\b', question, re.I)
            and len(_title_mentions(question, [doc['title'] for doc in documents])) == 1):
        # "Which materials are in <one named item>?" is a property question,
        # even though a plural follows "which".
        return replace(hints, broad_discovery=False)
    return hints


def evidence_limits(config, comparison_count, targeted_discovery):
    pairs, cores = config.rerank_candidates, config.evidence_top_k
    if config.adaptive_evidence:
        if comparison_count >= 2:
            pairs = min(config.retriever_top_k * 2, max(pairs, 96))
            cores = min(pairs, max(cores, 16))
        elif targeted_discovery:
            cores = min(pairs, max(cores, 16))
    return pairs, cores


def distinct_subjects(ranked, documents, limit=4):
    result = []
    for item in ranked:
        source = item.node.metadata.get('subject_source_id', item.node.metadata['source_id'])
        if source in documents and source not in result:
            result.append(source)
        if len(result) >= limit:
            break
    return result


def retain_source_and_detail(ranked, selected, anchor_groups, max_count):
    """Keep a scored source introduction and a scored detail for broad options.

    Routing summaries never enter the answer context. The retained nodes are
    indexed original passages; all have passed through the same reranker.
    """
    by_id = {item.node.node_id: item for item in ranked}
    result, seen = [], set()
    for ids in anchor_groups.values():
        for node_id in ids[:1]:
            if node_id in by_id and node_id not in seen and len(result) < max_count:
                result.append(by_id[node_id])
                seen.add(node_id)
    represented = set()
    for item in ranked:
        subject = item.node.metadata.get('subject_source_id', item.node.metadata['source_id'])
        if item.node.node_id not in seen and subject not in represented and len(result) < max_count:
            result.append(item)
            seen.add(item.node.node_id)
            represented.add(subject)
    for item in selected:
        if item.node.node_id not in seen and len(result) < max_count:
            result.append(item)
            seen.add(item.node.node_id)
    return result


def preserve_retrieved_anchor_spans(scoped, anchors):
    """Reuse the first retrieved span when its model view duplicates an anchor.

    Equal model text can have different original offsets and neighbors. Keep
    the existing representative rather than replacing its surrounding evidence.
    """
    def identity(item):
        metadata = item.node.metadata
        return (metadata['source_id'], metadata.get('subject_source_id', metadata['source_id']),
                ' '.join(item.node.text.split()))
    existing = {}
    for item in scoped:
        existing.setdefault(identity(item), item)
    return [existing.get(identity(item), item) for item in anchors]


def anchors_without_primary_evidence(selected, anchor_groups):
    primary = {item.node.metadata.get('subject_source_id', item.node.metadata['source_id'])
               for item in selected if item.node.metadata.get('evidence_role') == 'PRIMARY'}
    return {source: ids for source, ids in anchor_groups.items() if source not in primary}


def scoped_query(question, target_title, compared_titles, focused):
    """Avoid appending a redundant title when competing names remain unresolved."""
    ambiguous = len(_title_mentions(question, compared_titles)) < len(compared_titles)
    prefix = target_title + '. '
    if ambiguous and focused.startswith(prefix) and focused[len(prefix):].strip():
        return focused[len(prefix):].strip(), True
    return focused, False


def ranking_projection(nodes, omit_title=False):
    if not omit_title:
        return nodes
    result = []
    for item in nodes:
        copied = item.model_copy(deep=True)
        copied.node.text = re.sub(r'^document_title:[^\n]*\n?', '', copied.node.text)
        result.append(copied)
    return result
