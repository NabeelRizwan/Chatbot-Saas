"""Phase 3 handoff only. Discovery resolves; Phase 2.5 alone narrows scope."""
from dataclasses import replace
import re

from services.query_contract import ResolvedEntity, explicit_identity_candidate, split_exclusions
from services.resource_channels import ResourceProbe
from services.resource_discovery import ResourceDiscoveryService, ResolutionState, ResourceDiscoveryError
from services.resource_normalization import normalize_resource_text
from services.retrieval_contracts import (SoftSemanticScope, SemanticScopeState, choose_scope_strategy,
                                          ScopeStrategy, AbsenceBasis)


def discovery_probes(contract, state):
    from services.resource_probe_builder import build_resource_probes
    return build_resource_probes(contract, state)


def apply_resource_discovery(db, contract, state, trace=None, *, service=None):
    execution = contract.execution
    if execution is None or execution.scope_decision.reason in {"no_knowledge_request", "identity_limit_reached", "incompatible_embedding_profile"}:
        return contract
    try:
        probes = discovery_probes(contract, state)
        result = (service or ResourceDiscoveryService()).discover(db, execution.hard_scope, probes, state,
                                legacy_candidates=execution.soft_scope.resource_candidates)
    except ValueError:
        # Excessively long/complex mentions cannot be truncated into an identity.
        contract.ambiguity_status = "needs_subject_clarification"
        contract.clarification_prompt = "Please give the full name of the item you mean."
        soft = SoftSemanticScope(ambiguity=True, state=SemanticScopeState.AMBIGUOUS)
        decision = choose_scope_strategy(execution.hard_scope, soft, clarification_required=True)
        contract.execution = replace(execution, soft_scope=soft, scope_decision=decision, version="3.2")
        contract.permitted_document_ids = list(decision.effective_document_ids) if decision.effective_document_ids is not None else None
        return contract
    except ResourceDiscoveryError:
        # Do not disguise a missing migration/programming error as no resources.
        if trace:
            trace.retrieval.resource_discovery = {"backend": "resource-discovery-3.0", "status": "technical_failure"}
        raise
    diagnostic = result.trace()
    identity = result.cache_identity(execution.hard_scope)
    if result.status in {"catalog_empty", "empty_hard_scope"}:
        contract.execution = replace(execution, version="3.2", resource_discovery=diagnostic,
                                     discovery_identity=identity)
        if trace:
            trace.retrieval.resource_discovery = diagnostic
        return contract
    resolved = [r.candidate for r in result.resolutions if r.state == ResolutionState.RESOLVED]
    resolved = list({c.resource.resource_id: c for c in resolved}.values())
    unresolved = tuple(r.probe.text for r in result.resolutions if r.state != ResolutionState.RESOLVED)
    comparison = execution.soft_scope.comparison_requested or len(probes) > 1
    ambiguous = any(r.state == ResolutionState.AMBIGUOUS for r in result.resolutions)
    state_value = (SemanticScopeState.INCOMPLETE_COMPARISON if comparison and (unresolved or len(resolved) < 2)
                   else SemanticScopeState.AMBIGUOUS if ambiguous else SemanticScopeState.RESOLVED_MULTI if len(resolved) > 1
                   else SemanticScopeState.RESOLVED_SINGLE if resolved else SemanticScopeState.UNRESOLVED)
    # Candidates in the scope policy carry the central resolution proof, not a
    # raw rank winner. Unresolved alternatives remain soft candidates.
    proof_ids = {c.resource.resource_id for c in resolved}
    candidates = tuple(resolved) + tuple(c for c in result.candidates if c.resource.resource_id not in proof_ids)
    soft = SoftSemanticScope(resource_candidates=candidates, resolved_resources=tuple(c.resource for c in resolved),
        unresolved_mentions=unresolved, comparison_requested=comparison,
        comparison_members=tuple(p.text for p in probes) if comparison else (),
        confidence=min((c.confidence for c in resolved), default=0), ambiguity=ambiguous, state=state_value,
        topic_hints=execution.soft_scope.topic_hints, reason_codes=("central_resource_resolution",)+tuple(dict.fromkeys(
            code for r in result.resolutions for code in r.reason_codes
            if code in {"structured_relation_required","deterministic_discovery_insufficient",
                        "query_optimizer_eligible","unresolved_unknown_resource"})))
    category_request=any(r.probe.category_intent for r in result.resolutions)
    specific_entity=bool(resolved) and not comparison and not category_request
    decision = choose_scope_strategy(execution.hard_scope, soft, broad_request=category_request or
        (contract.mode in {"catalog", "filter"} and not specific_entity))
    contract.execution = replace(execution, soft_scope=soft, scope_decision=decision, version="3.2",
                                 resource_discovery=diagnostic, discovery_identity=identity)
    contract.resolved_entities = [ResolvedEntity(c.resource.canonical_name, c.resource.document_ids[0], c.confidence) for c in resolved]
    contract.resolved_subject = resolved[0].resource.canonical_name if len(resolved) == 1 and not comparison else None
    contract.subject_document_id = resolved[0].resource.document_ids[0] if contract.resolved_subject else None
    contract.subject_confidence = soft.confidence
    contract.permitted_document_ids = list(decision.effective_document_ids) if decision.effective_document_ids is not None else None
    contract.ambiguity_status = "needs_subject_clarification" if decision.strategy == ScopeStrategy.CLARIFICATION_REQUIRED else "clear"
    contract.clarification_prompt = "Which item do you mean? Please give its full name." if contract.requires_clarification else None
    contract.scope_mode = "multi_entity" if decision.exact_narrowing_applied and comparison else "single_entity" if decision.exact_narrowing_applied else "uncertain"
    if comparison:
        contract.mode, contract.intent = "comparison", "comparison"
        contract.comparison_entities = list(soft.comparison_members)
    # Retrieval may use canonical resolved names, but keeps every original
    # member and the exact user question; no rewrite/model work is added.
    contract.retrieval_query = " ".join([contract.original_query] + [c.resource.canonical_name for c in resolved] + contract.requested_fields)
    contract.resolved_query = contract.retrieval_query
    contract.execution = replace(contract.execution, retrieval_query=contract.retrieval_query)
    contract.entity_resolution.update(semantic_state=state_value.value, resolver="resource_discovery",
                                      scope_policy=decision.reason, catalog_revision=result.catalog_revision)
    if trace:
        trace.retrieval.resource_discovery = diagnostic
    return contract
