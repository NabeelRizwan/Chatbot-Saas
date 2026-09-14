"""Bounded surface grammar, not semantic rewriting or another search backend.

Design-study attribution: OPEN_SOURCE_ADAPTATION_NOTES_PHASE_3_2.md.
Original messages/spans survive; weaker forms cannot override explicit identity.
No DB, provider, token permutations, catalog scan, or synonym dictionary.
"""
from dataclasses import replace
import re

from services.resource_channels import ResourceProbe, ProbeVariant, MAX_PROBES
from services.resource_normalization import normalize_resource_text

PROBE_VERSION = "natural-probes-3.7.0"
MAX_VARIANTS = 4
MAX_INPUT = 8192
# Resource-type vocabulary is grammar, not an alias/name dictionary. Explicit
# authorized context can supply additional custom types without catalog scanning.
RESOURCE_TYPES = frozenset("product service plan program course form document location policy department pdf ebook page section guide appointment certificate permit brochure office branch contact faq".split())
# Only used in a LOWER-PRIORITY variant, never to alter an original identity.
FUNCTION_WORDS = frozenset("a an the your my our for of to".split())
SHORT_GENERIC = frozenset("ai hr pro pdf".split())
_VERBS = r"(?:show|send|find|tell|give|open|download|contact|look at)"
_TYPED_NEED = r"^(?:which|what)\s+(\w+)\s+(?:would|do)\s+i\s+need\s+if\s+i\s+(?:want|need)\s+both\s+"
_PREFIXES = (
    ("typed_concept_request", _TYPED_NEED),
    ("request_connector", rf"^(?:and|then)\s+(?=(?:please|{_VERBS})\b)"),
    ("focus_framing", r"^(?:only|mostly)\s+(?=(?:the|your|do|does)\b)"),
    ("politeness", r"^please\s+"),
    ("belief", r"^i think\s+"),
    ("looking", r"^i(?:\s+am|['’]m| was) looking for\s+"),
    ("called", r"^(?:(?:it|(?:the\s+)?\w+)\s+(?:is|was)\s+|something\s+)?called\s+"),
    ("question", r"^(?:where|what|which|how)\s+(?:is|are|can i|could i|do i)\s+"),
    ("auxiliary", r"^(?:(?:can|could|would|will) you|(?:do|does) (?:you(?: guys)?|your)|(?:should|can|could) i|(?:is|are) there)\s+"),
    ("request", rf"^{_VERBS}(?:\s+me)?(?:\s+about)?\s+"),
    ("offer", r"^(?:offer|provide|have)\s+"),
    ("comparison", r"^(?:compare|difference between|what is the difference between|either)\s+"),
    ("determiner", r"^(?:your|the|this|that|a|an)\s+"),
)


def singular_type(text, types=RESOURCE_TYPES):
    value = normalize_resource_text(text)
    if value in types:
        return value
    forms = [value[:-1]] if value.endswith("s") else []
    if value.endswith("ies"):
        forms.insert(0, value[:-3]+"y")
    return next((v for v in forms if v in types), "")


def informative_tokens(text):
    return {t for t in normalize_resource_text(text).split()
            if t not in FUNCTION_WORDS and t not in RESOURCE_TYPES and t not in SHORT_GENERIC
            and ((len(t) >= 3 and t.isalpha()) or any(c.isdigit() for c in t))}


def strip_request(span):
    """At most 12 anchored grammar steps; no global deletion of content nouns."""
    value = span.strip().strip("?.! ,;:")
    reasons = []
    value, count = re.subn(r"^(where|what|which|how)['’]s\b", r"\1 is", value, flags=re.I)
    if count:
        reasons.append("question_contraction")
    for _ in range(12):
        if "focus_framing" in reasons and re.match(r"^(?:do|does)\s+", value, re.I):
            value = re.sub(r"^(?:do|does)\s+", "", value, count=1, flags=re.I)
            reasons.append("elliptical_auxiliary")
            continue
        for reason, pattern in _PREFIXES:
            new, count = re.subn(pattern, "", value, count=1, flags=re.I)
            if count:
                value = new.strip()
                reasons.append(reason)
                break
        else:
            break
    if reasons:
        if "looking" in reasons:
            value = re.sub(r"^(?:someone|somebody|a team)\s+to\s+", "", value, count=1, flags=re.I)
            # A separate confirmation sentence is framing, not name text. Its
            # original remains in the explicit probe and original user query.
            value = re.split(r"[.!?]\s+(?:is|are|would|could|can|do|does)\b", value, maxsplit=1, flags=re.I)[0]
        if "called" in reasons:
            value=re.split(r"\s*[-—;?]\s*(?=(?:can|could|would|will) you\b)",value,maxsplit=1,flags=re.I)[0]
        value = re.sub(r"\s+(?:for me|please)$", "", value, flags=re.I)
        # Requested factual clauses are not part of the mentioned resource.
        value = re.split(r"\s+(?:and its|have|has|offer|offers|provide|provides)\b", value, maxsplit=1, flags=re.I)[0]
    return value.strip("?.! ,;:"), tuple(dict.fromkeys(reasons))


