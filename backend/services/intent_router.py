import re
from typing import Optional, Tuple, List

from services.query_contract import extract_requested_fields as extract_contract_fields


# Intent Constants
INTENT_GREETING = "greeting"
INTENT_FAREWELL = "farewell"
INTENT_GRATITUDE = "gratitude"
INTENT_IDENTITY = "identity"
INTENT_SMALL_TALK = "small_talk"
INTENT_SUMMARIZE_PREVIOUS = "summarize_previous"
INTENT_SIMPLIFY_PREVIOUS = "simplify_previous"
INTENT_REPHRASE_CONTINUE = "rephrase_continue"
INTENT_PRONOUN_FOLLOWUP = "pronoun_followup"
INTENT_CATALOG_LIST = "catalog_list"
INTENT_COMPARISON = "comparison"
INTENT_PURCHASE = "purchase_intent"
INTENT_FILTER = "filter_query"
INTENT_POLICY = "policy_query"
INTENT_ENTITY_DEEP = "entity_deep"
INTENT_KNOWLEDGE_QUERY = "knowledge_query"

# Retrieval Modes
RETRIEVAL_MODE_FACTUAL = "factual"
RETRIEVAL_MODE_ENTITY = "entity"
RETRIEVAL_MODE_CATALOG = "catalog"
RETRIEVAL_MODE_FILTER = "filter"
RETRIEVAL_MODE_COMPARISON = "comparison"
RETRIEVAL_MODE_POLICY = "policy"
RETRIEVAL_MODE_PURCHASE = "purchase"


GREETING_PATTERNS = {
    "hi", "hello", "hey", "heya", "hiya", "yo", "sup", "good morning",
    "good afternoon", "good evening", "greetings", "howdy", "welcome"
}

FAREWELL_PATTERNS = {
    "bye", "goodbye", "see ya", "see you", "talk to you later", "catch you later",
    "have a good day", "have a nice day", "good night", "cya"
}

GRATITUDE_PATTERNS = {
    "thanks", "thank you", "thx", "thank you so much", "thanks a lot",
    "appreciate it", "awesome thanks", "great thanks", "perfect thanks",
    "thank you for your help", "that helps", "much appreciated"
}

IDENTITY_PATTERNS = (
    r"\bwho are you\b",
    r"\bwhat are you\b",
    r"\bwhat can you do\b",
    r"\bwho made you\b",
    r"\bwho created you\b",
    r"\bwhat is your name\b",
    r"\bwhat is your role\b",
    r"\bhow can you help\b",
)

SMALL_TALK_PATTERNS = {
    "how are you", "how are you?", "how is it going", "how's it going",
    "how are things", "what's up", "ok", "okay", "cool", "nice", "great",
    "sounds good", "got it", "understood", "nice to meet you"
}

SUMMARIZE_PATTERNS = (
    r"\bsummarize( this| that)?\b",
    r"\btldr\b",
    r"\bmake it shorter\b",
    r"\bshort version\b",
    r"\bgive me a summary\b",
    r"\bcan you summarize\b",
    r"\bin brief\b",
    r"\bkey points\b",
)

SIMPLIFY_PATTERNS = (
    r"\bexplain (it |this |that )?simply\b",
    r"\bexplain like i('?m| am) 5\b",
    r"\beli5\b",
    r"\bsimplify (this|that|it)\b",
    r"\bin simple terms\b",
    r"\bmake it simple\b",
    r"\beasier to understand\b",
)

CONTINUE_PATTERNS = (
    r"\btell me more\b",
    r"\bexplain more\b",
    r"\bcontinue\b",
    r"\belaborate\b",
    r"\bgo on\b",
    r"\bmore details\b",
    r"\bwhat else\b",
    r"\bkeep going\b",
    r"\bcan you expand\b",
)

PRONOUN_PATTERNS = (
    r"\b(it|this|that|them|those|these|the above|previous answer|earlier|its)\b",
)

