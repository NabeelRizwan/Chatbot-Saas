"""Structural interchange v1. Pure values, not an extractor or authorization grant.

Ownership is supplied by a trusted caller, never merged from parser metadata.
Locations refer to an immutable source artifact, not enriched chunk offsets.
Only validated constructors/JSON deserialization are supported ingress paths.
"""
from __future__ import annotations

from decimal import Decimal
from enum import Enum
import hashlib
import json
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator

SCHEMA_VERSION = "structural-v1"
NonNegative = Annotated[StrictInt, Field(ge=0)]
Positive = Annotated[StrictInt, Field(gt=0)]
Name = Annotated[StrictStr, Field(min_length=1, max_length=256)]
Digest = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
Confidence = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class Value(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False)

    def canonical_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


class NodeType(str, Enum):
    DOCUMENT = "document"
    SECTION = "section"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    LIST_ITEM = "list_item"
    TABLE = "table"
    TABLE_ROW = "table_row"
    TABLE_CELL = "table_cell"
    GROUP = "group"
    LINK = "link"
    MEDIA = "media"


class SemanticRole(str, Enum):
    TITLE = "title"
    FAQ_QUESTION = "faq_question"
    FAQ_ANSWER = "faq_answer"
    REVIEW = "review"
    PRODUCT_CARD = "product_card"
    PRICE_BLOCK = "price_block"
    DIRECTIONS = "directions"
    INGREDIENTS = "ingredients"
    TIMELINE_STAGE = "timeline_stage"
    WARNING = "warning"
    NAVIGATION = "navigation"
    FURNITURE = "furniture"
    UNKNOWN = "unknown"


class Relation(str, Enum):
    CONTAINS = "CONTAINS"
    REFERS_TO = "REFERS_TO"
    VARIANT_OF = "VARIANT_OF"
    DESCRIBES = "DESCRIBES"
    HEADING_FOR = "HEADING_FOR"
    QA_PAIR = "QA_PAIR"


class SourceIdentity(Value):
    organization_id: Positive
    bot_id: Positive
    document_id: Positive
    document_version_id: Name
    source_version: Positive
    source_sha256: Digest


class RevisionIdentity(Value):
    source: SourceIdentity
    structure_revision_id: Name


class NodeIdentity(Value):
    revision: RevisionIdentity
    node_key: Digest


class ByteRange(Value):
    """Half-open UTF-8 byte range. Zero-width boundaries are representable."""
    start: NonNegative
    end: NonNegative

    @model_validator(mode="after")
    def ordered(self):
        if self.start > self.end:
            raise ValueError("range start must not exceed end")
        return self


class CoordinateSystem(str, Enum):
    UTF8_BYTES = "utf8_bytes"
    PARSER_ITEM = "parser_item"
    PAGE_BBOX = "page_bbox"
    UNAVAILABLE = "unavailable"


class PageBox(Value):
    page: Positive
    x0: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    y0: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    x1: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    y1: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    unit: Literal["points", "pixels", "normalized"]
    origin: Literal["top_left", "bottom_left"]

    @model_validator(mode="after")
    def ordered(self):
        if self.x0 > self.x1 or self.y0 > self.y1:
            raise ValueError("invalid bounding box")
        if self.unit == "normalized" and max(self.x1, self.y1) > 1:
            raise ValueError("normalized box must fit unit square")
        return self


class SourceLocation(Value):
    system: CoordinateSystem
    byte_range: ByteRange | None = None
    parser_item: Name | None = None
    page_bbox: PageBox | None = None
    unavailable_reason: Name | None = None

    @model_validator(mode="after")
    def exclusive(self):
        expected = {CoordinateSystem.UTF8_BYTES: "byte_range",
                    CoordinateSystem.PARSER_ITEM: "parser_item",
                    CoordinateSystem.PAGE_BBOX: "page_bbox",
                    CoordinateSystem.UNAVAILABLE: "unavailable_reason"}[self.system]
        for field in ("byte_range", "parser_item", "page_bbox", "unavailable_reason"):
            if (getattr(self, field) is not None) != (field == expected):
                raise ValueError("coordinate system requires exactly its own location field")
        return self