def _member(span, index, group, types):
    normalize_resource_text(span)  # reject overflow, never truncate an identity
    clean, transformations = strip_request(span)
    tokens = normalize_resource_text(clean).split()
    hint = singular_type(tokens[-1], types) if tokens else ""
    typed_request = re.match(_TYPED_NEED, span, re.I)
    if typed_request:
        hint = singular_type(typed_request.group(1), types)
    qualifier = re.fullmatch(r"(.+?)\s+for\s+(?:the\s+)?(.+)", clean, re.I)
    reordered = ""
    if qualifier:
        left,right = qualifier.groups()
        left_type = singular_type(left.split()[-1], types)
        if left_type:
            hint = left_type
            reordered = right+" "+left
    variants = [ProbeVariant(span, "explicit_user", 0)]
    if transformations and clean:
        variants.append(ProbeVariant(clean, "wrapper_stripped", 10, transformations))
    if reordered:
        variants.append(ProbeVariant(reordered, "qualified_object", 20, ("qualified_object_reordering",)))
    variation=re.fullmatch(r"(.+?)\s+(?:version|edition|option)\s+of\s+(?:this|that|the)\s+(\w+)",clean,re.I)
    if variation and singular_type(variation.group(2),types):
        hint=singular_type(variation.group(2),types)
        variants.append(ProbeVariant(variation.group(1)+" "+hint,"type_hinted",20,("typed_variation_phrase",)))
    reduced = " ".join(t for t in normalize_resource_text(clean).split() if t not in FUNCTION_WORDS)
    if reduced:
        variants.append(ProbeVariant(reduced, "function_reduced", 30, ("articles_possessives_prepositions",)))
    unique={}
    for variant in variants:
        unique.setdefault(normalize_resource_text(variant.text), variant)
    return ResourceProbe(span, original_span=span, probe_kind="comparison_member" if group else "entity",
        explicit_resource_type_hint=hint, comparison_group_id=group, comparison_member_index=index if group else None,
        variants=tuple(unique.values())[:MAX_VARIANTS])