CATALOG_LIST_PATTERNS = (
    # Natural catalog questions often put a qualified noun before "do you
    # have" (for example, "what eco-friendly plans do you have in this
    # catalog?").  Keep the qualifier domain-agnostic and allow punctuation.
    r"\bwhat\b.{0,120}\b(products|items|services|plans|options|offerings|models|courses|treatments|packages|solutions)\b.{0,80}\bdo you\b.{0,20}\b(have|offer|sell|provide|stock|carry)\b",
    r"\bwhat ([\w\s]+? )?(products|items|models|services|plans|options|categories|types|courses|degrees|programs|majors|certificates|treatments|specialties|amenities|listings|properties|units|apartments|rooms|dishes|meals|menu|tours|excursions|itineraries|modules|features|packages|solutions|tiers|offerings)( (and|or) ([\w\s]+? )?(products|items|models|services|plans|options|categories|types|courses|degrees|programs|majors|certificates|treatments|specialties|amenities|listings|properties|units|apartments|rooms|dishes|meals|menu|tours|excursions|itineraries|modules|features|packages|solutions|tiers|offerings|[\w]+))? (do you|are) (have|sell|offer|provide|serve|available|there|present)\b",
    r"\bwhat ([\w\s]+? )?(categories|products|services|plans|models|options|courses|degrees|programs|majors|treatments|dishes|tours|listings|units|solutions|offerings)( (and|or) ([\w\s]+? )?(categories|products|services|plans|models|options|courses|degrees|programs|majors|treatments|dishes|tours|listings|units|solutions|offerings|[\w]+))? (are there|do you have|do you offer|are available|do you provide|do you serve)\b",
    r"\b(list|show|give me) (all|available|the) (products|items|models|laptops|phones|services|plans|categories|options|courses|degrees|programs|majors|treatments|dishes|menu|tours|listings|units|solutions|packages|tiers|offerings)\b",
    r"\bwhat (are|is) (all |the )?(available |different )?(products|categories|plans|services|models|options|courses|degrees|programs|majors|treatments|dishes|menu|tours|listings|units|offerings|solutions|packages|practice areas)\b",
    r"\bwhat types of (products|services|treatments|courses|degrees|programs|dishes|tours|listings|solutions) does the company (sell|offer|provide|serve|have)\b",
    r"\bwhich (products|models|laptops|phones|plans|services|courses|degrees|programs|treatments|dishes|tours|units|listings) (do you have|are available|do you offer|do you serve)\b",
    r"\bwhat do you (sell|offer|provide|specialize in|teach|treat|serve)\b",
    r"\bwhat are your (services|products|offerings|plans|treatments|courses|degrees|programs|dishes|menu|tours|listings|specialties|solutions|practice areas|packages|tiers)\b",
    # Domain-agnostic catalog phrasing.  The subject is intentionally not an
    # allow-list: a tenant may sell wardrobes, instruments, legal packages, or
    # any other offering that this module has never seen before.
    r"\bwhat (?:are )?(?:all|other|available|different) ([a-z0-9][\w'-]*(?:\s+[a-z0-9][\w'-]*){0,5}) (?:do you|does (?:the|this) (?:company|business)|are) (?:have|sell|offer|provide|stock|carry|available)\b",
    r"\b(?:list|show|name|give me) (?:all |the |available |other )?(?:items|options|choices|types|kinds|models|products|services|offerings)?(?:\s*(?:you|we|the (?:company|business))?\s*(?:have|offer|sell|provide|stock|carry))?(?:\s+(?:for|in|under|from)\s+.+)?$",
    r"\b(?:what|which) (?:other )?(?:types|kinds|options|ones|choices)(?:\s+of\s+.+)?(?:\s+(?:do you|are|does (?:the|this) (?:company|business))\s+(?:have|offer|sell|provide|available))?\b",
)