class SourceSpan(Value):
    source: SourceIdentity
    location: SourceLocation


class QualityClass(str, Enum):
    USABLE = "usable"
    MIXED = "mixed"
    BLOCKED = "blocked"
    INTERSTITIAL = "interstitial"
    NAVIGATION_ONLY = "navigation_only"
    ERROR = "error"
    UNKNOWN = "unknown"


class Disposition(str, Enum):
    ACCEPT = "accept"
    QUARANTINE = "quarantine"
    MANUAL_REVIEW = "manual_review"


class SourceQuality(Value):
    classification: QualityClass
    disposition: Disposition
    detector_version: Name
    reason_codes: tuple[Name, ...] = Field(min_length=1)
    evidence: tuple[SourceSpan, ...] = Field(min_length=1)
    confidence: Confidence | None = None

    @model_validator(mode="after")
    def coherent(self):
        if self.disposition == Disposition.ACCEPT and self.classification not in (
                QualityClass.USABLE, QualityClass.MIXED):
            raise ValueError("non-usable/unknown quality cannot assert acceptance")
        object.__setattr__(self, "reason_codes", tuple(sorted(set(self.reason_codes))))
        return self


class RevisionState(str, Enum):
    STAGING = "staging"
    VALIDATED = "validated"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StructureRevisionDescriptor(Value):
    schema_version: Literal["structural-v1"] = SCHEMA_VERSION
    identity: RevisionIdentity
    parser_version: Name
    normalizer_version: Name
    chunker_version: Name | None = None
    configuration_sha256: Digest
    source_format: Literal["markdown", "html", "text", "pdf", "docx"]
    fidelity: Literal["original", "extracted_markdown", "extracted_text", "layout", "unknown"]
    state: RevisionState
    quality: SourceQuality

    @model_validator(mode="after")
    def local_quality(self):
        if any(s.source != self.identity.source for s in self.quality.evidence):
            raise ValueError("quality evidence must belong to revision source")
        return self

    def build_fingerprint(self) -> str:
        # Lifecycle/quality can change without changing the processing recipe.
        recipe = [self.schema_version, self.identity.source.canonical_json(), self.parser_version,
                  self.normalizer_version, self.chunker_version, self.configuration_sha256,
                  self.source_format, self.fidelity]
        return hashlib.sha256(json.dumps(recipe, ensure_ascii=False).encode()).hexdigest()


class ListAttributes(Value):
    ordered: StrictBool
    item_count: NonNegative
    source_block_complete: StrictBool


class TableAttributes(Value):
    row_count: NonNegative
    column_count: NonNegative


class CellAttributes(Value):
    row: NonNegative
    column: NonNegative
    row_span: Positive = 1
    column_span: Positive = 1
    is_header: StrictBool = False
    header_keys: tuple[Digest, ...] = ()
    unit: StrictStr | None = None


class CommercialRole(str, Enum):
    UNKNOWN = "unknown"
    ONE_TIME = "one_time"
    SUBSCRIPTION = "subscription"
    PER_UNIT = "per_unit"
    BUNDLE = "bundle"
    REGULAR = "regular"
    OFFER = "offer"
    FEE = "fee"


def _decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    # Source text is retained separately; the typed value is a decimal string.
    import re
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", value):
        raise ValueError("numeric value must be a finite decimal string")
    return Decimal(value)


class CommercialAttributes(Value):
    source_text: Annotated[StrictStr, Field(min_length=1)]
    amount: StrictStr | None = None
    currency: Annotated[StrictStr, Field(min_length=1, max_length=16)] | None = None
    role: CommercialRole = CommercialRole.UNKNOWN
    conditions: tuple[StrictStr, ...] = ()

    @model_validator(mode="after")
    def amount_string(self):
        _decimal(self.amount)
        return self


