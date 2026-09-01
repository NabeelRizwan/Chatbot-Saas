"""Domain-neutral conversational query and structured-evidence contracts.

This module deliberately contains no tenant names, product names, or expected
answers.  It turns a natural-language turn plus tenant-scoped document
identities into an explicit subject/field contract that retrieval can satisfy.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import unquote, urlsplit


FIELD_ONTOLOGY: dict[str, tuple[str, ...]] = {
    "price": (
        r"\b(?:price|prices|pricing|cost|costs|rate|rates|fee|fees|tuition|rent)\b",
        r"\bhow much\b",
        r"\b(?:cheap|cheaper|cheapest|affordable)\b",
    ),
    "ingredients": (
        r"\b(?:ingredient|ingredients|composition|components|materials)\b",
        r"\bwhat(?:'s| is) in\b",
        r"\b(?:contain|contains|contained|made of|composed of)\b",
    ),
    "directions": (
        r"\b(?:how (?:do i|should i|to) (?:use|take|apply|install|set up)|how to use|usage|use directions|directions|dosage|dose|serving|setup|instructions?)\b",
    ),
    "form": (r"\b(?:product form|form|format|variant|type)\b",),
    "benefits": (r"\b(?:benefit|benefits|purpose|purposes|supports?|used for)\b",),
    "results_timeframe": (
        r"\b(?:how soon|when (?:will|should|can)|timeframe|time frame|expected results?|see results?|notice results?|results? timeline)\b",
        r"\bhow long (?:until|before)\b",
    ),
    "features": (
        r"\b(?:feature|features|capabilities|what is included|what does .{0,60} include|inclusions?|include sso|includes? sso|sso)\b",
    ),
    "specifications": (r"\b(?:specification|specifications|specs|technical details|attributes)\b",),
    "amenities": (r"\b(?:amenity|amenities|facilities)\b",),
    "availability": (r"\b(?:availability|available|in stock|stock status|sold out)\b",),
    "duration": (r"\b(?:duration|length|term|how long (?:is|does|will)|weeks?|months?|years?)\b",),
    "policy": (r"\b(?:policy|policies|terms|conditions|cancellation)\b",),
    "eligibility": (r"\b(?:eligibility|eligible|requirements?|prerequisites?|qualify)\b",),
    "shipping": (r"\b(?:shipping|delivery|dispatch)\b",),
    "returns": (r"\b(?:return|returns|refund|refunds|exchange)\b",),
    "check_in": (r"\b(?:check[ -]?in|checkout|check[ -]?out)\b",),
    "syllabus": (r"\b(?:syllabus|curriculum|modules?|topics? covered)\b",),
    "flavor": (r"\b(?:flavor|flavour|taste)\b",),
    "link": (r"\b(?:direct (?:product )?link|product link|url|website link|page link)\b",),
    "reviews": (r"\b(?:review|reviews|ratings?|customers? say|testimonials?|feedback)\b",),
    "brand": (r"\bbrand\b",),
    "sku": (r"\b(?:sku|product code|item code)\b",),
    "rating": (r"\b(?:rating|ratings|stars?)\b",),
}


FIELD_EVIDENCE_PATTERNS: dict[str, re.Pattern[str]] = {
    "price": re.compile(
        r"(?:\$|₹|€|£|¥)\s*\d|\b(?:USD|EUR|GBP|INR|JPY)\s*\d|"
        r"\b(?:price|pricing|cost|rate|fee|tuition|rent)s?\b",
        re.I,
    ),
    "ingredients": re.compile(r"\b(?:ingredient|composition|component|material)s?\b", re.I),
    "directions": re.compile(
        r"\b(?:how to use|directions?|usage|dosage|dose|serving|instructions?|"
        r"take \w+|mix \w+|apply \w+|setup)\b",
        re.I,
    ),
    "form": re.compile(r"\b(?:form|format|variant|capsules?|softgels?|gumm(?:y|ies)|powder|liquid|tablets?|room|suite|plan|course)\b", re.I),
    "benefits": re.compile(r"\b(?:benefits?|purpose|supports?|used for|designed to)\b", re.I),
    "results_timeframe": re.compile(
        r"\b(?:how soon|when (?:will|should|can).{0,40}(?:results?|notice)|"
        r"results?.{0,80}(?:days?|weeks?|months?|timeframe|consistent (?:use|usage))|"
        r"(?:days?|weeks?|months?).{0,80}(?:results?|notice|consistent (?:use|usage)))\b",
        re.I | re.S,
    ),
    "features": re.compile(r"\b(?:features?|includes?|included|capabilities|sso|single sign-on)\b", re.I),
    "specifications": re.compile(r"\b(?:specifications?|specs|technical details|attributes)\b", re.I),
    "amenities": re.compile(r"\b(?:amenities|facilities|wifi|breakfast|parking|pool)\b", re.I),
    "availability": re.compile(r"\b(?:availability|available|in stock|sold out|vacancies)\b", re.I),
    "duration": re.compile(r"\b(?:duration|length|term|days?|weeks?|months?|years?|hours?)\b", re.I),
    "policy": re.compile(r"\b(?:policy|policies|terms|conditions|cancellation)\b", re.I),
    "eligibility": re.compile(r"\b(?:eligibility|eligible|requirements?|prerequisites?|qualify)\b", re.I),
    "shipping": re.compile(r"\b(?:shipping|delivery|dispatch|business days?)\b", re.I),
    "returns": re.compile(r"\b(?:returns?|refunds?|exchange|money-back)\b", re.I),
    "check_in": re.compile(r"\b(?:check[ -]?in|check[ -]?out|arrival|departure)\b", re.I),
    "syllabus": re.compile(r"\b(?:syllabus|curriculum|modules?|topics? covered)\b", re.I),
    "flavor": re.compile(r"\b(?:flavou?r|taste)\b", re.I),
    "link": re.compile(r"https?://|\b(?:url|link|page)\b", re.I),
    "reviews": re.compile(r"\b(?:reviews?|ratings?|verified reviewer|testimonials?|feedback)\b", re.I),
    "brand": re.compile(r"\bbrand\b", re.I),
    "sku": re.compile(r"\b(?:sku|product code|item code)\b", re.I),
    "rating": re.compile(r"\b(?:rating|ratings|stars?)\b", re.I),
}


STRUCTURED_FIELD_KEYS: dict[str, tuple[str, ...]] = {
    "price": (
        "price", "sale_price", "saleprice", "regular_price", "regularprice",
        "list_price", "listprice", "og:price:amount", "product:price:amount",
        "offers.price", "offer.price", "lowprice", "highprice",
    ),
    "availability": ("availability", "offers.availability", "stock", "stockstatus"),
    "brand": ("brand", "brand.name"),
    "sku": ("sku", "mpn", "productid", "product_id"),
    "rating": ("rating", "ratingvalue", "aggregaterating.ratingvalue"),
    "name": ("name", "product.name", "og:title", "title", "page_title"),
}


PRICE_CURRENCY_KEYS = (
    "pricecurrency", "price_currency", "currency", "og:price:currency",
    "product:price:currency", "offers.pricecurrency", "offer.pricecurrency",
)


REFERENCE_PATTERN = re.compile(
    r"\b(?:it|its|this|that|this one|that one|they|them|these|those|"
    r"the first one|the second one|the cheaper one|the powder|the plan|"
    r"the product|the room|the course|the service|the package)\b",
    re.I,
)


GENERIC_CATALOG_WORDS = {
    "what", "which", "are", "is", "all", "the", "a", "an", "do", "does",
    "you", "we", "have", "offer", "sell", "provide", "stock", "carry",
    "available", "in", "this", "your", "catalog", "products", "product",
    "items", "item", "services", "service", "plans", "plan", "options",
    "option", "courses", "course", "rooms", "room", "packages", "package",
    "offerings", "offering", "show", "list", "give", "me",
}


@dataclass
class StructuredEvidence:
    field: str
    display_value: str
    raw_value: Any
    normalized_value: str | None
    currency: str | None
    origin: str
    label: str
    confidence: float


@dataclass
class QueryContract:
    original_query: str
    normalized_query: str
    resolved_query: str
    intent: str
    mode: str
    requested_fields: list[str] = field(default_factory=list)
    include_constraints: list[str] = field(default_factory=list)
    exclude_constraints: list[str] = field(default_factory=list)
    comparison_entities: list[str] = field(default_factory=list)
    catalog_scope: list[str] = field(default_factory=list)
    conversation_references: list[str] = field(default_factory=list)
    resolved_subject: str | None = None
    subject_document_id: int | None = None
    subject_confidence: float = 0.0
    ambiguity_status: str = "clear"
    clarification_prompt: str | None = None

    @property
    def requires_clarification(self) -> bool:
        return self.ambiguity_status != "clear"

    def cache_fragment(self) -> str:
        payload = {
            "subject": self.resolved_subject,
            "document_id": self.subject_document_id,
            "fields": self.requested_fields,
            "include": self.include_constraints,
            "exclude": self.exclude_constraints,
            "comparison": self.comparison_entities,
            "catalog_scope": self.catalog_scope,
            "ambiguity": self.ambiguity_status,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def to_debug_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_text(value: str) -> str:
    text = re.sub(r"\s+", " ", (value or "").lower()).strip()
    replacements = {
        r"\bwht\b": "what",
        r"\bwat\b": "what",
        r"\bwhts\b": "what is",
        r"\bwhats\b": "what is",
        r"\bwilll\b": "will",
        r"\bingrediant(s?)\b": r"ingredient\1",
    }
    for pattern, replacement in replacements.items():
        text = re.sub(pattern, replacement, text)
    return text.strip(" \t\r\n?.!")


def extract_requested_fields(message: str) -> list[str]:
    text = normalize_text(message)
    return [
        field_name
        for field_name, patterns in FIELD_ONTOLOGY.items()
        if any(re.search(pattern, text, re.I) for pattern in patterns)
    ]


def _metadata_values(metadata: Mapping[str, Any], prefix: str = "") -> Iterable[tuple[str, Any]]:
    for key, value in metadata.items():
        key_text = str(key).strip()
        path = f"{prefix}.{key_text}" if prefix else key_text
        yield path, value
        if isinstance(value, Mapping):
            yield from _metadata_values(value, path)
        elif isinstance(value, list):
            for index, item in enumerate(value[:20]):
                item_path = f"{path}[{index}]"
                if isinstance(item, Mapping):
                    yield from _metadata_values(item, item_path)


def _canonical_key(path: str) -> str:
    return re.sub(r"\[\d+\]", "", path).lower().replace("_", "").replace("-", "")


def _path_matches(path: str, candidates: Sequence[str]) -> bool:
    canonical_path = _canonical_key(path)
    for candidate in candidates:
        canonical_candidate = _canonical_key(candidate)
        if canonical_path == canonical_candidate or canonical_path.endswith("." + canonical_candidate):
            return True
    return False


def _currency_symbol(currency: str | None) -> str:
    return {
        "USD": "$", "EUR": "€", "GBP": "£", "INR": "₹", "JPY": "¥",
    }.get((currency or "").upper(), "")


def _normalize_number(value: Any) -> str | None:
    raw = str(value).strip().replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", raw)
    if not match:
        return None
    try:
        number = Decimal(match.group(0))
    except InvalidOperation:
        return None
    return format(number.normalize(), "f")


def extract_structured_evidence(metadata: Mapping[str, Any] | None, requested_fields: Sequence[str]) -> list[StructuredEvidence]:
    if not isinstance(metadata, Mapping):
        return []
    flattened = list(_metadata_values(metadata))
    currency = next(
        (str(value).strip().upper() for path, value in flattened if _path_matches(path, PRICE_CURRENCY_KEYS) and value),
        None,
    )
    results: list[StructuredEvidence] = []
    seen: set[tuple[str, str, str]] = set()
    for field_name in requested_fields:
        keys = STRUCTURED_FIELD_KEYS.get(field_name, ())
        for path, value in flattened:
            if not keys or not _path_matches(path, keys) or value in (None, "", [], {}):
                continue
            if isinstance(value, (Mapping, list)):
                continue
            raw = str(value).strip()
            normalized_value = _normalize_number(value) if field_name in {"price", "rating"} else normalize_text(raw)
            if field_name == "price" and normalized_value is None:
                continue
            if field_name == "price":
                symbol = _currency_symbol(currency)
                display = raw
                if not re.search(r"(?:\$|₹|€|£|¥)|\b(?:USD|EUR|GBP|INR|JPY)\b", display, re.I):
                    display = f"{symbol}{raw}" if symbol else f"{raw} {currency or ''}".strip()
                elif currency and currency not in display.upper() and not symbol:
                    display = f"{display} {currency}"
            else:
                display = raw
            dedupe_key = (field_name, display.lower(), path.lower())
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            label = path.split(".")[-1].replace("_", " ").replace(":", " ").strip()
            results.append(
                StructuredEvidence(
                    field=field_name,
                    display_value=display,
                    raw_value=value,
                    normalized_value=normalized_value,
                    currency=currency if field_name == "price" else None,
                    origin=path,
                    label=label or field_name,
                    confidence=0.98 if field_name == "price" else 0.92,
                )
            )
    return results


def _document_values(document: Any) -> list[str]:
    metadata = getattr(document, "metadata_json", None) or {}
    values = [
        str(getattr(document, "title", "") or ""),
        str(getattr(document, "filename", "") or ""),
    ]
    for key in ("name", "product_name", "page_title", "title", "og:title", "ogTitle"):
        value = metadata.get(key) if isinstance(metadata, Mapping) else None
        if value:
            values.append(str(value))
    url = str(
        getattr(document, "canonical_url", None)
        or getattr(document, "source_url", None)
        or ""
    )
    if url:
        slug = unquote(urlsplit(url).path.rstrip("/").split("/")[-1]).replace("-", " ").replace("_", " ")
        if slug:
            values.append(slug)
    return list(dict.fromkeys(value.strip() for value in values if value and value.strip()))


def _identity_score(text: str, identity: str) -> float:
    text_norm = normalize_text(text)
    identity_norm = normalize_text(identity)
    if not text_norm or not identity_norm:
        return 0.0
    if re.search(rf"(?<!\w){re.escape(identity_norm)}(?!\w)", text_norm):
        return 1.0
    identity_tokens = set(re.findall(r"[a-z0-9]+", identity_norm))
    text_tokens = set(re.findall(r"[a-z0-9]+", text_norm))
    if not identity_tokens:
        return 0.0
    overlap = len(identity_tokens & text_tokens) / len(identity_tokens)
    return 0.82 * overlap if overlap >= 0.75 else 0.0


def match_document(text: str, documents: Sequence[Any]) -> tuple[Any | None, str | None, float]:
    best_document = None
    best_identity = None
    best_score = 0.0
    for document in documents:
        for identity in _document_values(document):
            score = _identity_score(text, identity)
            if score > best_score:
                best_document, best_identity, best_score = document, identity, score
    if best_score < 0.72:
        return None, None, 0.0
    display = str(getattr(best_document, "title", None) or getattr(best_document, "filename", None) or best_identity)
    return best_document, display, best_score


def _history_document_matches(history: Sequence[Mapping[str, Any]], documents: Sequence[Any]) -> list[tuple[Any, str, float]]:
    matches: list[tuple[Any, str, float]] = []
    seen: set[int] = set()
    user_items = [item for item in history if str(item.get("role", "")).lower() == "user"]
    assistant_items = [item for item in history if str(item.get("role", "")).lower() == "assistant"]
    for item in reversed(user_items):
        content = str(item.get("content", ""))
        per_turn: list[tuple[float, Any, str]] = []
        for document in documents:
            score = max((_identity_score(content, identity) for identity in _document_values(document)), default=0.0)
            if score >= 0.72:
                subject = str(getattr(document, "title", None) or getattr(document, "filename", None) or "")
                per_turn.append((score, document, subject))
        for score, document, subject in sorted(per_turn, key=lambda row: -row[0]):
            document_id = int(getattr(document, "id", 0) or 0)
            if document_id not in seen:
                matches.append((document, subject, score))
                seen.add(document_id)
    if not matches:
        for item in reversed(assistant_items[-2:]):
            content = str(item.get("content", ""))
            for document in documents:
                score = max((_identity_score(content, identity) for identity in _document_values(document)), default=0.0)
                document_id = int(getattr(document, "id", 0) or 0)
                if score >= 0.92 and document_id not in seen:
                    subject = str(getattr(document, "title", None) or getattr(document, "filename", None) or "")
                    matches.append((document, subject, score))
                    seen.add(document_id)
    return matches


def extract_catalog_scope(query: str) -> list[str]:
    text = normalize_text(query)
    tokens = [token for token in re.findall(r"[a-z0-9][a-z0-9'-]*", text) if token not in GENERIC_CATALOG_WORDS]
    return list(dict.fromkeys(tokens))[:8]


def _clarification_for(fields: Sequence[str]) -> str:
    field_name = fields[0] if fields else "information"
    noun = {
        "ingredients": "product or item",
        "price": "product, plan, room, course, or service",
        "amenities": "room or property",
        "syllabus": "course",
        "features": "product, plan, or service",
    }.get(field_name, "item")
    return f"Which {noun} would you like the {field_name.replace('_', ' ')} for?"


def build_query_contract(
    query: str,
    history: Sequence[Mapping[str, Any]] | None,
    documents: Sequence[Any],
    *,
    intent: str,
    mode: str,
    mode_params: Mapping[str, Any] | None = None,
) -> QueryContract:
    history = list(history or [])
    params = dict(mode_params or {})
    fields = extract_requested_fields(query)
    existing_fields = list(params.get("requested_fields") or [])
    fields = list(dict.fromkeys(existing_fields + fields))
    filters = params.get("filters") or {}
    generic_constraint_values = {
        "it", "its", "this", "that", "this one", "that one", "them", "those", "these",
    }
    include_constraints = [
        str(value) for value in (filters.get("include") or [])
        if normalize_text(str(value)) not in generic_constraint_values
    ]
    exclude_constraints = [
        str(value) for value in (filters.get("exclude") or [])
        if normalize_text(str(value)) not in generic_constraint_values
    ]
    if mode not in {"filter", "catalog", "comparison"}:
        include_constraints = []
        exclude_constraints = []
    comparison_entities = list(params.get("entities") or [])
    references = list(dict.fromkeys(match.group(0).lower() for match in REFERENCE_PATTERN.finditer(query)))

    direct_document, direct_subject, direct_score = match_document(query, documents)
    resolved_document = direct_document
    resolved_subject = direct_subject
    subject_confidence = direct_score

    history_matches = _history_document_matches(history, documents)
    if resolved_document is None and references and history_matches:
        ordinal = normalize_text(query)
        if "second one" in ordinal and len(history_matches) >= 2:
            resolved_document, resolved_subject, subject_confidence = history_matches[1]
        else:
            resolved_document, resolved_subject, subject_confidence = history_matches[0]
            subject_confidence = min(subject_confidence, 0.94)

    # A comparison follow-up such as "which one is cheaper?" intentionally
    # retains all recently named entities instead of pretending one is clear.
    if not comparison_entities and re.search(r"\b(?:which one|cheaper one|compare|between them)\b", query, re.I):
        comparison_entities = [subject for _doc, subject, _score in history_matches[:6] if subject]

    catalog_scope = extract_catalog_scope(query) if mode == "catalog" else []
    ambiguity_status = "clear"
    clarification_prompt = None
    generic_field_query = bool(fields) and (
        bool(re.search(r"^(?:what (?:are|is)|how much|how long|when|does|do)\b", normalize_text(query)))
        or bool(references)
    )
    explicit_subject_phrase = bool(re.search(r"\b(?:of|for|about)\s+[a-z0-9]", normalize_text(query)))
    named_unknown = explicit_subject_phrase and not references
    if (
        fields
        and resolved_document is None
        and not comparison_entities
        and mode not in {"catalog", "filter", "comparison", "policy"}
        and generic_field_query
        and not named_unknown
    ):
        ambiguity_status = "needs_subject_clarification"
        clarification_prompt = _clarification_for(fields)

    resolved_query = normalize_text(query)
    if resolved_subject and references:
        resolved_query = REFERENCE_PATTERN.sub(resolved_subject, resolved_query)
    elif resolved_subject and normalize_text(resolved_subject) not in resolved_query:
        resolved_query = f"{resolved_subject} {resolved_query}".strip()

    return QueryContract(
        original_query=query,
        normalized_query=normalize_text(query),
        resolved_query=resolved_query or query,
        intent=intent,
        mode=mode,
        requested_fields=fields,
        include_constraints=include_constraints,
        exclude_constraints=exclude_constraints,
        comparison_entities=comparison_entities,
        catalog_scope=catalog_scope,
        conversation_references=references,
        resolved_subject=resolved_subject,
        subject_document_id=int(getattr(resolved_document, "id", 0) or 0) or None,
        subject_confidence=subject_confidence,
        ambiguity_status=ambiguity_status,
        clarification_prompt=clarification_prompt,
    )