def build_resource_probes(contract, state):
    from services.query_contract import split_exclusions, explicit_identity_candidate, current_turn_anchor, is_capability_discovery
    from services.semantic_scope import comparison_mentions, between_choice_span
    original=contract.original_query
    if len(original)>MAX_INPUT:
        raise ValueError("Natural query exceeds probe bound")
    positive,exclusions=split_exclusions(original)
    if not exclusions:
        positive=original.strip()  # Preserve grammatical punctuation/span when exclusion masking isn't needed.
    soft=contract.execution.soft_scope
    types=RESOURCE_TYPES | {normalize_resource_text(c.resource.resource_type) for c in soft.resource_candidates[:32]}
    anchor = current_turn_anchor(positive)
    if anchor and not soft.comparison_requested:
        p = _member(anchor, 0, "", types)
        return (replace(p, original_span=positive, reason_codes=("current_noun_anchor",)),)
    if is_capability_discovery(positive) and not soft.resolved_resources:
        return (ResourceProbe(positive, "full_query", original_span=positive, probe_kind="fallback",
                              reason_codes=("current_capability_discovery",)),)
    # Relation requests require structure that this identity catalog does not
    # encode. They may discover references, but may not resolve an invented tier.
    choice = between_choice_span(positive)
    relation = re.search(r"\b(?:between .+ and|comes? (?:before|after)|next tier|previous tier|cheapest|most expensive|higher|lower|closest equivalent|best)\b",positive,re.I)
    if relation and not choice and not re.search(r"\b(?:difference|compare|choose|decide)\b",positive,re.I):
        return (ResourceProbe(positive,"full_query",original_span=positive,probe_kind="fallback",
            relation_intent="structured_relation_required",reason_codes=("structured_relation_required",)),)
    members=soft.comparison_members
    if choice:
        members=comparison_mentions(positive,[c.resource.canonical_name for c in soft.resource_candidates[:32]])
    if len(members)>MAX_PROBES:
        raise ValueError("Natural comparison exceeds probe bound")
    if members:
        # The earlier safety parser may stop at an auxiliary ('have') before
        # seeing the resource. Reuse it on the separately stripped request;
        # never discard members or split a known canonical conjunction.
        from services.semantic_scope import comparison_mentions
        surface,_=strip_request(positive)
        if (re.search(r"\bcompare\b", positive, re.I)
                and not re.search(r"\bcompare\b", surface, re.I)):
            surface = 'compare ' + surface
        recovered=comparison_mentions(surface,[c.resource.canonical_name for c in soft.resource_candidates[:32]])
        if len(recovered)>=len(members):
            members=recovered
        probes=[_member(m,i,"current_comparison",types) for i,m in enumerate(members)]
        probes=[p if normalize_resource_text(p.text) in normalize_resource_text(positive) else
                replace(p, provenance="history_comparison", original_span=positive,
                        variants=tuple(replace(v,provenance="history_comparison") for v in p.variants))
                for p in probes]
        explicit={p.explicit_resource_type_hint for p in probes if p.explicit_resource_type_hint}
        if len(explicit)==1:
            shared=next(iter(explicit))
            for i,p in enumerate(probes):
                clean,why=strip_request(p.text)
                # Only peer-typed comparison ellipsis; One remains a normal name elsewhere.
                if not p.explicit_resource_type_hint and re.search(r"\s+one$",clean,re.I):
                    reduced=re.sub(r"\s+one$","",clean,flags=re.I)
                    base=ProbeVariant(reduced,"comparison_ellipsis",20,why+("peer_type_ellipsis",))
                    typed=ProbeVariant(reduced+" "+shared,"type_hinted",21,("peer_type_search_variant",))
                    probes[i]=replace(p,inherited_resource_type_hint=shared,variants=(p.variants[0],base,typed))
        return tuple(probes)
    clean,why=strip_request(positive)
    category=re.fullmatch(r"(?:what|which)\s+(.+?)\s+(?:do you (?:have|offer|provide)|are available)[?.!]*",positive,re.I)
    category_text=category.group(1) if category else re.sub(r"^all\s+","",clean,flags=re.I)
    kind=singular_type(category_text,types)
    # Open-ended persisted type labels: an explicit list question may propose
    # a plural type without consulting/scanning the catalog. SQL metadata proves
    # whether that category actually exists; a named exact entity still wins.
    if not kind and (category or re.match(r"^all\s+",clean,re.I)):
        words=normalize_resource_text(category_text).split()
        if 0<len(words)<=3 and words[-1].endswith("s") and not any(c.isdigit() for c in category_text):
            kind=normalize_resource_text(category_text)
    if kind and (category or why or category_text!=clean):
        return (ResourceProbe(category_text,"category",original_span=positive,probe_kind="category",
                              category_intent=True,explicit_resource_type_hint=kind,
                              variants=(ProbeVariant(category_text,"explicit_user",0,("entity_hypothesis",)),
                                        ProbeVariant(category_text,"category",40,("category_hypothesis",)))),)
    # Genuine typed/deictic reference only, never history over an explicit switch.
    if re.search(r"\bthe other one\b",positive,re.I):
        # A sole active item is not proof of which alternative 'other' means.
        return (ResourceProbe(positive,"full_query",original_span=positive,probe_kind="conversation_reference",
                              reason_codes=("conversation_alternative_unresolved",)),)
    reference=re.fullmatch(r"(?:(?:how much is|tell me about|what about)\s+)?(?:it|this|that)(?:\s+(one|\w+))?[?.!]*",positive,re.I)
    if reference and reference.group(1) and reference.group(1).casefold()!="one" and not singular_type(reference.group(1),types):
        reference=None
    active=state.get("active_subjects",())
    if reference and len(active)==1 and isinstance(active[0],dict) and active[0].get("name"):
        p=_member(active[0]["name"],0,"",types)
        return (replace(p,provenance="conversation_state",original_span=positive,probe_kind="conversation_reference",
                        variants=tuple(replace(v,provenance="conversation_state") for v in p.variants)),)
    if contract.conversation_references and contract.resolved_entities and not explicit_identity_candidate(positive):
        return tuple(ResourceProbe(e.name,"conversation_state",original_span=positive,probe_kind="conversation_reference")
                     for e in contract.resolved_entities[:MAX_PROBES])
    explicit=explicit_identity_candidate(positive)
    # Existing extractor is an additional high-confidence surface span, not the
    # sole string replacing the user's text. Preserve original fallback too.
    p=_member(positive,0,"",types)
    if explicit and not why and normalize_resource_text(explicit)!=normalize_resource_text(positive):
        variant=ProbeVariant(explicit,"wrapper_stripped",10,("existing_subject_grammar",))
        p=replace(p,variants=(p.variants[0],variant,*p.variants[1:])[:MAX_VARIANTS])
    return (p,)