class QuantityAttributes(Value):
    source_text: Annotated[StrictStr, Field(min_length=1)]
    value: StrictStr | None = None
    range_min: StrictStr | None = None
    range_max: StrictStr | None = None
    unit: Annotated[StrictStr, Field(min_length=1)] | None = None
    frequency: Annotated[StrictStr, Field(min_length=1)] | None = None
    qualifier: StrictStr | None = None

    @model_validator(mode="after")
    def coherent(self):
        for v in (self.value, self.range_min, self.range_max):
            _decimal(v)
        if (self.range_min is None) != (self.range_max is None):
            raise ValueError("range requires both endpoints")
        if self.value is not None and self.range_min is not None:
            raise ValueError("quantity cannot assert both scalar and range")
        if self.range_min is not None and Decimal(self.range_min) > Decimal(self.range_max):
            raise ValueError("quantity range reversed")
        return self


class TimelineAttributes(Value):
    stage_order: NonNegative
    stage_label: Annotated[StrictStr, Field(min_length=1)]
    qualifiers: tuple[StrictStr, ...] = ()


class LinkSafety(str, Enum):
    UNCHECKED = "unchecked"
    SAFE = "safe"
    UNSAFE = "unsafe"


class LinkAttributes(Value):
    original_href: Annotated[StrictStr, Field(min_length=1)]
    anchor_text: StrictStr
    fragment: StrictStr | None = None
    safety: LinkSafety
    validated_href: StrictStr | None = None
    resolution: Literal["unresolved", "ambiguous", "resolved"] = "unresolved"

    @model_validator(mode="after")
    def safe_representation(self):
        # Syntax consistency only, NOT URL resolution, SSRF clearance or permission.
        if self.safety == LinkSafety.SAFE:
            if not self.validated_href:
                raise ValueError("safe link requires complete validated representation")
            for href in (self.original_href, self.validated_href):
                if any(ord(c) < 32 or ord(c) == 127 for c in href):
                    raise ValueError("control character in safe link")
                parsed = urlsplit(href)
                if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
                    raise ValueError("safe link must be credential-free HTTP(S)")
        elif self.validated_href is not None:
            raise ValueError("unvalidated/unsafe link cannot advertise safe representation")
        return self


class NodeAttributes(Value):
    list: ListAttributes | None = None
    table: TableAttributes | None = None
    cell: CellAttributes | None = None
    commercial: CommercialAttributes | None = None
    quantities: tuple[QuantityAttributes, ...] = ()
    timeline: TimelineAttributes | None = None
    link: LinkAttributes | None = None


class Provenance(Value):
    method: Literal["manual_annotation", "deterministic", "parser"]
    method_version: Name
    basis: Annotated[StrictStr, Field(min_length=1)]
    spans: tuple[SourceSpan, ...] = Field(min_length=1)
    confidence: Confidence | None = None


def make_node_key(source: SourceIdentity, parser_path: str, occurrence: int, text: str) -> str:
    if not parser_path or type(occurrence) is not int or occurrence < 0:
        raise ValueError("node identity requires path and nonnegative occurrence")
    payload = [source.model_dump(mode="json"), parser_path, occurrence,
               hashlib.sha256(text.encode("utf-8")).hexdigest()]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


class StructuralNode(Value):
    identity: NodeIdentity
    parser_path: Name
    occurrence: NonNegative
    parent: NodeIdentity | None
    preorder: NonNegative
    leaf_order: NonNegative | None = None
    node_type: NodeType
    semantic_role: SemanticRole = SemanticRole.UNKNOWN
    text: StrictStr = ""
    attributes: NodeAttributes = Field(default_factory=NodeAttributes)
    provenance: Provenance
    quality: SourceQuality | None = None

    @model_validator(mode="after")
    def coherent(self):
        if self.identity.node_key != make_node_key(self.identity.revision.source, self.parser_path, self.occurrence, self.text):
            raise ValueError("node key does not match source/path/occurrence/content")
        if self.parent and self.parent.revision != self.identity.revision:
            raise ValueError("parent must belong to exact same revision")
        spans = self.provenance.spans + (self.quality.evidence if self.quality else ())
        if any(s.source != self.identity.revision.source for s in spans):
            raise ValueError("node provenance must belong to its source")
        for attr, kind in (("list", NodeType.LIST), ("table", NodeType.TABLE),
                           ("cell", NodeType.TABLE_CELL), ("link", NodeType.LINK)):
            if getattr(self.attributes, attr) is not None and self.node_type != kind:
                raise ValueError("physical attributes incompatible with node type")
        return self