FILTER_PATTERNS = (
    r"\bwhich\b.{0,80}\b(products|items|models|plans|services|options|variants|courses|treatments|dishes|tours|units|listings|solutions|offerings)\b.{0,100}\b(are|have|support|include|contain|feature|provide|presented)\b",
    r"\bwhich ([\w\s]+? )?(products|items|models|plans|services|laptops|phones|options|variants|courses|degrees|treatments|dishes|meals|tours|units|listings|apartments|solutions|offerings)( (on|in|of) (your|the) (menu|catalog|inventory|website|store|firm|building|property))? (support|have|feature|include|offer|cost|serve|contain|are under|are over|are priced|are available in|use|run|require|cover|provide|are)\b",
    r"\bwhich (of your|of the) (products|laptops|phones|plans|models|items|services|courses|treatments|dishes|meals|tours|units|listings) (have|are|support|include|cost|require|serve|contain|feature)\b",
    r"\bwhich (ones|models|items|options|plans|services|courses|treatments|dishes|meals|tours|units|listings) (have|are|cost|support|include|require|serve|contain|feature)\b",
    r"\b(show|list|find) (all )?(products|items|models|laptops|phones|plans|services|courses|treatments|dishes|meals|tours|units|listings|apartments|properties|rooms) (that|with|under|over|having|supporting|requiring|offering|containing|serving)\b",
)

COMPARISON_PATTERNS = (
    r"\bcompare (.+) (and|with|vs|versus) (.+)\b",
    r"\bwhat('?s| is) the difference between (.+) and (.+)\b",
    r"\bwhich (is|one is) better,? (.+) or (.+)\b",
    r"\b(.+) vs\.? (.+)\b",
)

PURCHASE_PATTERNS = (
    r"\b(i want to|where can i|how (can|do) i|can i) (buy|purchase|order|checkout|get|book|reserve|schedule|enroll in|sign up for|register for|subscribe to|apply for|apply to|tour|schedule a tour|request a quote|get a quote) (.+)?\b",
    r"\b(take me to|link to|where is the) (checkout|cart|purchase|buy|product page|order page|booking page|registration page|enrollment page|sign up page|reservation page|tour page)\b",
    r"\bwhere (can i|to) (buy|order|purchase|book|reserve|schedule|enroll|register|subscribe|tour)\b",
    r"\bhow to (buy|order|purchase|book|reserve|schedule|enroll|register|subscribe|tour)\b",
    r"\b(how do i|where can i) (reserve a table|book a table|book an appointment|schedule an appointment|book a consultation|schedule a consultation|schedule a tour|book a tour)\b",
)

POLICY_PATTERNS = (
    r"\b(return|refund|shipping|warranty|cancellation|privacy|terms|delivery|guarantee|exchange|replacement|appointment|cancellation|prerequisite|deposit|lease) (policy|rules|process|period|time|duration|guarantee|terms|requirements)\b",
    r"\bhow (do|does) (returns|refunds|shipping|delivery|cancellation|appointments|reservations|deposits) work\b",
    r"\bhow long does (shipping|delivery) take\b",
    r"\bwhat is (your|the) (return|refund|warranty|shipping|cancellation|privacy|deposit) policy\b",
    r"\bdo you (offer|have) (?:a )?(refunds|returns|free shipping|warranty|guarantee)\b",
)

ENTITY_DEEP_PATTERNS = (
    r"\btell me (everything |all )?about (.+)\b",
    r"\bwhat (features|specifications|specs|details|options|modules|treatments|ingredients|allergens|amenities|syllabus|curriculum|prerequisites) does (.+) have\b",
    r"\bgive me (a |an )?(overview|summary|breakdown|deep dive) (of|on|for) (.+)\b",
    r"\beverything about (.+)\b",
    r"\ball details (about|on|for) (.+)\b",
)

RAG_INTENT_TERMS = {
    "account", "billing", "cancel", "company", "contact", "delivery", "docs",
    "documentation", "feature", "features", "guarantee", "integration", "login",
    "order", "policy", "price", "pricing", "product", "refund", "return",
    "service", "shipping", "support", "terms", "warranty", "how to", "where is",
    "can i", "do you offer", "what is", "how do", "specifications", "specs",
    "battery", "ram", "storage", "display", "screen", "processor", "chip",
    "camera", "compare", "categories", "category", "plans", "plan", "cost", "buy",
    "course", "courses", "degree", "degrees", "program", "programs", "major", "majors",
    "certificate", "certificates", "treatment", "treatments", "specialty",
    "specialties", "doctor", "dentist", "tuition", "prerequisite", "enroll", "book",
    "appointment", "schedule", "syllabus", "solution", "solutions", "package", "tier",
    "module", "modules", "amenity", "amenities", "listing", "listings", "property",
    "unit", "units", "apartment", "apartments", "condo", "sqft", "square feet",
    "bedroom", "bath", "deposit", "rent", "lease", "tour", "reserve", "reservation",
    "menu", "dish", "dishes", "appetizer", "entree", "dessert", "allergen", "gluten-free",
    "vegan", "vegetarian", "excursion", "itinerary", "tours", "attorney", "lawyer", "counsel"
}

