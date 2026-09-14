"""Domain-neutral request contracts. No I/O, model output, or ORM authorization.

Routing is a hint until a complete, confident identity proof permits narrowing.
Pattern adaptations (not copied implementation): RAGFlow navigation, LlamaIndex
typed routing/composition, Onyx access-filter separation. See the Phase 2.5 ledger.
"""
from dataclasses import asdict, dataclass, replace, field
from enum import Enum
import hashlib
import json

from services.requested_propositions import RequestedProposition

CONTRACT_VERSION = "2.5"


class SemanticScopeState(str, Enum):
    UNRESOLVED = "unresolved"
    AMBIGUOUS = "ambiguous"
    RESOLVED_SINGLE = "resolved_single"
    RESOLVED_MULTI = "resolved_multi"
    INCOMPLETE_COMPARISON = "incomplete_comparison"


class ScopeStrategy(str, Enum):
    EXACT_SCOPED = "exact_scoped"
    BROAD_AUTHORIZED = "broad_authorized"
    DISCOVERY_REQUIRED = "discovery_required"
    CLARIFICATION_REQUIRED = "clarification_required"


class AbsenceBasis(str, Enum):
    NONE = "none"
    SELECTED_CONTEXT = "no_evidence_in_selected_context"
    SEMANTIC_SCOPE = "no_evidence_in_semantic_scope"
    CATALOG_CHECKED = "authorized_catalog_checked_not_found"
    LIVE_DATA = "live_data_unavailable"
    TECHNICAL = "technical_failure"
    PROVIDER = "provider_failure"
    UNRESOLVED = "unresolved_resource"


@dataclass(frozen=True)
class ProfileIdentity:
    provider: str
    model: str
    version: int
    dimensions: int


