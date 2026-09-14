"""Adapt existing, authorized identity results to the generalized scope policy.

No resource discovery, new alias matcher, or model call lives here. The small
comparison guard preserves unresolved user mentions rather than guessing them.
"""
import re

from services.query_contract import FIELD_ONTOLOGY, MULTI_ENTITY_CONTINUATION_PATTERN, _document_values, normalize_text, split_exclusions, current_turn_anchor, is_capability_discovery
from services.retrieval_contracts import (
    AbsenceBasis, HardKnowledgeScope, KnowledgeResourceRef, QueryExecutionContract,
    ResourceCandidate, SemanticScopeState, SoftSemanticScope, ScopeStrategy, choose_scope_strategy,
)


class ComparisonParsingLimit(ValueError):
    """A plausible comparison exceeded bounded member parsing; never narrow."""


def between_choice_span(text):
    """Two named alternatives followed by a choice predicate, not a third item.

    Keep punctuation until the noun phrase boundary is found; ordinary field
    prose after 'which' must not become part of the second resource name.
    """
    if len(text) > 8192:
        return None
    match = re.search(
        r"\bbetween\s+([^.!?;]{1,420}?)\s*[,;:]?\s+which\s+(?:one\s+)?"
        r"(?:is|has|have|takes?|would|works?|fits?|offers?|needs?|requires?|suits?)\b",
        text, re.I,
    )
    if not match or not re.search(r"\band\b", match[1], re.I):
        return None
    prefix = re.split(r"[.!?;]", text[:match.start()])[-1]
    if re.search(r"\b(?:what|which)\b.{0,80}\b(?:is|comes?|lies?)\s*$", prefix, re.I):
        return None
    return match[1].strip(' ,:')


def comparison_mentions(positive, known_names=()):
    """Conservative noun-phrase alternatives, not an entity/NLP parser.

    Existing canonical names protect their own internal conjunctions. An action
    alternative ('PDF or find more information') is not a resource comparison.
    Unrecognized nouns remain unresolved; this function never assigns IDs.
    """
    choice = between_choice_span(positive)
    trailing = re.match(r"^how\s+(?:do|does|would)\s+([^.!?;]{1,420}?)\s+compare\b", positive, re.I)
    if not choice and trailing and re.search(r"\b(?:and|or|versus|vs)\b", trailing[1], re.I):
        choice = trailing[1]  # Here the named members precede the predicate.
    colon_choice = re.search(r"\bwhich\b[^.!?;:]{0,240}:\s*([^.!?;]+)", positive, re.I)
    if not choice and colon_choice and re.search(r"\b(?:or|versus|vs)\b", colon_choice[1], re.I):
        choice = colon_choice[1]
    text = normalize_text('compare ' + choice if choice else positive)
    if len(text) > 8192:
        return ()  # Caller records overflow and prohibits exact narrowing.
    names = [normalize_text(n) for n in known_names if n]
    protected = [(m.start(), m.end()) for n in names for m in re.finditer(re.escape(n), text)]
    comparison_start = re.search(r"\b(?:compare|difference between|choose between|decide between)\b", text)
    # An anchored resource's attribute alternatives are not additional entities.
    # A real resource choice has members on both sides, or a choice predicate.
    if not comparison_start and current_turn_anchor(positive):
        return ()
    # An explicit comparison's noun list ends before its requested-field/purpose
    # clause. Later field alternatives (months A versus B, price and duration)
    # are not additional resources. Keep unknown members and protected names.
    if comparison_start:
        member_separators = [s for s in re.finditer(r"\b(?:and|with|or|versus|vs)\b", text)
                             if s.start() > comparison_start.end()
                             and not any(a <= s.start() < b for a, b in protected)]
        for boundary in re.finditer(r"[:;!?]|\.(?=\s)|\s+(?:for|on|in terms of)\b", text):
            if (any(s.end() < boundary.start() for s in member_separators)
                    and not any(a <= boundary.start() < b for a, b in protected)):
                text = text[:boundary.start()]
                break
    separators = list(re.finditer(r"\b(?:or|versus|vs)\b", text))
    if comparison_start:
        separators += [s for s in re.finditer(r"\b(?:and|with)\b", text) if s.start() > comparison_start.end()]
    if not separators:
        return ()
    # Do not split an already matched canonical name's own 'and/or'.
    separators = sorted((s for s in separators if not any(a <= s.start() < b for a, b in protected)), key=lambda s: s.start())
    if not separators:
        return ()
    parts, start = [], 0
    for separator in separators:
        parts.append(text[start:separator.start()])
        start = separator.end()
    parts.append(text[start:])
    cleaned = []
    if len(parts) > 9:
        return ()  # Caller treats excessive comparison cues as ambiguous.
    for index, part in enumerate(parts):
        part = part.strip(" ,.?;:")
        if index == 0:
            part = re.split(r"\b(?:would|should|compare|difference between|choose between|decide between|about)\b", part)[-1].strip()
            part = re.sub(r"^(?:which is better[, :]*|is|are|can i choose|do you provide)\s+", "", part)
        elif re.match(r"(?:find|download|read|learn|browse|get|see|ask|contact|tell|show)\b", part):
            return ()
        # Strong names may be followed by arbitrary requested field prose. Use
        # an existing identity verbatim, not a newly synthesized alias.
        matched = [n for n in names if re.match(r"^(?:the |a |an )?" + re.escape(n) + r"(?:\b|$)", part)]
        if index == 0 and not matched:
            matched = [n for n in names if re.search(r"\b" + re.escape(n) + r"$", part)]
        if matched:
            part = max(matched, key=len)
        else:
            # A final field list is additive, not a third comparison member.
            # Reuse the existing field vocabulary; do not invent domain nouns.
            if index >= 2 and any(re.fullmatch(pattern, part, re.I)
                                  for patterns in FIELD_ONTOLOGY.values() for pattern in patterns):
                continue
            part = re.split(r"\s+(?:give|help|cost|compare|work|have|has|offer|offers|provide|provides|fit|be|is|are|"
                            r"for|before|after|on|in terms of|to see)\b", part, maxsplit=1)[0]
            part = re.sub(r"^(?:the|a|an)\s+", "", part)
        part = part.strip(" ,.?;:")
        if not part or len(part) > 200:
            raise ComparisonParsingLimit("Comparison member is empty or exceeds the parsing bound")
        cleaned.append(part)
    return tuple(dict.fromkeys(cleaned)) if len(set(cleaned)) >= 2 else ()