COMMON_TYPOS = {
    r"\bwht\b": "what",
    r"\bwat\b": "what",
    r"\bwhts\b": "what is",
    r"\byoiu\b": "you",
    r"\bu\b": "you",
    r"\bahve\b": "have",
    r"\bhav\b": "have",
    r"\bur\b": "your",
    r"\bproduts\b": "products",
    r"\bprodcut\b": "product",
    r"\bprodcts\b": "products",
    r"\bpolcy\b": "policy",
    r"\bpolici\b": "policy",
    r"\brefun\b": "refund",
    r"\bshippin\b": "shipping",
    r"\bplz\b": "please",
    r"\bpls\b": "please",
    r"\babt\b": "about",
}


def _normalize(message: str) -> str:
    text = re.sub(r"\s+", " ", message.lower()).strip()
    for pattern, repl in COMMON_TYPOS.items():
        text = re.sub(pattern, repl, text)
    return re.sub(r"^[^\w]+|[^\w?!.]+$", "", text)


def is_small_talk(message: str) -> bool:
    text = _normalize(message)
    if text in GREETING_PATTERNS or text in SMALL_TALK_PATTERNS or text in GRATITUDE_PATTERNS or text in FAREWELL_PATTERNS:
        return True
    if any(re.search(p, text) for p in IDENTITY_PATTERNS):
        return True
    words = text.split()
    return len(words) <= 3 and any(text.startswith(g) for g in ("hi", "hello", "hey", "thanks", "bye"))


def is_general_conversation(message: str) -> bool:
    text = _normalize(message)
    if is_small_talk(text):
        return True
    if any(re.search(p, text) for p in (SUMMARIZE_PATTERNS + SIMPLIFY_PATTERNS + CONTINUE_PATTERNS)):
        return True
    general_patterns = (
        r"\btell me (a )?joke\b",
        r"\bmake me laugh\b",
        r"\bwrite (a )?(poem|story|email|message)\b",
        r"\bbrainstorm\b",
    )
    if any(re.search(pattern, text) for pattern in general_patterns):
        business_cues = {"your", "you", "company", "product", "service", "pricing", "policy", "refund"}
        return not any(cue in text.split() for cue in business_cues)
    return False


def is_catalog_or_list_query(message: str) -> bool:
    text = _normalize(message)
    return any(re.search(p, text) for p in CATALOG_LIST_PATTERNS)


def _recent_user_topic(history: list[dict] | None) -> str:
    """Return a conservative topic from user turns only.

    Assistant prose commonly begins with words such as "Yes" and contains
    prices/capitalized product names.  Treating those tokens as the entity made
    follow-ups resolve to strings such as "Yes Rs".  User turns are the stable
    source of conversational intent; retrieval can discover the concrete
    entities afterwards.
    """
    if not history:
        return ""

    wrappers = (
        r"^(?:well\s+)?(?:what|which)\s+(?:are\s+)?(?:about\s+|all\s+|other\s+)?",
        r"^(?:well\s+)?(?:do|does|did)\s+(?:you|we|the\s+(?:company|business))\s+(?:have|offer|sell|provide|stock|carry)\s+",
        r"^(?:tell|show|give)\s+(?:me\s+)?(?:all\s+|more\s+)?(?:about\s+)?",
        r"^(?:list|name)\s+(?:all\s+|the\s+|available\s+)?",
    )
    trailing = re.compile(
        r"\s+(?:do you|does (?:the|this) (?:company|business)|are)\s+"
        r"(?:have|offer|sell|provide|stock|carry|available)\??$"
    )

    for item in reversed(history):
        if str(item.get("role", "")).strip().lower() != "user":
            continue
        original = str(item.get("content", "")).strip()
        if not original or is_small_talk(original):
            continue
        topic = original.strip(" \t\r\n?.!")
        for pattern in wrappers:
            topic = re.sub(pattern, "", topic, flags=re.IGNORECASE).strip()
        topic = trailing.sub("", topic).strip(" \t\r\n?.!")
        topic = re.sub(r"^(?:items|options|types|kinds)\s+(?:for|of)\s+", "", topic, flags=re.IGNORECASE)
        if topic and not any(re.fullmatch(p, _normalize(topic)) for p in CONTINUE_PATTERNS):
            return topic
    return ""


