"""Synthetic bounded-lane tests; no corpus, network, or learned model inference."""

import copy

import pytest
from llama_index.core import VectorStoreIndex
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.llms import MockLLM
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode

from retrieval_engine.primary_candidates import build_primary_lane, merge_primary_candidates


def item(node_id, role="UNKNOWN", source="s", subject=None):
    return NodeWithScore(node=TextNode(
        id_=node_id, text=f"Capacity size specification {node_id}",
        metadata={"evidence_role": role, "source_id": source,
                  "subject_source_id": subject or source}, embedding=[1.0, 1.0, 1.0],
    ), score=8.0)


def test_fixed_budget_and_interleaving_preserve_unknown_global():
    global_nodes = [item(f"g{i}") for i in range(100)]
    primary = [item(f"p{i}", "PRIMARY") for i in range(30)]
    result, audit = merge_primary_candidates(global_nodes, primary, "Capacity?")
    assert len(result) == 64
    assert [x.node.node_id for x in result[:8]] == ["g0", "g1", "g2", "p0", "g3", "g4", "g5", "p1"]
    assert audit["primary_lane_slots"] == 16
    assert audit["global_slots"] == 48
    assert sum(x.node.metadata["evidence_role"] == "UNKNOWN" for x in result) == 48


def test_sparse_primary_falls_back_and_duplicates_are_not_extra_slots():
    global_nodes = [item(f"g{i}") for i in range(70)]
    result, audit = merge_primary_candidates(global_nodes, [item("p", "FAQ")] * 5, "Size?")
    assert len(result) == 64
    assert len({x.node.node_id for x in result}) == 64
    assert audit["primary_lane_slots"] == 1


def test_sparse_global_never_exceeds_primary_cap():
    result, audit = merge_primary_candidates([item("g")], [item(str(i), "POLICY") for i in range(70)], "Returns?")
    assert len(result) == 17
    assert audit["primary_lane_slots"] == 16


def test_shared_ids_use_original_global_objects_without_mutation():
    global_nodes = [item(f"g{i}", "PRIMARY") for i in range(70)]
    primary = [item("g8", "PRIMARY"), item("g1", "PRIMARY"), item("p", "PRIMARY")]
    original = copy.deepcopy([x.model_dump() for x in global_nodes + primary])
    result, audit = merge_primary_candidates(global_nodes, primary, "Size?")
    assert next(x for x in result if x.node.node_id == "g8") is global_nodes[8]
    assert len({x.node.node_id for x in result}) == len(result) == 64
    assert [x.model_dump() for x in global_nodes + primary] == original
    assert audit["primary_lane_slots"] == 2


@pytest.mark.parametrize("question", ["What do customers say?", "Show product reviews", "Any testimonials?"])
def test_review_requests_disable_primary_lane(question):
    global_nodes = [item(f"g{i}", "REVIEW") for i in range(70)]
    result, audit = merge_primary_candidates(global_nodes, [item("p", "PRIMARY")], question)
    assert result == global_nodes[:64]
    assert not audit["enabled"]
    assert audit["disabled_reason"] == "explicit_review_intent"


def test_invalid_primary_roles_cannot_enter_extra_lane():
    result, _ = merge_primary_candidates([item("g")], [item("r", "REVIEW"), item("u")], "Size?")
    assert [x.node.node_id for x in result] == ["g"]


@pytest.mark.parametrize("budget,cap", [(0, 16), (2, 16), (64, 0)])
def test_small_or_disabled_budgets(budget, cap):
    result, audit = merge_primary_candidates([item(str(i)) for i in range(70)], [item("p", "PRIMARY")], "Size?", budget, cap)
    assert len(result) == budget
    assert audit["primary_lane_slots"] <= min(budget, cap)


@pytest.mark.parametrize("budget,cap", [(-1, 3), (2, -1), (1.5, 1), (True, 1)])
def test_invalid_budgets_rejected(budget, cap):
    with pytest.raises(ValueError):
        merge_primary_candidates([], [], "Size?", budget, cap)


def synthetic_index(items):
    return VectorStoreIndex(nodes=[x.node for x in items], embed_model=MockEmbedding(embed_dim=3))


def test_official_filtered_retrievers_only_return_eligible_roles():
    nodes = [item("p", "PRIMARY"), item("f", "FAQ"), item("r", "REVIEW"), item("u")]
    lane = build_primary_lane(synthetic_index(nodes), [x.node for x in nodes], MockLLM())
    bundle = QueryBundle(query_str="capacity", embedding=[1.0, 1.0, 1.0])
    result, audit = lane.retrieve(bundle, "Capacity?")
    assert {x.node.node_id for x in result} == {"p", "f"}
    assert audit["embedding_reused"]
    assert audit["generative_provider_calls"] == 0
    assert audit["discarded_outside_filter"] == 0


def test_source_scope_rejects_cross_sell_mentions_and_other_sources():
    nodes = [item("own", "PRIMARY", "a"), item("cross", "PRIMARY", "a", "b"),
             item("other", "FAQ", "b")]
    lane = build_primary_lane(synthetic_index(nodes), [x.node for x in nodes], MockLLM(), source_id="a")
    result, audit = lane.retrieve(QueryBundle("capacity", embedding=[1.0] * 3), "Capacity?")
    assert [x.node.node_id for x in result] == ["own"]
    assert audit["source_id"] == "a"


def test_shared_query_bundle_embedding_survives_official_fusion():
    nodes = [item("p", "PRIMARY")]
    index = synthetic_index(nodes)
    bundle = QueryBundle("capacity")
    index.as_retriever(similarity_top_k=1).retrieve(bundle)
    embedding = bundle.embedding
    assert embedding is not None
    lane = build_primary_lane(index, [x.node for x in nodes], MockLLM())
    _, audit = lane.retrieve(bundle, "Capacity?")
    assert bundle.embedding is embedding
    assert audit["embedding_reused"]


def test_review_lane_skips_retriever_entirely():
    nodes = [item("p", "PRIMARY")]
    lane = build_primary_lane(synthetic_index(nodes), [x.node for x in nodes], MockLLM())
    class MustNotRetrieve:
        def retrieve(self, query):
            raise AssertionError("Disabled lane must not retrieve")
    object.__setattr__(lane, "retriever", MustNotRetrieve())
    results, audit = lane.retrieve(QueryBundle("customer reviews"), "Show customer reviews")
    assert results == [] and not audit["enabled"]


def test_empty_role_corpus_has_no_extra_lane():
    nodes = [item("r", "REVIEW"), item("u")]
    assert build_primary_lane(synthetic_index(nodes), [x.node for x in nodes], MockLLM()) is None