class ValidationState(str, Enum):
    UNVALIDATED = "unvalidated"
    VALIDATED = "validated"
    REJECTED = "rejected"


class StructuralEdge(Value):
    from_node: NodeIdentity
    to_node: NodeIdentity
    relation: Relation
    field: Name | None = None
    role: SemanticRole | None = None
    provenance: Provenance
    validation_state: ValidationState

    @model_validator(mode="after")
    def coherent(self):
        a, b = self.from_node.revision.source, self.to_node.revision.source
        if (a.organization_id, a.bot_id) != (b.organization_id, b.bot_id):
            raise ValueError("edge endpoints must share organization and bot")
        if any(s.source not in (a, b) for s in self.provenance.spans):
            raise ValueError("edge evidence must belong to a pinned endpoint source")
        if self.validation_state == ValidationState.VALIDATED and all(
                s.location.system == CoordinateSystem.UNAVAILABLE for s in self.provenance.spans):
            raise ValueError("validated edge requires located evidence")
        return self


class ChunkStructuralMapping(Value):
    """Mapping DTO only; no chunk is created, fetched or serialized here."""
    node: NodeIdentity
    chunk_revision: RevisionIdentity
    chunk_id: Name
    ordinal: NonNegative
    node_slice: ByteRange
    output_slice: ByteRange
    role: Literal["body", "heading", "header", "qualifier"]
    bundle_key: Name | None = None
    part_index: NonNegative | None = None
    part_count: Positive | None = None

    @model_validator(mode="after")
    def coherent(self):
        if self.node.revision != self.chunk_revision:
            raise ValueError("mapping cannot cross source/revision ownership")
        parts = (self.bundle_key, self.part_index, self.part_count)
        if any(v is not None for v in parts) and not all(v is not None for v in parts):
            raise ValueError("bundle requires key, index and count")
        if self.part_index is not None and self.part_index >= self.part_count:
            raise ValueError("part index outside bundle")
        return self