def is_filter_query(message: str) -> Tuple[bool, str]:
    text = _normalize(message)
    for p in FILTER_PATTERNS:
        if re.search(p, text):
            return True, text
    return False, ""


def is_purchase_intent(message: str) -> bool:
    text = _normalize(message)
    return any(re.search(p, text) for p in PURCHASE_PATTERNS)


def is_policy_query(message: str) -> bool:
    text = _normalize(message)
    return any(re.search(p, text) for p in POLICY_PATTERNS)


def is_entity_broad_query(message: str) -> Tuple[bool, str]:
    text = _normalize(message)
    for p in ENTITY_DEEP_PATTERNS:
        m = re.search(p, text)
        if m:
            groups = [g.strip() for g in m.groups() if g and g.strip() not in ("everything", "all", "a", "an", "overview", "summary", "breakdown", "deep dive")]
            entity = groups[-1] if groups else ""
            return True, entity
    return False, ""


def is_comparison_query(message: str) -> Tuple[bool, List[str]]:
    text = _normalize(message)
    if re.search(r"\bcompare\s+(?:the\s+)?matching\s+(?:options|items|products)\b", text):
        return False, []
    # Parse explicit comma/Oxford-comma lists only from the comparison clause,
    # not from the requested output fields that commonly follow it.
    direct = re.match(r"^compare\s+(.+?)(?:[.!?](?:\s|$)|$)", text)
    if direct:
        subject = direct.group(1).strip(" ,")
        parts = [
            part.strip(" ,")
            for part in re.split(r"\s*,\s*(?:and\s+)?|\s+(?:and|with|vs\.?|versus)\s+", subject)
            if part.strip(" ,")
        ]
        generic = {
            "the matching options", "matching options", "the options", "options",
            "the products", "products", "the items", "items", "them", "these",
        }
        parts = [part for part in parts if part not in generic and 1 <= len(part.split()) <= 12]
        if len(parts) >= 2:
            return True, list(dict.fromkeys(parts))

    for p in COMPARISON_PATTERNS:
        m = re.search(p, text)
        if m:
            groups = [g.strip() for g in m.groups() if g and g.strip() not in ("and", "with", "vs", "versus", "or")]
            groups = [g for g in groups if g not in {"the matching options", "matching options", "the options", "options"}]
            if len(groups) >= 2 and all(len(group.split()) <= 12 for group in groups):
                return True, groups
    return False, []


REQUESTED_FIELD_PATTERNS = {
    "price": r"\b(price|prices|pricing|cost|costs|rate|rates|fee|fees)\b",
    "ingredients": r"\b(ingredient|ingredients|composition|components|materials)\b",
    "directions": r"\b(how (?:the\s+\w+\s+)?(?:page\s+)?(?:says\s+)?to use|how to use|usage|use directions|directions|dosage|dose|serving|setup|instructions?)\b",
    "form": r"\b(product form|form|format|variant|type)\b",
    "benefits": r"\b(benefit|benefits|purpose|purposes|supports?|capabilities|features)\b",
    "flavor": r"\b(flavor|flavour|taste)\b",
    "link": r"\b(direct (?:product )?link|product link|url|website link|page link)\b",
    "reviews": r"\b(review|reviews|ratings?|customers? say|testimonials?|feedback)\b",
    "duration": r"\b(duration|how long|length|term)\b",
}


def extract_requested_fields(message: str) -> List[str]:
    """Return canonical, domain-neutral output fields explicitly requested."""
    return extract_contract_fields(message)


def _singular_attribute(value: str) -> str:
    value = value.strip(" ,.?\t\r\n").lower()
    if value.endswith("ies") and len(value) > 4:
        return value[:-3] + "y"
    if value.endswith("s") and not value.endswith("ss") and len(value) > 3:
        return value[:-1]
    return value


