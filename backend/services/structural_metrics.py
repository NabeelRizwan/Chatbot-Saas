"""Offline structural comparisons. No extraction, scoring models or runtime hooks.

V1 compares normalized objects with the same source/path identity convention.
An adapter with different node keys must supply explicit gold alignment later;
this module deliberately does not guess identity from matching text.
"""
from collections import Counter
from dataclasses import dataclass
import json

from services.structural_document import (
    CoordinateSystem, LinkSafety, NodeType, Relation, SemanticRole,
    StructuralDocument, ValidationState,
)


@dataclass(frozen=True)
class Metric:
    expected: int
    actual: int
    matched: int

    @property
    def precision(self) -> float | None:
        return self.matched / self.actual if self.actual else None

    @property
    def recall(self) -> float | None:
        return self.matched / self.expected if self.expected else None


def _key(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _endpoint(ref):
    return [ref.revision.source.model_dump(mode="json"), ref.node_key]


def _features(doc: StructuralDocument):
    result = {name: [] for name in (
        "heading_body", "full_list", "review_edges", "collection_edges", "price_role",
        "quantity_unit", "timeline_stage", "canonical_link", "provenance", "source_quality")}
    nodes = {n.identity.node_key: n for n in doc.nodes}
    children = {}
    for n in doc.nodes:
        if n.parent:
            children.setdefault(n.parent.node_key, []).append(n)
    descriptions = {}
    for e in doc.edges:
        if e.relation == Relation.DESCRIBES and e.validation_state == ValidationState.VALIDATED:
            descriptions.setdefault(e.from_node.node_key, []).append([
                _endpoint(e.to_node), e.field, e.role.value if e.role else None,
                [s.model_dump(mode="json") for s in e.provenance.spans]])
    for n in doc.nodes:
        ident = _endpoint(n.identity)
        parent = _endpoint(n.parent) if n.parent else None
        subjects = descriptions.get(n.identity.node_key, [])
        attrs = n.attributes
        if attrs.list and attrs.list.source_block_complete:
            result["full_list"].append([ident, parent, attrs.list.model_dump(mode="json"),
                [[_endpoint(c.identity), c.text] for c in children.get(n.identity.node_key, ())
                 if c.node_type == NodeType.LIST_ITEM]])
        if attrs.commercial:
            result["price_role"].append([ident, parent, subjects, attrs.commercial.model_dump(mode="json")])
        for quantity in attrs.quantities:
            result["quantity_unit"].append([ident, parent, subjects, quantity.model_dump(mode="json")])
        if attrs.timeline:
            result["timeline_stage"].append([ident, parent, subjects, attrs.timeline.model_dump(mode="json"), n.text,
                [[_endpoint(c.identity), c.text, c.semantic_role.value] for c in children.get(n.identity.node_key, ())]])
        if attrs.link and attrs.link.safety == LinkSafety.SAFE:
            result["canonical_link"].append([ident, parent, attrs.link.model_dump(mode="json")])
        if n.text and n.node_type not in (NodeType.DOCUMENT, NodeType.SECTION, NodeType.GROUP, NodeType.LIST, NodeType.TABLE):
            result["provenance"].append([ident, n.text, [s.model_dump(mode="json") for s in n.provenance.spans]])
    for e in doc.edges:
        if e.validation_state != ValidationState.VALIDATED:
            continue
        origin = nodes[e.from_node.node_key]
        evidence = [s.model_dump(mode="json") for s in e.provenance.spans]
        pair = [_endpoint(e.from_node), _endpoint(e.to_node), e.field, evidence]
        if e.relation == Relation.HEADING_FOR:
            target = nodes.get(e.to_node.node_key)
            result["heading_body"].append([pair, origin.text, target.text if target else None])
        elif e.relation == Relation.REFERS_TO and origin.semantic_role == SemanticRole.REVIEW:
            result["review_edges"].append(pair)
        elif e.relation == Relation.CONTAINS:
            result["collection_edges"].append(pair)
    result["source_quality"].append(doc.revision.quality.model_dump(mode="json"))
    return {name: Counter(_key(v) for v in values) for name, values in result.items()}


def compare_structures(expected: StructuralDocument, actual: StructuralDocument) -> dict[str, Metric]:
    if expected.revision.identity.source != actual.revision.identity.source:
        raise ValueError("structural comparison requires exact same source ownership/version")
    gold, observed = _features(expected), _features(actual)
    return {name: Metric(sum(gold[name].values()), sum(observed[name].values()),
                         sum((gold[name] & observed[name]).values())) for name in gold}


def provenance_completeness(doc: StructuralDocument) -> Metric:
    """Located text nodes, not a claim that asserted coordinates are true.

    Exact slice correctness needs the original source artifact; unavailable
    provenance round-trips honestly but does not count as located coverage.
    """
    leaves = [n for n in doc.nodes if n.text and n.node_type not in
              (NodeType.DOCUMENT, NodeType.SECTION, NodeType.GROUP, NodeType.LIST, NodeType.TABLE)]
    located = sum(all(s.location.system != CoordinateSystem.UNAVAILABLE and
                      (s.location.byte_range is None or s.location.byte_range.end > s.location.byte_range.start)
                      for s in n.provenance.spans) for n in leaves)
    return Metric(len(leaves), len(leaves), located)


def serialization_coverage(doc: StructuralDocument) -> Metric:
    """Union of mapped node-local bytes; overlaps never inflate coverage.

    This validates mapping coverage only, NOT emitted text fidelity, output
    token limits or a chunker that does not exist yet. Empty text is N/A.
    """
    by_node = {}
    for mapping in doc.mappings:
        by_node.setdefault(mapping.node.node_key, []).append(mapping.node_slice)
    total = covered = 0
    for node in doc.nodes:
        total += len(node.text.encode("utf-8"))
        end = 0
        for span in sorted(by_node.get(node.identity.node_key, ()), key=lambda s: (s.start, s.end)):
            covered += max(0, span.end - max(end, span.start))
            end = max(end, span.end)
    return Metric(total, total, covered)
