"""Bounded factual-evidence candidate lane using official LlamaIndex retrievers.

This adds candidates, not trusted answers or relevance-score bonuses. The global
lane remains available for unclassified passages and customer experiences.
LlamaIndex's public MetadataFilters, BM25Retriever and QueryFusionRetriever APIs
are used directly; no upstream implementation is copied.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from retrieval_engine.evidence_priority import wants_review_evidence

if TYPE_CHECKING:
    from llama_index.core import VectorStoreIndex
    from llama_index.core.schema import BaseNode, NodeWithScore, QueryBundle


PRIMARY_ROLES = ("PRIMARY", "FAQ", "POLICY")


@dataclass(frozen=True)
class PrimaryCandidateLane:
    """Synchronous hybrid lane; share a QueryBundle after global retrieval."""

    retriever: Any
    eligible_count: int
    eligible_ids: frozenset[str]
    source_id: str | None = None

    def retrieve(
        self, query_bundle: QueryBundle, question: str
    ) -> tuple[list[NodeWithScore], dict[str, Any]]:
        audit: dict[str, Any] = {
            "enabled": not wants_review_evidence(question),
            "eligible_count": self.eligible_count,
            "source_id": self.source_id,
            "roles": list(PRIMARY_ROLES),
            "embedding_available_before": query_bundle.embedding is not None,
            "embedding_reused": False,
            "generative_provider_calls": 0,
        }
        if not audit["enabled"]:
            audit.update(disabled_reason="explicit_review_intent", returned=0)
            return [], audit
        had_embedding = query_bundle.embedding is not None
        results = self.retriever.retrieve(query_bundle)
        # The official filtered retrievers enforce this already. Keeping the
        # ID check guards zero-score BM25 fallbacks and future adapter changes.
        unique: dict[str, NodeWithScore] = {}
        for item in results:
            if item.node.node_id in self.eligible_ids:
                unique.setdefault(item.node.node_id, item)
        audit.update(
            returned=len(unique),
            embedding_reused=had_embedding,
            embedding_available_after=query_bundle.embedding is not None,
            discarded_outside_filter=sum(
                item.node.node_id not in self.eligible_ids for item in results
            ),
        )
        return list(unique.values()), audit


def build_primary_lane(
    index: VectorStoreIndex,
    model_nodes: Mapping[str, BaseNode] | Sequence[BaseNode],
    disabled_llm: Any,
    top_k: int = 32,
    source_id: str | None = None,
) -> PrimaryCandidateLane | None:
    """Build official filtered vector + BM25 retrieval without model inference.

    Optional comparison scoping requires both source_id and subject_source_id
    to match: a product mentioned inside another page is not its primary page.
    Roles are exact metadata values, matching the indexed filter semantics.
    An empty lane returns None so callers can keep their global fallback.
    """
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1:
        raise ValueError("Primary lane top_k must be a positive integer.")
    from llama_index.core.retrievers import QueryFusionRetriever
    from llama_index.core.retrievers.fusion_retriever import FUSION_MODES
    from llama_index.core.vector_stores import MetadataFilter, MetadataFilters
    from llama_index.core.vector_stores.types import FilterCondition, FilterOperator
    from llama_index.retrievers.bm25 import BM25Retriever

    nodes = list(model_nodes.values() if isinstance(model_nodes, Mapping) else model_nodes)
    nodes = [node for node in nodes if node.metadata.get("evidence_role") in PRIMARY_ROLES]
    if source_id is not None:
        nodes = [node for node in nodes if
                 node.metadata.get("source_id") == source_id and
                 node.metadata.get("subject_source_id") == source_id]
    nodes = list({node.node_id: node for node in nodes}.values())
    if not nodes:
        return None
    filter_items = [MetadataFilter(
        key="evidence_role", value=list(PRIMARY_ROLES), operator=FilterOperator.IN,
    )]
    if source_id is not None:
        filter_items.extend([
            MetadataFilter(key="source_id", value=source_id),
            MetadataFilter(key="subject_source_id", value=source_id),
        ])
    # The BM25 adapter supports flat filters, so use IN rather than a nested
    # OR inside AND. Both official retrievers receive the identical filter.
    filters = MetadataFilters(filters=filter_items, condition=FilterCondition.AND)
    limit = min(top_k, len(nodes))
    vector = index.as_retriever(similarity_top_k=limit, filters=filters)
    # A physically restricted lexical corpus also prevents masked zero-score
    # results from occupying primary slots when few query words match.
    bm25 = BM25Retriever.from_defaults(
        nodes=nodes, filters=filters, similarity_top_k=limit,
        language="en", verbose=False,
    )
    fusion = QueryFusionRetriever(
        [vector, bm25], llm=disabled_llm, num_queries=1,
        mode=FUSION_MODES.RECIPROCAL_RANK,
        similarity_top_k=min(top_k * 2, len(nodes)),
        use_async=False, verbose=False,
    )
    return PrimaryCandidateLane(
        retriever=fusion, eligible_count=len(nodes),
        eligible_ids=frozenset(node.node_id for node in nodes), source_id=source_id,
    )


def merge_primary_candidates(
    global_ranked: Sequence[NodeWithScore],
    primary_ranked: Sequence[NodeWithScore],
    question: str,
    max_candidates: int = 64,
    primary_cap: int = 16,
) -> tuple[list[NodeWithScore], dict[str, Any]]:
    """Interleave three global hits and one primary hit within a fixed budget.

    The cap counts slots supplied by the extra lane, not primary-role passages
    that already rank globally. IDs receive one slot; the first global object
    is canonical when both lanes contain it. All input objects, source IDs and
    scores remain untouched. Review requests and a zero cap use only global.
    This is candidate coverage, not a rule forcing final evidence to be factual.
    """
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0
           for value in (max_candidates, primary_cap)):
        raise ValueError("Candidate budget and primary cap must be nonnegative integers.")
    canonical = {}
    global_nodes = []
    for item in global_ranked:
        if item.node.node_id not in canonical:
            canonical[item.node.node_id] = item
            global_nodes.append(item)
    review_intent = wants_review_evidence(question)
    lane_enabled = not review_intent and primary_cap > 0
    primary_nodes = []
    primary_seen = set()
    for item in primary_ranked:
        node_id = item.node.node_id
        if node_id not in primary_seen and item.node.metadata.get("evidence_role") in PRIMARY_ROLES:
            primary_seen.add(node_id)
            primary_nodes.append(canonical.get(node_id, item))
    if not lane_enabled:
        primary_nodes = []
    selected, supplied_by = [], []
    seen = set()
    gi = pi = lane_slots = 0
    cap = min(primary_cap, max_candidates)

    def add(item: NodeWithScore, lane: str) -> bool:
        if item.node.node_id in seen or len(selected) >= max_candidates:
            return False
        seen.add(item.node.node_id)
        selected.append(item)
        supplied_by.append(lane)
        return True

    while len(selected) < max_candidates:
        previous_count = len(selected)
        global_added = 0
        while gi < len(global_nodes) and global_added < 3:
            item = global_nodes[gi]
            gi += 1
            global_added += int(add(item, "global"))
        if lane_slots < cap:
            while pi < len(primary_nodes):
                item = primary_nodes[pi]
                pi += 1
                if add(item, "primary"):
                    lane_slots += 1
                    break
        if len(selected) == previous_count:
            break
    audit = {
        "enabled": lane_enabled,
        "disabled_reason": "explicit_review_intent" if review_intent else (
            "zero_primary_cap" if primary_cap == 0 else None),
        "max_candidates": max_candidates,
        "primary_cap": cap,
        "primary_lane_slots": lane_slots,
        "global_slots": supplied_by.count("global"),
        "global_unique": len(global_nodes),
        "primary_unique": len(primary_nodes),
        "selected_count": len(selected),
        "selected": [{"node_id": item.node.node_id, "lane": lane}
                     for item, lane in zip(selected, supplied_by, strict=True)],
    }
    return selected, audit