def extract_filter_attributes(message: str) -> dict[str, List[str]]:
    """Extract explicit include/exclude constraints without a domain allow-list.

    These are lexical evidence constraints, not facts.  They help retrieval
    locate the right documents; the answer still has to quote stored evidence.
    """
    text = _normalize(message)
    include: List[str] = []
    exclude: List[str] = []

    rather = re.search(r"\b(?:rather than|instead of)\s+([^?.;]+)", text)
    if rather:
        tail = re.split(r"\b(?:for|that|which|tell|show|include|with)\b", rather.group(1), maxsplit=1)[0]
        exclude.extend(re.split(r"\s*,\s*|\s+(?:or|and)\s+", tail))

    exclude.extend(re.findall(r"\bnon[-\s]([a-z0-9][\w-]*)", text))
    for match in re.finditer(r"\b(?:without|excluding|except)\s+([^,.;?]+)", text):
        exclude.extend(re.split(r"\s+(?:or|and)\s+", match.group(1)))

    # "are powders rather than ..." and equivalent constraints.
    attr_match = re.search(
        r"\b(?:are|is|with|having|featuring|supporting|containing)\s+"
        r"([a-z0-9][\w-]*(?:\s+[a-z0-9][\w-]*){0,3}?)(?=\s+(?:rather than|instead of)|[,.;?]|$)",
        text,
    )
    if attr_match:
        include.append(attr_match.group(1))

    def clean(values: List[str]) -> List[str]:
        result = []
        for value in values:
            normalized = re.sub(r"^(?:and|or)\s+", "", _singular_attribute(value))
            if normalized and normalized not in {"the", "a", "an", "option", "product", "item"}:
                result.append(normalized)
        return list(dict.fromkeys(result))

    return {"include": clean(include), "exclude": clean(exclude)}


def detect_retrieval_mode(query: str, history: list[dict] | None = None) -> Tuple[str, dict]:
    """
    Classifies the user query into a specialized Phase 9 retrieval mode with context parameters.
    """
    text = _normalize(query)
    query_analysis = {
        "requested_fields": extract_requested_fields(query),
        "filters": extract_filter_attributes(query),
    }

    # 1. Purchase intent
    if is_purchase_intent(query):
        return RETRIEVAL_MODE_PURCHASE, {
            "mode": RETRIEVAL_MODE_PURCHASE,
            "context_budget": 4000,
            "target_depth": 6,
            **query_analysis,
        }

    # 2. Comparison
    is_comp, entities = is_comparison_query(query)
    if is_comp:
        return RETRIEVAL_MODE_COMPARISON, {
            "mode": RETRIEVAL_MODE_COMPARISON,
            "entities": entities,
            "context_budget": 9500,
            "target_depth": 10,
            **query_analysis,
        }

    # 3. Catalog & List queries, including short contextual continuations after
    # a catalog turn ("which types?", "what other ones?", "show me more").
    previous_catalog = False
    if history:
        previous_user = next(
            (str(item.get("content", "")) for item in reversed(history)
             if str(item.get("role", "")).lower() == "user" and str(item.get("content", "")).strip()),
            "",
        )
        previous_catalog = bool(previous_user and is_catalog_or_list_query(previous_user))
    contextual_catalog = previous_catalog and bool(re.search(
        r"\b(which types|what types|what kinds|which ones|what other ones|other options|show me more|list more)\b",
        text,
    ))
    if is_catalog_or_list_query(query) or contextual_catalog:
        return RETRIEVAL_MODE_CATALOG, {
            "mode": RETRIEVAL_MODE_CATALOG,
            "context_budget": 12000,
            "target_depth": 16,
            **query_analysis,
        }

    # 4. Filter query across products.  Broad availability questions that also
    # match a permissive "which ... are" filter pattern are catalogs, so this is
    # intentionally evaluated after catalog recognition.
    is_filt, filt_text = is_filter_query(query)
    if is_filt:
        return RETRIEVAL_MODE_FILTER, {
            "mode": RETRIEVAL_MODE_FILTER,
            "filter_text": filt_text,
            "context_budget": 11000,
            "target_depth": 14,
            **query_analysis,
        }

    # 5. Entity deep queries ("Tell me about X", "Everything about X")
    is_ent_deep, ent_name = is_entity_broad_query(query)
    if is_ent_deep:
        return RETRIEVAL_MODE_ENTITY, {
            "mode": RETRIEVAL_MODE_ENTITY,
            "entity_name": ent_name,
            "context_budget": 8500,
            "target_depth": 10,
            **query_analysis,
        }

    # 6. Policy queries
    if is_policy_query(query):
        return RETRIEVAL_MODE_POLICY, {
            "mode": RETRIEVAL_MODE_POLICY,
            "context_budget": 6000,
            "target_depth": 6,
            **query_analysis,
        }

    # 7. Default Factual query
    return RETRIEVAL_MODE_FACTUAL, {
        "mode": RETRIEVAL_MODE_FACTUAL,
        "context_budget": 3500,
        "target_depth": 4,
        **query_analysis,
    }