def resource_ref(doc, canonical_name=None):
    metadata = doc.metadata_json if isinstance(doc.metadata_json, dict) else {}
    # Descriptors only. Do not copy arbitrary customer metadata into instructions,
    # trace or policy. These optional fields do not implement structural recall.
    kind = metadata.get("resource_type")
    return KnowledgeResourceRef(
        resource_id=f"org:{doc.organization_id}:bot:{doc.bot_id}:document:{doc.id}",
        organization_id=doc.organization_id, bot_id=doc.bot_id,
        canonical_name=canonical_name or doc.title or doc.filename, resource_type=kind if isinstance(kind, str) else "document",
        document_ids=(doc.id,), title=doc.title, url=doc.canonical_url or doc.source_url,
        status=doc.status, version=doc.version,
    )


def attach_execution_contract(contract, documents, state, plan, hard: HardKnowledgeScope, resolve_subject,
                              current_entities=(), *, identity_overflow=False):
    """All documents were SQL-authorized before planner/identity processing."""
    authorized_ids = set(hard.authorized_document_ids) if hard.authorized_document_ids is not None else None
    by_id = {d.id: d for d in documents if not hard.empty and d.bot_id == hard.bot_id and d.organization_id == hard.organization_id
             and d.status == "ready" and (authorized_ids is None or d.id in authorized_ids)}
    positive, _ = split_exclusions(contract.original_query)
    known_names = [value for d in by_id.values() for value in _document_values(d)]
    parser_limited = False
    try:
        mentions = comparison_mentions(positive, known_names)
    except ComparisonParsingLimit:
        mentions, parser_limited = (), True
    if (not mentions and not current_turn_anchor(positive) and not is_capability_discovery(positive)
            and not current_entities and MULTI_ENTITY_CONTINUATION_PATTERN.search(positive)
            and state.get("semantic_state") == "incomplete_comparison"):
        mentions = tuple(state.get("comparison_members", ()))
    broad_request = contract.mode in {"catalog", "filter"}
    comparison = bool(parser_limited or mentions or contract.mode == "comparison" or (contract.comparison_entities and not broad_request))
    # A planner may add multi-resource caution, never remove explicit members.
    if plan and plan.comparison_requested and not comparison:
        mentioned = [name for name in plan.active_subjects if normalize_text(name) in positive]
        if len(mentioned) >= 2:
            mentions, comparison = tuple(mentioned), True
    entities = list(contract.resolved_entities)
    unresolved = []
    if mentions:
        matched = [resolve_subject(name, list(by_id.values())) for name in mentions]
        unresolved = [name for name, entity in zip(mentions, matched) if entity is None]
        entities = list({e.document_id: e for e in matched if e and e.document_id in by_id}.values())
    elif comparison and len(entities) < 2:
        # Known partial identity is a hint even when the earlier comparison
        # branch refused to make it the sole subject.
        entities = list({e.document_id: e for e in (*entities, *current_entities) if e.document_id in by_id}.values())
        mentions = tuple(contract.comparison_entities)
        unresolved = [name for name in mentions if resolve_subject(name, list(by_id.values())) is None]
    overflow = parser_limited or identity_overflow or len(positive) > 8192 or len(re.findall(r"\b(?:or|versus|vs|and)\b", positive)) > 8
    ambiguous = contract.requires_clarification and not mentions and not (comparison and (unresolved or len(entities) < 2))
    if overflow:
        ambiguous = True
    resources = tuple(resource_ref(by_id[e.document_id], e.name) for e in entities if e.document_id in by_id)
    active_ids = {e.get("document_id") for e in state.get("active_subjects", []) if isinstance(e, dict)}
    candidates = []
    # Deduplicate by tenant-qualified identity, not content or vector-score winner.
    for entity in (*entities, *current_entities):
        if entity.document_id not in by_id or any(c.resource.document_ids == (entity.document_id,) for c in candidates):
            continue
        resource = resource_ref(by_id[entity.document_id], entity.name)
        name = normalize_text(entity.name)
        exact = name in positive
        candidates.append(ResourceCandidate(resource, mention=name if exact else "",
                          match_sources=("authorized_identity", "canonical_exact" if exact else "existing_identity_resolver"),
                          confidence=entity.confidence, canonical_exact=exact,
                          conversation_hint=entity.document_id in active_ids and not exact,
                          reason_codes=("database_revalidated_identity",)))
    if comparison and (unresolved or len(resources) < 2):
        scope_state = SemanticScopeState.INCOMPLETE_COMPARISON
    elif ambiguous:
        scope_state = SemanticScopeState.AMBIGUOUS
    elif len(resources) > 1:
        scope_state = SemanticScopeState.RESOLVED_MULTI
    elif resources:
        scope_state = SemanticScopeState.RESOLVED_SINGLE
    else:
        scope_state = SemanticScopeState.UNRESOLVED
    if overflow:
        scope_state = SemanticScopeState.AMBIGUOUS
    soft = SoftSemanticScope(
        resource_candidates=tuple(candidates), resolved_resources=resources,
        unresolved_mentions=tuple(unresolved), comparison_requested=comparison,
        comparison_members=mentions or tuple(e.name for e in entities) if comparison else (),
        active_conversation_resources=tuple(resource_ref(by_id[i]).resource_id for i in sorted(active_ids & by_id.keys())),
        topic_hints=tuple(contract.catalog_scope), planner_hints=(plan.scope_mode,) if plan else (),
        ambiguity=ambiguous, confidence=min((e.confidence for e in entities), default=0.0), state=scope_state,
        reason_codes=("identity_limit_reached",) if overflow else (scope_state.value,),
    )
    decision = choose_scope_strategy(hard, soft, broad_request=contract.mode in {"catalog", "filter"},
                                    clarification_required=ambiguous,
                                    no_retrieval=contract.scope_mode == "global" and not comparison,
                                    identity_overflow=overflow)
    if scope_state == SemanticScopeState.INCOMPLETE_COMPARISON and not overflow:
        contract.mode, contract.intent, contract.scope_mode = "comparison", "comparison", "uncertain"
        contract.resolved_entities = [e for e in entities if e.document_id in by_id]
        contract.resolved_subject, contract.subject_document_id, contract.subject_confidence = None, None, 0.0
        contract.comparison_entities = list(soft.comparison_members)
        contract.ambiguity_status, contract.clarification_prompt = "clear", None
        # An incomplete model rewrite must not erase an unresolved member.
        contract.retrieval_query = " ".join(filter(None, [contract.original_query, " ".join(contract.requested_fields)]))
        contract.resolved_query = contract.retrieval_query
    elif mentions and decision.exact_narrowing_applied:
        contract.mode, contract.intent, contract.scope_mode = "comparison", "comparison", "multi_entity"
        contract.resolved_entities = entities
        contract.resolved_subject, contract.subject_document_id, contract.subject_confidence = None, None, soft.confidence
        contract.comparison_entities = [e.name for e in entities]
        contract.ambiguity_status, contract.clarification_prompt = "clear", None
    if decision.strategy == ScopeStrategy.CLARIFICATION_REQUIRED:
        contract.ambiguity_status = "needs_subject_clarification"
        contract.clarification_prompt = contract.clarification_prompt or "Which item do you mean? Please give its full name."
    if decision.absence_basis == AbsenceBasis.TECHNICAL:
        contract.ambiguity_status, contract.clarification_prompt = "clear", None
    contract.execution = QueryExecutionContract(
        contract.original_query, contract.retrieval_query, hard, soft, decision,
        tuple(contract.requested_fields), tuple(contract.requested_propositions), contract.intent,
    )
    ids = decision.effective_document_ids
    contract.permitted_document_ids = list(ids) if ids is not None else None
    contract.entity_resolution.update({"scope_policy": decision.reason, "semantic_state": soft.state.value})
    return contract
