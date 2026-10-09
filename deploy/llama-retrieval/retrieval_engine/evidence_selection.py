# SPDX-FileCopyrightText: 2022-present deepset GmbH <info@deepset.ai>
# SPDX-License-Identifier: Apache-2.0
"""Bounded evidence selection with cached embeddings and source provenance.

The MMR selection loop is adapted from Haystack's
SentenceTransformersDiversityRanker._maximum_margin_relevance at commit
e1376b4cee1703606e0202f010c706189ef93fc9. See
third_party/haystack_mmr/NOTICE.txt for source, license and modifications.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import TYPE_CHECKING, Iterable
from collections.abc import Mapping, Sequence

import numpy as np

if TYPE_CHECKING:
    from llama_index.core.schema import NodeWithScore


def _source(item: NodeWithScore) -> str:
    node = item.node
    return str(node.metadata.get("source_id") or node.ref_doc_id or node.node_id)


def _fact_scope(item: NodeWithScore) -> str:
    # Only a parser-verified linked subject can unify copies across pages.
    # Unrelated documents with identical prose retain separate attribution.
    return str(item.node.metadata.get('subject_source_id') or _source(item))


def _text(item: NodeWithScore) -> str:
    # Normalization is used only for comparison; source text is never modified.
    return " ".join(item.node.get_content().casefold().split())


def _score(item: NodeWithScore) -> float | None:
    value = item.score
    return float(value) if value is not None and math.isfinite(value) else None


def deduplicate_evidence(ranked: Iterable[NodeWithScore]) -> list[NodeWithScore]:
    """Remove repeated nodes and already-covered text within the same source.

    Mere semantic similarity or overlapping offsets do not justify deletion:
    a short differing number or negation can change the answer. A later passage
    is discarded only if its entire normalized text is already present in a
    retained passage. Identical text from distinct sources remains attributable.
    """
    result = []
    seen_ids: set[str] = set()
    texts: dict[str, list[str]] = {}
    for item in ranked:
        node_id = item.node.node_id
        text = _text(item)
        if not text or node_id in seen_ids:
            continue
        source = _fact_scope(item)
        if any(text == prior or (len(text) >= 80 and text in prior)
               for prior in texts.get(source, [])):
            continue
        seen_ids.add(node_id)
        texts.setdefault(source, []).append(text)
        result.append(item)
    return result


def choose_evidence(
    ranked: list[NodeWithScore],
    max_count: int,
    document_coverage_ids: Iterable[str] | None = None,
    *,
    diversity_strength: float = 0.15,
    source_penalty: float = 0.04,
    coverage_per_document: int = 2,
    score_margin: float = 3.0,
    min_score: float | None = None,
    selection_scores: Mapping[str, float] | None = None,
) -> list[NodeWithScore]:
    """Select relevant, non-redundant evidence without changing nodes or scores.

    ``diversity_strength=0`` preserves rank order apart from deduplication and
    explicit coverage. Larger values trade relevance for diversity; callers may
    choose a stronger value for broad discovery. There is no hard source cap.
    Source coverage is supplied by the caller, never inferred from page names.
    Optional second/third passages must stay within ``score_margin`` of that
    source's best score. MMR cannot promote a candidate more than this margin
    below the best currently available score. ``min_score`` can enforce a
    calibrated relevance floor; none is guessed for a new domain.

    Cached ``node.embedding`` vectors are reused. If unavailable or invalid,
    lexical shingles provide a conservative redundancy signal without loading
    a model. The returned objects are the original NodeWithScore instances.
    """
    if max_count < 0 or coverage_per_document < 1:
        raise ValueError("Evidence count must be nonnegative and coverage positive.")
    if not 0 <= diversity_strength <= 1 or source_penalty < 0 or score_margin < 0:
        raise ValueError("Invalid diversity or relevance margin.")
    if max_count == 0:
        return []
    candidates = deduplicate_evidence(ranked)
    if min_score is not None:
        candidates = [item for item in candidates
                      if _score(item) is not None and _score(item) >= min_score]
    if not candidates:
        return []
    count = len(candidates)
    scores = [_score(item) for item in candidates]
    utility_scores = [selection_scores.get(item.node.node_id, scores[i])
                      if selection_scores else scores[i] for i,item in enumerate(candidates)]
    if any(value is not None and not math.isfinite(value) for value in utility_scores):
        raise ValueError('Selection scores must be finite.')
    finite = [score for score in utility_scores if score is not None]
    low, high = (min(finite), max(finite)) if finite else (0.0, 0.0)
    relevance = [
        (score - low) / (high - low) if score is not None and high > low
        else 1.0 if score is not None else 1.0 - i / max(1, count)
        for i, score in enumerate(utility_scores)
    ]
    # A linked product card can be repeated across several source pages. Count
    # its known subject once for diversity, retaining the selected page's URL.
    sources = [str(item.node.metadata.get('subject_source_id') or _source(item)) for item in candidates]
    vectors = []
    shingles = []
    for item in candidates:
        raw = item.node.embedding
        vector = np.asarray(raw, dtype=float) if raw is not None else np.empty(0)
        norm = np.linalg.norm(vector)
        vectors.append(vector / norm if vector.ndim == 1 and norm > 0
                       and np.isfinite(vector).all() else None)
        words = re.findall(r"\w+", _text(item))
        shingles.append(set(zip(words, words[1:], words[2:])) if len(words) >= 3
                        else set(words))
    similarities: dict[tuple[int, int], float] = {}

    def similarity(left: int, right: int) -> float:
        key = (min(left, right), max(left, right))
        if key not in similarities:
            a, b = vectors[left], vectors[right]
            if a is not None and b is not None and a.shape == b.shape:
                value = float(np.dot(a, b))
            else:
                union = shingles[left] | shingles[right]
                value = len(shingles[left] & shingles[right]) / len(union) if union else 0.0
            similarities[key] = max(0.0, min(1.0, value))
        return similarities[key]

    selected: list[int] = []
    source_counts: Counter[str] = Counter()

    def add(index: int) -> None:
        selected.append(index)
        source_counts[sources[index]] += 1

    targets = set(map(str, document_coverage_ids or []))
    groups = {source: [i for i, value in enumerate(sources) if value == source]
              for source in targets}
    # Coverage respects the ranking order, including when the budget is smaller
    # than the number of requested sources. Missing sources are not fabricated.
    ordered_targets = sorted((source for source in targets if groups[source]),
                             key=lambda source: groups[source][0])
    for position in range(coverage_per_document):
        for source in ordered_targets:
            group = groups[source]
            if position >= len(group) or len(selected) >= max_count:
                continue
            index = group[position]
            first_score, candidate_score = scores[group[0]], scores[index]
            if position and first_score is not None and candidate_score is not None:
                if first_score - candidate_score > score_margin:
                    continue
            add(index)

    while len(selected) < min(max_count, count):
        remaining = [i for i in range(count) if i not in selected]
        available_scores = [scores[i] for i in remaining if scores[i] is not None]
        best_remaining_score = max(available_scores) if available_scores else None
        eligible = [i for i in remaining if best_remaining_score is None
                    or scores[i] is None or best_remaining_score - scores[i] <= score_margin]
        best_index = None
        best_value = -math.inf
        for index in eligible:
            redundancy = max((similarity(index, prior) for prior in selected), default=0.0)
            source_repetition = math.log2(1 + source_counts[sources[index]])
            value = ((1 - diversity_strength) * relevance[index]
                     - diversity_strength * redundancy
                     - diversity_strength * source_penalty * source_repetition)
            if value > best_value:
                best_value = value
                best_index = index
        assert best_index is not None
        add(best_index)
    return [candidates[index] for index in selected]


def choose_grouped_evidence(
    groups: Mapping[str, Sequence[NodeWithScore]],
    max_count: int,
    *,
    diversity_strength: float = 0.15,
    source_penalty: float = 0.04,
    score_margin: float = 3.0,
    min_score: float | None = None,
    selection_scores: Mapping[str, Mapping[str, float]] | None = None,
) -> list[NodeWithScore]:
    """MMR within each query group, followed by balanced unique round-robin.

    Mapping insertion order is the caller's stable coverage priority. A group
    may represent a subject/facet cell; group keys are opaque here. Scores are
    compared and normalized only inside their own query group, never globally.

    Duplicate IDs and identical normalized text from the same source consume one
    slot across groups. A skipped duplicate does not waste that group's turn: it
    advances to its next distinct candidate. Empty/exhausted groups are skipped,
    and remaining groups may fill capacity. No evidence is invented to meet a
    quota or an uncalibrated absolute relevance threshold.

    Returned items are original objects with unchanged scores. The caller can
    record which query group supplied an item by object identity; a node ID alone
    may occur in several groups with different scores.
    """
    if max_count < 0:
        raise ValueError("Evidence count must be nonnegative.")
    if not 0 <= diversity_strength <= 1 or source_penalty < 0 or score_margin < 0:
        raise ValueError("Invalid diversity or relevance margin.")
    if max_count == 0:
        return []
    ordered_groups = {}
    for key, items in groups.items():
        ordered = sorted(items, key=lambda item: (
            item.score is None or not math.isfinite(item.score),
            -float(item.score) if item.score is not None and math.isfinite(item.score) else 0.0,
        ))
        ordered_groups[key] = choose_evidence(
            ordered, len(ordered), diversity_strength=diversity_strength,
            source_penalty=source_penalty, score_margin=score_margin,
            min_score=min_score,
            selection_scores=selection_scores.get(key) if selection_scores else None,
        )
    offsets = {key: 0 for key in ordered_groups}
    seen_ids, seen_facts, selected = set(), set(), []
    while len(selected) < max_count:
        before = len(selected)
        for key, group in ordered_groups.items():
            while offsets[key] < len(group) and len(selected) < max_count:
                candidate = group[offsets[key]]
                offsets[key] += 1
                node = candidate.node
                source = _fact_scope(candidate)
                fact = (source, " ".join(node.get_content().casefold().split()))
                if node.node_id in seen_ids or fact in seen_facts:
                    continue
                selected.append(candidate)
                seen_ids.add(node.node_id)
                seen_facts.add(fact)
                break
        if len(selected) == before:
            break
    return selected