def classify_intent(message: str, history: list[dict] | None = None) -> str:
    text = _normalize(message)
    if not text:
        return INTENT_SMALL_TALK

    # 1. Greetings
    if text in GREETING_PATTERNS or (len(text.split()) <= 2 and any(text.startswith(g) for g in ("hi", "hello", "hey", "greetings"))):
        return INTENT_GREETING

    # 2. Farewell
    if text in FAREWELL_PATTERNS or (len(text.split()) <= 3 and any(text.startswith(f) for f in ("bye", "goodbye", "cya"))):
        return INTENT_FAREWELL

    # 3. Gratitude
    if text in GRATITUDE_PATTERNS or any(phrase in text for phrase in ("thank you", "thanks", "appreciate it")):
        return INTENT_GRATITUDE

    # 4. Identity / Capabilities
    if any(re.search(p, text) for p in IDENTITY_PATTERNS):
        return INTENT_IDENTITY

    # 5. Small Talk / Acknowledgement
    if text in SMALL_TALK_PATTERNS:
        return INTENT_SMALL_TALK

    # 6. Summarization of previous context
    if any(re.search(p, text) for p in SUMMARIZE_PATTERNS):
        return INTENT_SUMMARIZE_PREVIOUS

    # 7. Simplification of previous context
    if any(re.search(p, text) for p in SIMPLIFY_PATTERNS):
        return INTENT_SIMPLIFY_PREVIOUS

    # 8. Rephrase / Continue
    if any(re.search(p, text) for p in CONTINUE_PATTERNS):
        return INTENT_REPHRASE_CONTINUE

    # 9. Purchase Intent
    if is_purchase_intent(message):
        return INTENT_PURCHASE

    # 10. Comparison
    is_comp, _ = is_comparison_query(message)
    if is_comp:
        return INTENT_COMPARISON

    # 11. Catalog / List Query
    if is_catalog_or_list_query(message):
        return INTENT_CATALOG_LIST

    # 12. Filter Query
    is_filt, _ = is_filter_query(message)
    if is_filt:
        return INTENT_FILTER

    # 13. Entity Deep Query
    is_ent_deep, _ = is_entity_broad_query(message)
    if is_ent_deep:
        return INTENT_ENTITY_DEEP

    # 14. Policy Query
    if is_policy_query(message):
        return INTENT_POLICY

    # 15. Pronoun / Contextual Follow-up
    if history and len(history) >= 2 and any(re.search(p, text) for p in PRONOUN_PATTERNS):
        return INTENT_PRONOUN_FOLLOWUP

    # 16. Otherwise knowledge query
    return INTENT_KNOWLEDGE_QUERY


def should_use_rag(message: str, history: list[dict] | None = None) -> bool:
    """Determine whether RAG vector retrieval is genuinely required."""
    intent = classify_intent(message, history=history)

    # Do NOT run RAG for greetings, farewells, gratitude, identity, small talk, or in-place transformations
    if intent in (
        INTENT_GREETING,
        INTENT_FAREWELL,
        INTENT_GRATITUDE,
        INTENT_IDENTITY,
        INTENT_SMALL_TALK,
        INTENT_SUMMARIZE_PREVIOUS,
        INTENT_SIMPLIFY_PREVIOUS,
    ):
        return False

    text = _normalize(message)
    words = set(re.findall(r"[a-z0-9']+", text))
    if words.intersection(RAG_INTENT_TERMS):
        return True
    if any(phrase in text for phrase in ("your ", "you offer", "do you", "can you help with", "how do i", "tell me about")):
        return True

    if intent in (
        INTENT_REPHRASE_CONTINUE,
        INTENT_PRONOUN_FOLLOWUP,
        INTENT_CATALOG_LIST,
        INTENT_COMPARISON,
        INTENT_PURCHASE,
        INTENT_FILTER,
        INTENT_POLICY,
        INTENT_ENTITY_DEEP,
    ):
        return True

    return len(words) > 5


