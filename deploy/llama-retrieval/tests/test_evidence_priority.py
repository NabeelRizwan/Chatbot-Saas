"""Synthetic evidence-role ranking checks; no corpus or model inference."""

import copy

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from retrieval_engine.evidence_priority import (
    preference_scores,
    prioritize_candidates,
    wants_review_evidence,
    selection_preference_scores,
)


def item(node_id, role=None, score=5.0):
    metadata = {"source_id": f"source-{node_id}", "subject_source_id": "subject"}
    if role is not None:
        metadata["evidence_role"] = role
    return NodeWithScore(
        node=TextNode(id_=node_id, text=f"Original passage {node_id}", metadata=metadata),
        score=score,
    )


def ids(ranked):
    return [entry.node.node_id for entry in ranked]


def test_weighted_rrf_uses_upstream_zero_based_constant():
    ranked = [item("review", "REVIEW"), item("primary", "PRIMARY")]
    scores = preference_scores(ranked, "What is the capacity?", weight=0.2)
    assert scores["review"] == pytest.approx(0.8 / 61 + 0.2 / 62)
    assert scores["primary"] == pytest.approx(0.8 / 62 + 0.2 / 61)


def test_no_labels_preserves_order_even_with_unusual_original_scores():
    ranked = [item("a", score=-9), item("b", "UNKNOWN", score=12),
              item("c", "unrecognized", score=None)]
    assert ids(prioritize_candidates(ranked, "Specifications?", weight=1)) == ids(ranked)


def test_unknown_receives_exactly_its_original_rank_score():
    ranked = [item("r", "REVIEW"), item("u", "UNKNOWN"), item("p", "PRIMARY")]
    scores = preference_scores(ranked, "What is its size?", weight=0.3)
    assert scores["u"] == pytest.approx(1 / 62)
    assert scores["p"] > 1 / 63
    assert scores["r"] < 1 / 61


def test_zero_weight_preserves_exact_object_order_including_duplicates():
    a, b = item("a", "REVIEW"), item("b", "PRIMARY")
    ranked = [a, b, a]
    result = prioritize_candidates(ranked, "What is the size?", weight=0)
    assert all(x is y for x, y in zip(result, ranked, strict=True))


def test_tied_fusion_scores_keep_relevance_order():
    ranked = [item("review", "REVIEW"), item("primary", "PRIMARY")]
    assert ids(prioritize_candidates(ranked, "Capacity?", weight=0.5)) == ids(ranked)


def test_factual_role_ties_keep_primary_faq_and_policy_order():
    ranked = [item("r", "REVIEW"), item("f", "FAQ"),
              item("p", "POLICY"), item("s", "PRIMARY")]
    assert ids(prioritize_candidates(ranked, "Capacity?", weight=1)) == ["f", "p", "s", "r"]


def test_highly_ranked_review_not_universally_overridden_by_low_primary():
    ranked = [item(f"r{i}", "REVIEW", 10 - i / 100) for i in range(30)]
    ranked.append(item("unrelated-primary", "PRIMARY", score=-10))
    result = prioritize_candidates(ranked, "How does it feel in use?")
    assert result[0] is ranked[0]
    assert result.index(ranked[-1]) > 0
    assert len(result) == len(ranked)


@pytest.mark.parametrize("question", [
    "What do customers say about its flavor?",
    "Show customer testimonials.",
    "Are there any product reviews?",
    "What is the user feedback on comfort?",
    "What did buyers think?",
])
def test_review_requests_favor_review_evidence(question):
    ranked = [item("spec", "PRIMARY"), item("review", "REVIEW")]
    assert wants_review_evidence(question)
    assert ids(prioritize_candidates(ranked, question, weight=1)) == ["review", "spec"]
    assert preference_scores(ranked, question)["review"] >= 1 / 62


@pytest.mark.parametrize("question", [
    "How many customer reviews are there?",
    "What is the review count?",
    "Which model has more reviews?",
    "Is this peer-reviewed?",
    "Was it reviewed by a doctor?",
    "Review the warranty conditions.",
    "Ignore customer reviews and use specifications.",
    "Without testimonials, what are the dimensions?",
    "Do not use customer reviews.",
    "What is your customer reviews policy?",
    "Explain the policy on user reviews for this software marketplace.",
    "Where are the testimonial moderation guidelines?",
    "What are this store's review rules?",
])
def test_factual_or_excluded_review_questions_do_not_reverse_preference(question):
    assert not wants_review_evidence(question)