class StructuralDocument(Value):
    schema_version: Literal["structural-v1"] = SCHEMA_VERSION
    revision: StructureRevisionDescriptor
    nodes: tuple[StructuralNode, ...] = Field(min_length=1, max_length=10000)
    edges: tuple[StructuralEdge, ...] = Field(default=(), max_length=20000)
    mappings: tuple[ChunkStructuralMapping, ...] = ()

    @model_validator(mode="after")
    def coherent(self):
        # Linear validation plus canonical sorting. No traversal or I/O.
        nodes = {n.identity.node_key: n for n in self.nodes}
        if len(nodes) != len(self.nodes) or len({n.preorder for n in self.nodes}) != len(nodes):
            raise ValueError("duplicate node key or preorder")
        roots = [n for n in self.nodes if n.parent is None]
        if len(roots) != 1 or roots[0].node_type != NodeType.DOCUMENT or roots[0].preorder != 0:
            raise ValueError("one document root at preorder zero required")
        children: dict[str, list[StructuralNode]] = {}
        leaf_orders = []
        for n in self.nodes:
            if n.identity.revision != self.revision.identity:
                raise ValueError("node belongs to different document/revision")
            if n.parent:
                p = nodes.get(n.parent.node_key)
                if p is None or p.identity != n.parent or p.preorder >= n.preorder:
                    raise ValueError("parent must exist and precede child")
                children.setdefault(p.identity.node_key, []).append(n)
            if n.leaf_order is not None:
                leaf_orders.append((n.preorder, n.leaf_order, n.identity.node_key))
        ordered_leaves = sorted(leaf_orders)
        if len({v for _, v, _ in ordered_leaves}) != len(ordered_leaves) or [v for _, v, _ in ordered_leaves] != sorted(v for _, v, _ in ordered_leaves):
            raise ValueError("leaf reading order must be unique and follow preorder")
        if any(k in children for _, _, k in ordered_leaves):
            raise ValueError("container cannot assert leaf reading order")
        depths, tables, cells = {}, {}, set()
        for n in sorted(self.nodes, key=lambda n: n.preorder):
            key = n.identity.node_key
            parent_key = n.parent.node_key if n.parent else None
            depths[key] = depths[parent_key] + 1 if parent_key else 0
            if depths[key] > 32:
                raise ValueError("structural tree exceeds depth bound")
            tables[key] = key if n.node_type == NodeType.TABLE else tables.get(parent_key)
            if n.attributes.cell:
                table_key = tables[key]
                table = nodes[table_key].attributes.table if table_key else None
                cell = n.attributes.cell
                if table is None or nodes[parent_key].node_type != NodeType.TABLE_ROW:
                    raise ValueError("cell requires table/row parentage and dimensions")
                if cell.row + cell.row_span > table.row_count or cell.column + cell.column_span > table.column_count:
                    raise ValueError("cell exceeds declared table dimensions")
                position = (table_key, cell.row, cell.column)
                if position in cells:
                    raise ValueError("duplicate table cell coordinate")
                cells.add(position)
        for n in self.nodes:
            attrs = n.attributes
            if attrs.list:
                items = [c for c in children.get(n.identity.node_key, ()) if c.node_type == NodeType.LIST_ITEM]
                if len(items) > attrs.list.item_count or (attrs.list.source_block_complete and len(items) != attrs.list.item_count):
                    raise ValueError("complete list must contain declared item count")
            if attrs.cell:
                for k in attrs.cell.header_keys:
                    h = nodes.get(k)
                    if h is None or not h.attributes.cell or not h.attributes.cell.is_header:
                        raise ValueError("table header reference must name a local header cell")
                    if tables[h.identity.node_key] != tables[n.identity.node_key]:
                        raise ValueError("header belongs to a different table")
        edge_keys = set()
        for e in self.edges:
            if e.from_node.revision != self.revision.identity or nodes.get(e.from_node.node_key) is None:
                raise ValueError("edge origin must be a local node")
            origin = nodes[e.from_node.node_key]
            if e.relation == Relation.HEADING_FOR and origin.node_type != NodeType.HEADING:
                raise ValueError("HEADING_FOR origin must be heading")
            if e.to_node.revision == self.revision.identity:
                target = nodes.get(e.to_node.node_key)
                if target is None:
                    raise ValueError("local edge target missing")
                if e.relation == Relation.CONTAINS and target.parent == origin.identity:
                    raise ValueError("tree parentage must not be duplicated as CONTAINS")
                if e.relation == Relation.QA_PAIR and (origin.semantic_role != SemanticRole.FAQ_QUESTION or target.semantic_role != SemanticRole.FAQ_ANSWER):
                    raise ValueError("QA_PAIR requires question/answer roles")
            key = e.canonical_json()
            if key in edge_keys:
                raise ValueError("duplicate semantic edge")
            edge_keys.add(key)
        ordinals = set()
        for m in self.mappings:
            n = nodes.get(m.node.node_key)
            if n is None or n.identity != m.node or m.node_slice.end > len(n.text.encode("utf-8")):
                raise ValueError("mapping must name local node and valid byte slice")
            encoded = n.text.encode("utf-8")
            try:
                encoded[:m.node_slice.start].decode("utf-8")
                encoded[:m.node_slice.end].decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("mapping splits UTF-8 character") from exc
            key = (m.chunk_id, m.ordinal)
            if key in ordinals:
                raise ValueError("duplicate chunk mapping ordinal")
            ordinals.add(key)
        object.__setattr__(self, "nodes", tuple(sorted(self.nodes, key=lambda n: (n.preorder, n.identity.node_key))))
        object.__setattr__(self, "edges", tuple(sorted(self.edges, key=lambda e: e.canonical_json())))
        object.__setattr__(self, "mappings", tuple(sorted(self.mappings, key=lambda m: (m.chunk_id, m.ordinal))))
        return self