def rewrite_query_for_retrieval(query: str, history: list[dict] | None = None) -> str:
    """Rewrite ambiguous follow-up queries ('tell me more', 'how much is it?') into standalone retrieval queries."""
    norm_q = _normalize(query)
    if not history:
        return norm_q or query

    # Find the most recent user turn that was substantive
    last_user_turn = None
    last_assistant_turn = None

    for item in reversed(history):
        role = str(item.get("role", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        if role == "user" and not last_user_turn and not is_small_talk(content):
            last_user_turn = content
        elif role == "assistant" and not last_assistant_turn:
            last_assistant_turn = content
        if last_user_turn and last_assistant_turn:
            break

    if not last_user_turn:
        return query

    intent = classify_intent(query, history=history)

    if intent == INTENT_REPHRASE_CONTINUE:
        return f"{last_user_turn} - elaborate in detail"

    # Resolve from user-authored turns only.  This avoids poisoning retrieval
    # with capitalized filler/prices from the assistant response.
    entity_context = _recent_user_topic(history) or last_user_turn

    norm_query = _normalize(query)
    if intent == INTENT_PRONOUN_FOLLOWUP or any(re.search(p, norm_query) for p in PRONOUN_PATTERNS):
        if intent in (INTENT_FILTER, INTENT_COMPARISON, INTENT_CATALOG_LIST):
            resolved_followup = re.sub(
                r"\b(its|it|this|that|them|those|these|the previous (?:product|item|option))\b",
                "the previously discussed items",
                norm_q,
                flags=re.IGNORECASE,
            )
            return f"{entity_context}. {resolved_followup}".strip()
        # Resolve 'its', 'it', 'this', 'that'
        resolved = re.sub(r"\b(its|it|this|that|them|those|these|the previous (?:product|item|option))\b", entity_context, norm_q, flags=re.IGNORECASE)
        if entity_context not in resolved:
            resolved = f"{entity_context} {resolved}"
        return resolved

    # Specific follow-up patterns like "what about the Ultra 15?" or "what about battery life?"
    if norm_query.startswith("what about") or norm_query.startswith("how about"):
        tail = re.sub(r"^(?:what|how) about\s+", "", norm_query).strip(" ?.!")
        # A proper-named previous topic generally means the tail is an
        # attribute ("Invisalign" -> "treatment duration").  A plural tail is
        # usually a deliberate category switch ("hallway storage" ->
        # "wardrobes") and should stand on its own.
        has_named_previous_topic = bool(re.search(r"\b[A-Z][a-zA-Z0-9'-]+", entity_context))
        if tail and (tail.endswith("s") or not has_named_previous_topic):
            return tail
        return f"{entity_context} {tail}".strip()

    if re.search(r"\b(which types|what types|what kinds|which ones|what other ones|other options|show me more|list more)\b", norm_query):
        return f"{entity_context} {norm_query}".strip()

    return norm_query or query


def detect_length_preference(message: str) -> Optional[str]:
    """Extract requested answer length preferences from the user's message."""
    text = _normalize(message)

    if any(p in text for p in ("in 1 sentence", "one sentence", "in a single sentence", "1 line", "one line")):
        return "one_sentence"
    if any(p in text for p in ("in 2 lines", "two lines", "2 lines", "very short", "tldr")):
        return "very_short"
    if any(p in text for p in ("short", "briefly", "in brief", "concise")):
        return "short"
    if any(p in text for p in ("detailed", "in detail", "comprehensive", "explain fully", "deep dive")):
        return "detailed"
    if any(p in text for p in ("bullet points", "bullets", "list format")):
        return "bullet_points"

    return None
