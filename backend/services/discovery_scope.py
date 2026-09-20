"""Keep explicit set discovery distinct from a resolved routing identity.

This is a semantic-scope safeguard, not an identity resolver or authorization
source. It never changes the query, candidate identities, or hard predicates.
"""
from dataclasses import replace
import re

from services.retrieval_contracts import ScopeStrategy, choose_scope_strategy


def _text(value):
    return re.sub(r"\s+", " ", value.casefold()).strip().rstrip("?.!") if isinstance(value, str) else ""


def _discovery_topic(question):
    # Bounded, anchored grammar: not a search for intent words in arbitrary
    # quoted/source text. 'Any reviews OF X' requests a field of X, not a set of X.
    if not isinstance(question, str) or len(question) > 2000:
        return ""
    q = _text(question)
    match = re.match(r"^(?:are there (?:any |some |other )?|do you (?:have|offer|provide) (?:any |some |other )?)"
                     r"(?P<topic>[\w -]{1,160}?)(?=\s+(?:that|which|with|for|under|over|available)\b|$)", q)
    if not match:
        match = re.match(r"^(?:which|what) (?P<topic>[\w -]{1,160}?)\s+(?:are|can|have|offer|provide)\b", q)
    if not match:
        return ""
    topic = match.group("topic").strip()
    if re.search(r"\b(?:of|about|in|on|the|this|that|one|ones)\b", topic) or not topic.endswith("s"):
        return ""
    return re.sub(r"[\W_]+", " ", topic).strip()


def _set_followup(question):
    # Complete deictic utterances only. An explicit named subject/new request
    # must not inherit a stale discovery topic. No assistant text establishes it.
    return bool(re.fullmatch(
        r"(?:which (?:one|ones)(?: (?:is|are) [\w -]{1,48})?|"
        r"what about (?:the )?other(?: one| ones)?|"
        r"which (?:is|are|tastes?|works?|performs?) (?:\w+ ){0,2}(?:\w+er|best|least|most))",
        _text(question)))


def discovery_scope_reason(question, history, resources):
    names = {re.sub(r"[\W_]+", " ", name.casefold()).strip()
             for resource in resources for name in (resource.canonical_name, *resource.aliases)}
    topic = _discovery_topic(question)
    if topic:
        # The set noun itself matched the identity; incidental field requests
        # mentioning a concrete item are not made broad.
        return "explicit_category_discovery" if topic in names else None
    if not _set_followup(question):
        return None
    if not isinstance(history, (tuple, list)):
        return None
    for message in reversed(history[-8:]):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        previous = message.get("content")
        # A field set (e.g. discounts FOR an item) is not a resource set.
        # Keep the inherited topic bound to an existing resolved identity too.
        previous_topic = _discovery_topic(previous)
        if previous_topic and previous_topic in names:
            return "discovery_set_followup"
        if not _set_followup(previous):
            break
    return None


def preserve_discovery_scope(contract, history):
    execution = contract.execution
    if execution is None or execution.scope_decision.strategy != ScopeStrategy.EXACT_SCOPED:
        return contract
    reason = discovery_scope_reason(contract.original_query, history, execution.soft_scope.resolved_resources)
    if not reason:
        return contract
    # Run the SAME hard/resource security validation before semantic broadening.
    # Unknown, empty, invalid, ambiguous and incomplete states cannot be promoted.
    proven = choose_scope_strategy(execution.hard_scope, execution.soft_scope)
    if proven.strategy != ScopeStrategy.EXACT_SCOPED:
        return contract
    decision = choose_scope_strategy(execution.hard_scope, execution.soft_scope, broad_request=True)
    decision = replace(decision, reason=reason)
    contract.execution = replace(execution, scope_decision=decision)
    contract.permitted_document_ids = None  # ALL of execution.hard_scope, never global access.
    contract.scope_mode = "catalog"
    contract.entity_resolution.update(scope_policy=reason)
    return contract