@dataclass(frozen=True)
class HardKnowledgeScope:
    organization_id: int | None
    bot_id: int
    # None is the SQL predicate universe; () is empty, never a wildcard.
    authorized_document_ids: tuple[int, ...] | None = None
    authorized_source_ids: tuple[int, ...] | None = None
    embedding_profile: ProfileIdentity | None = None
    corpus_fingerprint: str = ""
    active_document_versions: tuple[tuple[int, int, int | None], ...] = ()
    lifecycle_rule: str = "ready_document_and_chunk_completed_processing"
    active_crawl_rule: str = "ready_website_active_crawl_matching_version_or_upload"
    excluded_states: tuple[str, ...] = ("deleted", "error", "failed", "processing", "superseded")
    permission_context: str = "server_bot_organization_knowledge"
    provenance: str = "database_owned_ready_scope"

    def __post_init__(self):
        for key in ("authorized_document_ids", "authorized_source_ids"):
            values = getattr(self, key)
            if values is not None:
                object.__setattr__(self, key, tuple(sorted(set(values))))
        object.__setattr__(self, "excluded_states", tuple(self.excluded_states))
        object.__setattr__(self, "active_document_versions", tuple(tuple(v) for v in self.active_document_versions))

    @property
    def empty(self):
        return self.organization_id is None or self.authorized_document_ids == () or self.authorized_source_ids == ()

    def intersect(self, document_ids):
        if self.empty:
            return ()
        if document_ids is None:
            return self.authorized_document_ids
        ids = set(document_ids)
        if self.authorized_document_ids is not None:
            ids.intersection_update(self.authorized_document_ids)
        return tuple(sorted(ids))

    def identity(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class KnowledgeResourceRef:
    resource_id: str
    organization_id: int
    bot_id: int
    canonical_name: str
    resource_type: str = "document"  # Open vocabulary, not an ecommerce enum.
    aliases: tuple[str, ...] = ()
    document_ids: tuple[int, ...] = ()
    chunk_ids: tuple[int, ...] = ()
    title: str | None = None
    url: str | None = None
    breadcrumb: tuple[str, ...] = ()
    parent_id: str | None = None
    status: str = "ready"
    version: int | None = None
    # Immutable, safe descriptive pairs, not arbitrary executable/source metadata.
    metadata: tuple[tuple[str, str], ...] = ()
    heading_path: tuple[str, ...] = ()
    section_id: str | None = None
    sibling_position: int | None = None
    table_id: str | None = None
    list_id: str | None = None
    contextualized_representation: str | None = None


@dataclass(frozen=True)
class ResourceCandidate:
    resource: KnowledgeResourceRef
    mention: str = ""
    matched_span: tuple[int, int] | None = None
    match_sources: tuple[str, ...] = ()
    confidence: float = 0.0
    canonical_exact: bool = False
    alias_exact: bool = False
    planner_hint: bool = False
    conversation_hint: bool = False
    scores: tuple[tuple[str, float], ...] = ()
    ambiguous: bool = False
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class SoftSemanticScope:
    resource_candidates: tuple[ResourceCandidate, ...] = ()
    resolved_resources: tuple[KnowledgeResourceRef, ...] = ()
    unresolved_mentions: tuple[str, ...] = ()
    comparison_requested: bool = False
    comparison_members: tuple[str, ...] = ()
    active_conversation_resources: tuple[str, ...] = ()
    topic_hints: tuple[str, ...] = ()
    planner_hints: tuple[str, ...] = ()
    ambiguity: bool = False
    confidence: float = 0.0
    state: SemanticScopeState = SemanticScopeState.UNRESOLVED
    reason_codes: tuple[str, ...] = ()

    @property
    def resolved_document_ids(self):
        return tuple(sorted({i for r in self.resolved_resources for i in r.document_ids}))


@dataclass(frozen=True)
class ScopeDecision:
    strategy: ScopeStrategy
    effective_document_ids: tuple[int, ...] | None
    semantic_document_ids: tuple[int, ...]
    exact_narrowing_applied: bool
    reason: str
    absence_basis: AbsenceBasis = AbsenceBasis.SELECTED_CONTEXT


def choose_scope_strategy(hard: HardKnowledgeScope, soft: SoftSemanticScope, *, broad_request=False,
                          clarification_required=False, no_retrieval=False, identity_overflow=False) -> ScopeDecision:
    """The ONLY narrowing policy. A candidate is not an access-control grant."""
    semantic = soft.resolved_document_ids
    def decision(strategy, ids, exact, reason, absence=AbsenceBasis.SELECTED_CONTEXT):
        # None means all of THIS hard scope, not all database documents.
        effective = None if ids is None and not hard.empty else hard.intersect(ids)
        return ScopeDecision(strategy, effective, semantic, exact, reason, absence)
    if hard.empty:
        if hard.provenance == "embedding_profile_unavailable":
            return decision(ScopeStrategy.BROAD_AUTHORIZED, (), False, "incompatible_embedding_profile", AbsenceBasis.TECHNICAL)
        return decision(ScopeStrategy.BROAD_AUTHORIZED, (), False, "empty_hard_scope")
    if identity_overflow:
        return decision(ScopeStrategy.CLARIFICATION_REQUIRED, None, False, "identity_limit_reached", AbsenceBasis.UNRESOLVED)
    if no_retrieval:
        return decision(ScopeStrategy.BROAD_AUTHORIZED, (), False, "no_knowledge_request")
    valid = all(r.organization_id == hard.organization_id and r.bot_id == hard.bot_id
                and r.status == "ready" and r.document_ids
                and hard.intersect(r.document_ids) == tuple(sorted(set(r.document_ids)))
                for r in soft.resolved_resources)
    if not valid:
        return decision(ScopeStrategy.CLARIFICATION_REQUIRED, (), False, "invalid_resource_scope", AbsenceBasis.UNRESOLVED)
    # Incomplete intent takes precedence over earlier deterministic clarification
    # or an exact first member. Neither a planner nor history can erase it.
    if soft.comparison_requested and (soft.unresolved_mentions or len({r.resource_id for r in soft.resolved_resources}) < 2
                                      or soft.state == SemanticScopeState.INCOMPLETE_COMPARISON):
        return decision(ScopeStrategy.DISCOVERY_REQUIRED, None, False, "incomplete_comparison", AbsenceBasis.UNRESOLVED)
    if broad_request:
        return decision(ScopeStrategy.BROAD_AUTHORIZED, None, False, "broad_user_request")
    if soft.ambiguity or soft.state == SemanticScopeState.AMBIGUOUS or clarification_required:
        return decision(ScopeStrategy.CLARIFICATION_REQUIRED, None, False, "ambiguous_resource", AbsenceBasis.UNRESOLVED)
    if soft.unresolved_mentions:
        return decision(ScopeStrategy.DISCOVERY_REQUIRED, None, False, "unresolved_resource", AbsenceBasis.UNRESOLVED)
    proofs = {c.resource.resource_id: c for c in soft.resource_candidates if not c.ambiguous and c.confidence >= .8
              and (c.canonical_exact or c.alias_exact or "authorized_identity" in c.match_sources)}
    complete_proof = bool(soft.resolved_resources) and all(r.resource_id in proofs and proofs[r.resource_id].resource == r
                                                        for r in soft.resolved_resources)
    if complete_proof and soft.state in {SemanticScopeState.RESOLVED_SINGLE, SemanticScopeState.RESOLVED_MULTI}:
        return decision(ScopeStrategy.EXACT_SCOPED, semantic, True,
                        "confident_multi_resource" if len(soft.resolved_resources) > 1 else "confident_single_resource")
    return decision(ScopeStrategy.BROAD_AUTHORIZED, None, False, "safe_authorized_default")


@dataclass(frozen=True)
class CatalogAbsenceCheck:
    """A future authoritative check must provide complete scope/query-bound proof.

    Bounded chunk recall, model suggestions and empty context are NOT such proof.
    Phase 2.5 deliberately does not implement a catalog checker.
    """
    hard_scope_identity: str
    original_query_sha256: str
    checked_document_ids: tuple[int, ...]
    complete: bool
    found: bool
    provenance: str


@dataclass(frozen=True)
class QueryExecutionContract:
    original_user_message: str
    retrieval_query: str
    hard_scope: HardKnowledgeScope
    soft_scope: SoftSemanticScope
    scope_decision: ScopeDecision
    requested_fields: tuple[str, ...] = ()
    requested_propositions: tuple[RequestedProposition, ...] = ()
    intent: str = "unknown"
    version: str = CONTRACT_VERSION
    catalog_absence_check: CatalogAbsenceCheck | None = None
    resource_discovery: dict = field(default_factory=dict)
    discovery_identity: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.scope_decision.absence_basis == AbsenceBasis.CATALOG_CHECKED and not self.catalog_absence_supported(self.catalog_absence_check):
            raise ValueError("Catalog absence requires a complete authorized resource check")

    def trace_sections(self):
        # Never emit resource.metadata/contextualized representations or scores'
        # raw provider payloads. Descriptive names are redacted by ChatTrace.
        soft = self.soft_scope
        result = {"hard_scope": asdict(self.hard_scope), "soft_scope": {
            "state": soft.state.value, "ambiguity": soft.ambiguity, "confidence": soft.confidence,
            "resolved_resource_ids": [r.resource_id for r in soft.resolved_resources],
            "resolved_document_ids": soft.resolved_document_ids,
            "candidate_document_ids": sorted({i for c in soft.resource_candidates for i in c.resource.document_ids}),
            "unresolved_mentions": soft.unresolved_mentions, "comparison_requested": soft.comparison_requested,
            "comparison_members": soft.comparison_members, "reason_codes": soft.reason_codes,
            "active_conversation_resources": soft.active_conversation_resources,
            "candidates": [{"resource_id": c.resource.resource_id, "document_ids": c.resource.document_ids,
                            "match_sources": c.match_sources, "confidence": c.confidence,
                            "ambiguous": c.ambiguous, "reason_codes": c.reason_codes} for c in soft.resource_candidates],
        }, "scope_decision": asdict(self.scope_decision)}
        if self.resource_discovery:
            result["resource_discovery"] = self.resource_discovery
        return result

    def cache_identity(self):
        sections = self.trace_sections()
        sections.pop("resource_discovery", None)  # Scores/timings aren't identity.
        result = {"version": self.version, "original_sha256": hashlib.sha256(self.original_user_message.encode()).hexdigest(),
                  "retrieval_query": self.retrieval_query, **sections}
        if self.discovery_identity:
            result["discovery"] = self.discovery_identity
        return result

    def catalog_absence_supported(self, check: CatalogAbsenceCheck | None):
        return bool(check and check.complete and not check.found and check.provenance == "authorized_resource_catalog_check"
                    and self.hard_scope.authorized_document_ids is not None
                    and check.hard_scope_identity == self.hard_scope.identity()
                    and check.original_query_sha256 == hashlib.sha256(self.original_user_message.encode()).hexdigest()
                    and tuple(sorted(set(check.checked_document_ids))) == self.hard_scope.authorized_document_ids)

    def absence_instructions(self):
        return ("Evidence scope rule: missing selected evidence or an unresolved name does not establish catalog absence. "
                "Do not say an item is absent from the business/catalog unless a separate complete authorized catalog check supports it. "
                "For unresolved comparison members, keep the requested member visible, state which requested details you cannot confirm, "
                "and never substitute the known member's facts. Technical/provider failures are not missing business knowledge.")

    def with_catalog_absence(self, check: CatalogAbsenceCheck):
        if not self.catalog_absence_supported(check):
            raise ValueError("Catalog absence requires a complete authorized resource check")
        return replace(self, catalog_absence_check=check,
                       scope_decision=replace(self.scope_decision, absence_basis=AbsenceBasis.CATALOG_CHECKED))