def test_duplicate_ids_get_one_vote_but_all_original_objects_are_retained():
    a, b, repeated = item("a", "REVIEW"), item("b", "PRIMARY"), item("a", "PRIMARY")
    ranked = [a, b, repeated]
    scores = preference_scores(ranked, "Capacity?", weight=1)
    assert scores == {"a": pytest.approx(1 / 62), "b": pytest.approx(1 / 61)}
    result = prioritize_candidates(ranked, "Capacity?", weight=1)
    assert result[0] is b and result[1] is a and result[2] is repeated
    assert len(result) == len(ranked)


def test_inputs_and_source_identifiers_are_not_modified():
    ranked = [item("r", "REVIEW", -3), item("p", "PRIMARY", -8)]
    before = copy.deepcopy([entry.model_dump() for entry in ranked])
    result = prioritize_candidates(ranked, "Capacity?", weight=1)
    assert [entry.model_dump() for entry in ranked] == before
    assert result[0] is ranked[1]
    assert result[0].node.metadata["source_id"] == "source-p"
    assert result[0].score == -8


def test_empty_rankings():
    assert preference_scores([], "Question") == {}
    assert prioritize_candidates([], "Question") == []


@pytest.mark.parametrize("weight", [-0.1, 1.1, float("nan"), float("inf")])
def test_invalid_weights_are_rejected(weight):
    with pytest.raises(ValueError):
        preference_scores([], "Question", weight)
    with pytest.raises(ValueError):
        prioritize_candidates([], "Question", weight)
    with pytest.raises(ValueError):
        selection_preference_scores([], "Question", weight)


@pytest.mark.parametrize('question', [
    'Compare the official warranty with what customers say about support.',
    'Give both manufacturer specifications and customer reviews for the chair.',
    'Do customer reviews disagree with the published directions for use?',
    'Explain the review policy and what customers say about the service.',
])
def test_mixed_sources_keep_original_relevance_utility(question):
    ranked = [item('p', 'PRIMARY', 5), item('r', 'REVIEW', 4.95), item('f', 'FAQ', -2)]
    assert wants_review_evidence(question)
    assert prioritize_candidates(ranked, question, weight=.2) == ranked
    assert selection_preference_scores(ranked, question, weight=.2) is None


@pytest.mark.parametrize('roles,question', [
    ([None, 'UNKNOWN', None], 'How wide is it?'),
    (['PRIMARY', 'FAQ', 'POLICY'], 'What are the conflicting directions?'),
    (['REVIEW', 'REVIEW', 'REVIEW'], 'What did buyers think?'),
])
def test_inactive_role_preference_keeps_mmr_selection_and_context(roles, question):
    from retrieval_engine.evidence_selection import choose_evidence
    from retrieval_engine.evidence_context import build_evidence_context
    ranked = [item(str(i), role, score=score) for i, (role, score) in enumerate(zip(roles, [10, 9.95, -8]))]
    documents = {}
    for entry in ranked:
        node = entry.node
        source_id = node.metadata['source_id']
        node.metadata.update(subject_source_id=source_id, title=source_id, url='https://example.test/' + source_id)
        node.start_char_idx, node.end_char_idx = 0, len(node.text)
        documents[source_id] = {'text': node.text, 'title': source_id, 'url': node.metadata['url']}
    baseline = choose_evidence(ranked, 2)
    candidate = choose_evidence(ranked, 2, selection_scores=selection_preference_scores(ranked, question, .2))
    assert [id(entry) for entry in candidate] == [id(entry) for entry in baseline]
    mapping = {entry.node.node_id: entry.node for entry in ranked}
    assert build_evidence_context(candidate, mapping, documents, str.split, 1000, 2) == \
        build_evidence_context(baseline, mapping, documents, str.split, 1000, 2)


def test_conflicting_primary_faq_facts_remain_in_same_preference_tier():
    ranked = [item('review', 'REVIEW', 8), item('directions', 'PRIMARY', 7.9), item('faq', 'FAQ', 7.8)]
    for weight in (.1, .2):
        scores = selection_preference_scores(ranked, 'What are the conflicting usage directions?', weight)
        assert scores is not None
        assert scores['directions'] > scores['faq']
        assert len(prioritize_candidates(ranked, 'Usage directions?', weight)) == 3
        assert ranked[0].score == 8

