from collections import Counter
from llama_index.core.schema import NodeWithScore,TextNode
from retrieval_engine.evidence_selection import choose_grouped_evidence

def items(source, scores):
    return [NodeWithScore(node=TextNode(id_=f"{source}{index}", text=f"Distinct fact {source} {index}",
                                     metadata={"source_id":source}), score=score)
            for index, score in enumerate(scores)]

def ids(values):
    return [value.node.node_id for value in values]

def test_faceted_groups_cover_each_cell_before_taking_another_turn():
    groups = {
        "a/ingredients":items("a-ingredients", [100,99,98,97]),
        "b/ingredients":items("b-ingredients", [1,0,-1,-2]),
        "a/directions":items("a-directions", [-10,-20,-30,-40]),
        "b/directions":items("b-directions", [999,888,777,666]),
    }
    output = choose_grouped_evidence(groups, 12)
    assert Counter(item.node.metadata["source_id"] for item in output) == {
        "a-ingredients":3,"b-ingredients":3,"a-directions":3,"b-directions":3,
    }
    assert ids(output[:4]) == [group[0].node.node_id for group in groups.values()]

def test_faceted_group_duplicate_ids_advance_to_next_unique_candidate():
    a = items("a", [10,8,6,4])
    b = items("b", [1,0])
    same_node_other_query = NodeWithScore(node=a[0].node, score=-100)
    groups = {"a/first":[a[0],a[1]], "a/second":[same_node_other_query,a[2]], "b/first":b}
    output = choose_grouped_evidence(groups, 4)
    assert ids(output) == ["a0","a2","b0","a1"]
    assert output[0] is a[0]
    assert same_node_other_query.score == -100

def test_faceted_groups_same_source_fact_dedup_but_different_source_fact_retained():
    one = NodeWithScore(node=TextNode(id_="a1",text="Return within 30 days.",metadata={"source_id":"a"}),score=10)
    same = NodeWithScore(node=TextNode(id_="a2",text="Return within 30 days.",metadata={"source_id":"a"}),score=999)
    other = NodeWithScore(node=TextNode(id_="b1",text="Return within 30 days.",metadata={"source_id":"b"}),score=-10)
    assert ids(choose_grouped_evidence({"one":[one],"same":[same],"other":[other]},12)) == ["a1","b1"]

def test_faceted_group_score_shift_cannot_move_slots_between_cells():
    groups = {"x":items("x",[1,0,-1]), "y":items("y",[100,50,-100])}
    original = ids(choose_grouped_evidence(groups,5))
    shifted = {"x":groups["x"],"y":[NodeWithScore(node=item.node,score=item.score-1000) for item in groups["y"]]}
    assert ids(choose_grouped_evidence(shifted,5)) == original

def test_faceted_empty_exhausted_groups_and_small_budget():
    groups = {"empty":[],"x":items("x",[10]),"y":items("y",[1,0,-1])}
    assert ids(choose_grouped_evidence(groups,1)) == ["x0"]
    assert ids(choose_grouped_evidence(groups,10)) == ["x0","y0","y1","y2"]
    assert choose_grouped_evidence({},10) == []

def test_faceted_group_preserves_fact_difference_in_number_or_negation():
    facts = ["Take one capsule.","Take two capsules.","Do not take two capsules."]
    groups = {str(index):[NodeWithScore(node=TextNode(id_=str(index),text=fact,metadata={"source_id":"a"}),score=1)]
              for index,fact in enumerate(facts)}
    assert len(choose_grouped_evidence(groups,12)) == 3
