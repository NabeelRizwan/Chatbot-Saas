"""Bounded search-opportunity policy, NOT resource identity or catalog evidence.

No query transformation/search/model call is performed. See the Phase 3.4
adaptation ledger. Identity specificity/scoring remains owned by discovery.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
import re

from services.resource_normalization import normalize_resource_text
from services.resource_probe_builder import RESOURCE_TYPES, informative_tokens, strip_request

SEMANTIC_GAP_VERSION = "semantic-gap-3.4.0"
# Request grammar is discounted only for opportunity assessment. Do not change
# informative_tokens itself: its identity-specificity semantics are independent.
_REQUEST_FILLER = frozenset("""and or but with from into about can could would will
    should does do did you they them guys please show send find tell give looking
    someone somebody something anything everything just need want offer provide
    have has mostly only both also this that these those there here how what which
    where when why is are was were am not yes no me it its some more much many
    thanks thank help information details""".split())


@dataclass(frozen=True)
class SemanticGapAssessment:
    eligible_for_optimizer: bool
    basis: str
    reason_codes: tuple[str, ...]
    logical_probe_id: str
    candidate_count: int
    informative_token_count: int
    resource_type_hint: str
    comparison_group: str
    comparison_member: int | None
    explicit_current_user_span: bool
    current_span_sha256: str

    def trace(self):
        return {"version": SEMANTIC_GAP_VERSION, **asdict(self)}

    def cache_identity(self):
        # No timing, mutable score, arbitrary text or candidate payload here.
        return (self.logical_probe_id, self.eligible_for_optimizer, self.basis)


def assess_semantic_gap(resolution, *, hard, search_healthy, catalog_available):
    """Annotate one existing logical resolution; never manufacture a candidate.

    Insufficient lexical identity may still leave a useful current-user search
    description. Conflicting identities, category/relation/technical outcomes
    and empty authorization cannot be converted into this opportunity.
    """
    probe = resolution.probe
    span = probe.original_span or probe.text
    current = probe.provenance == "explicit_user" and probe.probe_kind != "conversation_reference"
    span_hash = hashlib.sha256(span.encode()).hexdigest()
    key = (span_hash, probe.provenance, probe.comparison_group_id, probe.comparison_member_index)
    probe_id = hashlib.sha256(json.dumps(key).encode()).hexdigest()
    information = set()
    # Same 512-character identity bound, including original provenance. No
    # truncated long request is allowed to look sufficiently informative.
    bounded = len(span) <= 512
    if bounded:
        clean, _ = strip_request(span)
        information = {t for t in informative_tokens(clean) - _REQUEST_FILLER
                       if t.isalpha() and len(set(t)) > 1}
    informative = bounded and len(information) >= 2
    reasons = set(resolution.reason_codes)
    count = len(resolution.alternatives)

    def result(basis, eligible=False):
        return SemanticGapAssessment(eligible, basis, (basis,), probe_id, count,
            len(information), probe.explicit_resource_type_hint or probe.inherited_resource_type_hint,
            probe.comparison_group_id, probe.comparison_member_index, current, span_hash)

    if hard is None or hard.empty:
        return result("empty_hard_scope")
    if not search_healthy or "identity_channel_unavailable" in reasons:
        return result("technical_failure")
    if resolution.state.value == "resolved" or resolution.candidate is not None:
        return result("not_eligible")
    if probe.category_intent or "category_resource_set" in reasons:
        return result("category")
    # A type-qualified successor/predecessor request also needs ordered data,
    # not a semantic substitute. This veto does not rewrite discovery probes
    # or override an identity already resolved above.
    ordered = re.search(r"\b(?:next|previous)\s+(\w+)\s+(?:after|before)\s+\w", span, re.I) if bounded else None
    if (probe.relation_intent or "structured_relation_required" in reasons
            or (ordered and normalize_resource_text(ordered.group(1)) in RESOURCE_TYPES)):
        return result("structured_relation_required")
    # Candidate-backed lexical ambiguity can remain eligible WITHOUT changing
    # clarification. Exact/complete identity collisions and bounds cannot.
    if reasons & {"candidate_limit_prevents_uniqueness", "conflicting_exact_identities",
                  "conflicting_complete_token_identities", "conflicting_probe_variants"}:
        return result("ambiguity")
    if not current or not catalog_available:
        return result("not_eligible")
    if not informative:
        return result("insufficient_input")
    if resolution.state.value == "ambiguous" and "competing_candidates" not in reasons:
        return result("ambiguity")
    if not reasons & {"weak_match", "insufficient_specificity", "competing_candidates", "no_match"}:
        return result("not_eligible")
    if count == 0:
        return result("candidate_free_informative", True)
    plausible = any("identity_term" in c.reason_codes and dict(c.scores).get("numeric_agreement") == 1
                    and (dict(c.scores).get("informative_coverage", 0) > 0
                         or dict(c.scores).get("token_sort", 0) >= 50)
                    for c in resolution.alternatives)
    return result("candidate_backed_insufficient", True) if plausible else result("not_eligible")
