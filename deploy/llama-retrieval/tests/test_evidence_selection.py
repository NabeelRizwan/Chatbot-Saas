"""Evidence-selection checks using a synthetic corpus, without model inference."""

import copy

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from retrieval_engine.evidence_selection import choose_evidence, deduplicate_evidence


def item(node_id, source, text, score, embedding=None):
    return NodeWithScore(node=TextNode(id_=node_id, text=text,
                                     metadata={"source_id": source}, embedding=embedding),
                         score=score)


def ids(items):
    return [entry.node.node_id for entry in items]


def test_selection_preference_does_not_mutate_raw_scores_or_bypass_margin():
    ranked = [item('a','one','A fact.',9), item('b','two','Another fact.',8.5),
              item('c','three','Unrelated fact.',-8)]
    selected = choose_evidence(ranked,1,diversity_strength=0,
        selection_scores={'a':.1,'b':.8,'c':1})
    assert ids(selected) == ['b']
    assert [r.score for r in ranked] == [9,8.5,-8]
    assert selected[0] is ranked[1]


def test_exact_duplicates_are_removed_within_source_but_preserve_attribution():
    ranked = [item("a", "manual-a", "Keep dry.\nStore upright.", 9),
              item("b", "manual-a", "Keep dry. Store upright.", 8),
              item("c", "manual-b", "Keep dry. Store upright.", 7)]
    assert ids(deduplicate_evidence(ranked)) == ["a", "c"]


def test_contained_passage_is_deduplicated_but_new_facts_are_kept():
    common = "This appliance must stand on a level surface and have sufficient ventilation on all sides."
    ranked = [item("a", "manual", common + " Disconnect it before cleaning.", 9),
              item("b", "manual", common, 8),
              item("c", "manual", common + " Do not disconnect it during updates.", 7)]
    assert ids(deduplicate_evidence(ranked)) == ["a", "c"]


def test_near_identical_numbers_and_negation_are_not_deleted():
    ranked = [item("a", "manual", "Use 1 cup daily.", 9),
              item("b", "manual", "Use 2 cups daily.", 8),
              item("c", "manual", "Do not use 1 cup daily.", 7)]
    assert len(deduplicate_evidence(ranked)) == 3


def test_verified_subject_copies_keep_one_original_citation():
    a=item('a','page-one','Lamp X uses an LED bulb.',8)
    b=item('b','page-two','Lamp X uses an LED bulb.',7)
    c=item('c','page-two','Lamp X does not include an LED bulb.',6)
    for row in [a,b,c]: row.node.metadata['subject_source_id']='linked:lamp-x'
    result=deduplicate_evidence([a,b,c])
    assert ids(result)==['a','c']
    assert result[0] is a and result[0].node.metadata['source_id']=='page-one'


def test_source_coverage_can_keep_multiple_passages_per_requested_document():
    ranked = [item("a1", "a", "Dimensions.", 10), item("a2", "a", "Directions.", 9.8),
              item("a3", "a", "Materials.", 9.7), item("b1", "b", "Dimensions.", 8.5),
              item("b2", "b", "Directions.", 8.4), item("b3", "b", "Unrelated boilerplate.", 0)]
    selected = choose_evidence(ranked, 4, ["a", "b"])
    assert ids(selected) == ["a1", "b1", "a2", "b2"]


def test_missing_coverage_source_is_not_invented_and_count_is_bounded():
    ranked = [item("a", "a", "Fact.", 5)]
    assert ids(choose_evidence(ranked, 12, ["missing"])) == ["a"]
    assert choose_evidence(ranked, 0) == []


def test_soft_diversity_promotes_distinct_relevant_evidence_without_source_cap():
    ranked = [item("a1", "a", "First fact.", 10, [1., 0.]),
              item("a2", "a", "Near duplicate fact.", 9.9, [1., 0.]),
              item("b1", "b", "Complementary fact.", 9.8, [0., 1.]),
              item("a3", "a", "Another relevant fact.", 9.7, [0.5, 0.5]),
              item("c1", "c", "Irrelevant page.", 0, [-1., 0.])]
    selected = choose_evidence(ranked, 4, diversity_strength=0.35)
    assert ids(selected)[:2] == ["a1", "b1"]
    assert ids(selected).count("a2") == 1
    assert "c1" not in ids(selected)


def test_mmr_compares_all_selected_nodes_and_does_not_mutate_inputs():
    ranked = [item("a", "one", "First topic.", 10, [1., 0.]),
              item("b", "two", "Second topic.", 9.9, [0., 1.]),
              item("c", "three", "Repeated first topic.", 9.8, [1., 0.]),
              item("d", "four", "New third topic.", 9.7, [-1., 0.]),
              item("e", "five", "Lowest relevance.", 0, [0., -1.])]
    before = copy.deepcopy([entry.model_dump() for entry in ranked])
    selected = choose_evidence(ranked, 3, diversity_strength=0.35)
    assert ids(selected) == ["a", "b", "d"]
    assert [entry.model_dump() for entry in ranked] == before
    assert selected[0] is ranked[0]


def test_zero_diversity_preserves_rank_and_single_source_can_fill_context():
    ranked = [item(str(i), "one", f"Distinct fact {i}.", 10 - i) for i in range(8)]
    assert ids(choose_evidence(ranked, 6, diversity_strength=0)) == ids(ranked[:6])


def test_relevance_floor_and_margin_prevent_forced_irrelevant_coverage():
    ranked = [item("a1", "a", "Relevant.", 10), item("b1", "b", "Relevant.", 9),
              item("b2", "b", "Unrelated.", -8)]
    selected = choose_evidence(ranked, 3, ["a", "b"], min_score=0)
    assert ids(selected) == ["a1", "b1"]


def test_invalid_embeddings_fall_back_to_lexical_similarity():
    ranked = [item("a", "one", "A clear factual passage.", 5, [0., 0.]),
              item("b", "two", "Another factual passage.", 4, [1., 0., 0.])]
    assert len(choose_evidence(ranked, 2)) == 2


def test_cross_sell_cards_count_as_their_subject_for_diversity():
    ranked = [item('a', 'page-a', 'First item.', 10, [1., 0.]),
              item('a-card', 'page-b', 'Another card about the first item.', 9.9, [1., 0.]),
              item('b', 'page-b', 'Second item.', 9.8, [1., 0.])]
    ranked[0].node.metadata['subject_source_id'] = 'item-a'
    ranked[1].node.metadata['subject_source_id'] = 'item-a'
    ranked[2].node.metadata['subject_source_id'] = 'item-b'
    selected = choose_evidence(ranked, 2, diversity_strength=.5, source_penalty=1)
    assert ids(selected) == ['a', 'b']
    assert selected[0].node.metadata['source_id'] == 'page-a'


@pytest.mark.parametrize("kwargs", [{"max_count": -1}, {"diversity_strength": 1.5},
                                   {"coverage_per_document": 0}, {"score_margin": -1}])
def test_invalid_configuration_fails(kwargs):
    parameters = {"max_count": 2, **kwargs}
    with pytest.raises(ValueError):
        choose_evidence([], **parameters)
