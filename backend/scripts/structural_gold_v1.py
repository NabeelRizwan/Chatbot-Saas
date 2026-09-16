"""Hand-annotated offline GOLD loader, not a Markdown/parser implementation.

Only bundled excerpts are read. No application imports, saved corpus dependency,
metadata merge, network, database, generated chunks or extraction heuristics.
"""
from hashlib import sha256
import json
from pathlib import Path

from services.structural_document import (
    ByteRange, CoordinateSystem, Disposition, NodeAttributes, NodeIdentity,
    NodeType, Provenance, RevisionIdentity, RevisionState, SourceIdentity,
    SourceLocation, SourceQuality, SourceSpan, StructuralDocument, StructuralEdge,
    StructuralNode, StructureRevisionDescriptor, ValidationState, make_node_key,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "structural_gold_v1"
GOLD_VERSION = "STRUCTURAL_GOLD_V1"


def fixture_specs():
    fixtures = []
    for filename in ("real_sources.json", "synthetic_sources.json"):
        payload = json.loads((FIXTURE_DIR / filename).read_text(encoding="utf-8"))
        if payload["version"] != GOLD_VERSION:
            raise ValueError("unsupported structural gold version")
        fixtures.extend(payload["fixtures"])
    if len({f["name"] for f in fixtures}) != len(fixtures):
        raise ValueError("duplicate fixture name")
    return tuple(fixtures)


def _source(spec):
    return SourceIdentity(organization_id=70001, bot_id=70002,
        document_id=spec["document_id"], document_version_id=f"gold-source-{spec['document_id']}-v{spec['source_version']}",
        source_version=spec["source_version"],
        source_sha256=spec.get("source_sha256") or sha256(spec["source_text"].encode()).hexdigest())


def build_fixture(spec) -> StructuralDocument:
    """Assemble explicit expected annotations. This performs no source parsing."""
    text = spec["source_text"]
    if spec.get("source_text_sha256") and sha256(text.encode()).hexdigest() != spec["source_text_sha256"]:
        raise ValueError("saved source excerpt changed")
    source = _source(spec)
    revision = RevisionIdentity(source=source, structure_revision_id="gold-v1")
    refs = {"root": NodeIdentity(revision=revision, node_key=make_node_key(source, "/root", 0, ""))}
    for a in spec["annotations"]:
        if a["label"] in refs:
            raise ValueError("duplicate annotation label")
        refs[a["label"]] = NodeIdentity(revision=revision,
            node_key=make_node_key(source, "/" + a["label"], 0, a["text"]))

    def span(a=None):
        if a and a.get("unavailable_reason"):
            loc = SourceLocation(system=CoordinateSystem.UNAVAILABLE, unavailable_reason=a["unavailable_reason"])
        else:
            start, end = (a["start"], a["end"]) if a and a["text"] else (0, len(text))
            if a and a["text"] and text[start:end] != a["text"]:
                raise ValueError("annotation is not exact saved source slice")
            loc = SourceLocation(system=CoordinateSystem.UTF8_BYTES,
                byte_range=ByteRange(start=spec["source_start"] + len(text[:start].encode()),
                                     end=spec["source_start"] + len(text[:end].encode())))
        return SourceSpan(source=source, location=loc)

    def provenance(a=None):
        return Provenance(method="manual_annotation", method_version=GOLD_VERSION,
                          basis="explicit offline gold annotation", spans=(span(a),))

    quality = SourceQuality(classification=spec.get("quality", "usable"),
        disposition=spec.get("disposition", "accept"), detector_version="manual-gold-v1",
        reason_codes=("manual_fixture_annotation",), evidence=(span(),))
    descriptor = StructureRevisionDescriptor(identity=revision, parser_version="manual-gold-v1",
        normalizer_version=GOLD_VERSION, configuration_sha256=sha256(GOLD_VERSION.encode()).hexdigest(),
        source_format="markdown" if spec["category"] == "real_saved_source" else "text",
        fidelity="extracted_markdown" if spec["category"] == "real_saved_source" else "original",
        state=RevisionState.VALIDATED, quality=quality)
    nodes = [StructuralNode(identity=refs["root"], parser_path="/root", occurrence=0, parent=None,
                            preorder=0, node_type=NodeType.DOCUMENT, provenance=provenance())]
    for i, a in enumerate(spec["annotations"], 1):
        attrs = json.loads(json.dumps(a["attributes"]))
        if attrs.get("cell") and "header_labels" in attrs["cell"]:
            attrs["cell"]["header_keys"] = [refs[label].node_key for label in attrs["cell"].pop("header_labels")]
        q = None
        if a.get("quality"):
            q = SourceQuality(classification=a["quality"], disposition=Disposition.QUARANTINE,
                detector_version="manual-gold-v1", reason_codes=("blocked_excerpt",), evidence=(span(a),))
        nodes.append(StructuralNode(identity=refs[a["label"]], parser_path="/" + a["label"], occurrence=0,
            parent=refs[a["parent"]], preorder=i, node_type=a["node_type"], semantic_role=a["semantic_role"],
            text=a["text"], attributes=NodeAttributes.model_validate(attrs), provenance=provenance(a), quality=q))
    edges = []
    annotations = {a["label"]: a for a in spec["annotations"]}
    for e in spec["edges"]:
        if "to_source" in e:
            target_source = _source(e["to_source"])
            target = NodeIdentity(revision=RevisionIdentity(source=target_source, structure_revision_id="gold-v1"),
                                  node_key=make_node_key(target_source, "/root", 0, ""))
        else:
            target = refs[e["to"]]
        edges.append(StructuralEdge(from_node=refs[e["from"]], to_node=target, relation=e["relation"],
            provenance=provenance(annotations[e["evidence"]]), validation_state=ValidationState.VALIDATED))
    return StructuralDocument(revision=descriptor, nodes=tuple(nodes), edges=tuple(edges))


def load_gold() -> dict[str, StructuralDocument]:
    return {spec["name"]: build_fixture(spec) for spec in fixture_specs()}
