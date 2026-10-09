# SPDX-FileCopyrightText: 2022-present deepset GmbH <info@deepset.ai>
# SPDX-License-Identifier: Apache-2.0
"""Evidence-role preferences independent of the original relevance scores.

Weighted reciprocal rank fusion is adapted from Haystack MetaFieldRanker,
revision 87dba65f8c8b1f3906a36625615618ba29505971. Provenance and modifications:
third_party/haystack_metadata_rrf/NOTICE.txt.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from llama_index.core.schema import NodeWithScore


_PRIMARY_ROLES = frozenset({"PRIMARY", "FAQ", "POLICY"})
_KNOWN_ROLES = _PRIMARY_ROLES | {"REVIEW"}
_REVIEW_COUNT = re.compile(
    r"\b(?:how many|number of|count of|total(?: number)? of)\s+"
    r"(?:(?:customer|user|buyer|product)\s+)?reviews?\b"
    r"|\breview\s+(?:count|total|number)\b"
    r"|\b(?:more|fewer|most|fewest)\s+reviews?\b",
    re.IGNORECASE,
)
_EXCLUDED_REVIEWS = re.compile(
    r"\b(?:not|no|without|exclude|excluding|ignore)\b"
    r"(?:\s+[\w'-]+){0,3}\s+(?:reviews?|testimonials?)\b",
    re.IGNORECASE,
)
_REVIEW_REQUEST = re.compile(
    r"(?<![\w-])reviews\b"
    r"|\btestimonials?\b"
    r"|\b(?:customer|user|buyer|product)\s+"
    r"(?:review|feedback|opinions?|experiences?)\b"
    r"|\b(?:customers?|users?|buyers?|reviewers?|people)\b"
    r".{0,45}\b(?:say|said|think|thought|feel|felt|report|reported)\b"
    r"|\b(?:review|feedback|opinions?)\s+(?:of|about|from|on)\b",
    re.IGNORECASE,
)
_PROFESSIONAL_REVIEW = re.compile(
    r"\b(?:peer|clinician|doctor|expert|medical|scientific)"
    r"(?:[ -]+(?:review|reviews|reviewed))\b"
    r"|\breview(?:ed|s)?\s+by\s+(?:a\s+)?"
    r"(?:doctor|clinician|expert|physician)\b",
    re.IGNORECASE,
)


def wants_review_evidence(question: str) -> bool:
    """Recognize explicit customer-experience requests without a model call.

    Counting reviews, asking for professional review, and explicitly excluding
    reviews are factual tasks. Ambiguous instructions such as "review the
    directions" are not treated as requests for testimonials. This is a
    conservative routing cue, not a semantic classifier or evidence filter.
    """
    if _REVIEW_COUNT.search(question) or _EXCLUDED_REVIEWS.search(question):
        return False
    if _PROFESSIONAL_REVIEW.search(question):
        # An explicit customer request can still coexist with a clinical term.
        return bool(re.search(
            r"\b(?:customer|user|buyer)\s+(?:reviews?|feedback|opinions?)\b",
            question, re.IGNORECASE,
        ))
    return bool(_REVIEW_REQUEST.search(question))


def _unique_nodes(ranked: Sequence[NodeWithScore]) -> list[NodeWithScore]:
    # Scores are keyed by node ID. First occurrence defines rank and metadata;
    # repeated retrieval hits must not earn additional fusion votes.
    seen: set[str] = set()
    unique = []
    for item in ranked:
        if item.node.node_id not in seen:
            seen.add(item.node.node_id)
            unique.append(item)
    return unique


def _role(item: NodeWithScore) -> str:
    return str(item.node.metadata.get("evidence_role", "UNKNOWN")).strip().upper()


def _metadata_order(
    ranked: list[NodeWithScore], question: str
) -> list[NodeWithScore]:
    """Reorder only labeled slots; unknown roles receive no preference."""
    review_request = wants_review_evidence(question)
    known_positions = [
        index for index, item in enumerate(ranked) if _role(item) in _KNOWN_ROLES
    ]
    ordered = list(ranked)
    known = [ranked[index] for index in known_positions]

    def preference(item: NodeWithScore) -> int:
        is_review = _role(item) == "REVIEW"
        return int(is_review == review_request)

    # Python's stable sort preserves relevance order inside equal-role tiers.
    known.sort(key=preference, reverse=True)
    for index, item in zip(known_positions, known, strict=True):
        ordered[index] = item
    return ordered


def preference_scores(
    ranked: Sequence[NodeWithScore], question: str, weight: float = 0.2
) -> dict[str, float]:
    """Return separate selection scores from relevance and evidence-role ranks.

    Input order is the relevance ranking; raw NodeWithScore.score values are
    neither read nor changed. Scores follow Haystack's zero-based formula
    (1-weight)/(61+relevance_rank) + weight/(61+metadata_rank).
    PRIMARY, FAQ and POLICY share a tier. Explicit customer-review intent favors
    REVIEW instead. Unknown/missing roles keep their own metadata rank, giving
    exactly their baseline reciprocal-rank score.

    Duplicate IDs use only their first occurrence: they receive one score and
    one vote, even if later occurrences have different metadata. No source,
    text, ID, metadata or original relevance score is modified. These scores
    express a soft preference, not calibrated relevance; callers retain their
    original-score floor/margin before accepting a preferred candidate.
    """
    if not math.isfinite(weight) or not 0 <= weight <= 1:
        raise ValueError("Metadata preference weight must be finite in [0, 1].")
    unique = _unique_nodes(ranked)
    if weight == 0:
        return {
            item.node.node_id: 1 / (61 + index)
            for index, item in enumerate(unique)
        }
    metadata_order = _metadata_order(unique, question)
    scores = {item.node.node_id: 0.0 for item in unique}
    for index, (item, preferred) in enumerate(
        zip(unique, metadata_order, strict=True)
    ):
        reciprocal_rank = 1 / (61 + index)
        scores[item.node.node_id] += reciprocal_rank * (1 - weight)
        scores[preferred.node.node_id] += reciprocal_rank * weight
    return scores


def prioritize_candidates(
    ranked: Sequence[NodeWithScore], question: str, weight: float = 0.2
) -> list[NodeWithScore]:
    """Return every original object, ordered by separate selection scores.

    Ties are stable. Weight zero and an unchanged metadata ranking preserve the
    input order exactly, including repeated IDs. When preferences reorder the
    ranking, repeated IDs share their first occurrence's score; every occurrence
    is retained. The caller may deduplicate separately before setting a budget.
    """
    scores = preference_scores(ranked, question, weight)
    unique = _unique_nodes(ranked)
    metadata_ids = [item.node.node_id for item in _metadata_order(unique, question)]
    if weight == 0 or metadata_ids == [item.node.node_id for item in unique]:
        return list(ranked)
    return sorted(ranked, key=lambda item: scores[item.node.node_id], reverse=True)
