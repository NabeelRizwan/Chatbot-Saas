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
    r"which one|each(?: one)?|both(?: of them)?|these two|those two|"
    r"the first one|the second one|the cheaper one|the more expensive one|"
    r"the powder|the plan|the product|the room|the course|the service|the package)\b",
    re.I,
)

SINGULAR_REFERENCE_PATTERN = re.compile(
    r"\b(?:it|its|this|that|this one|that one)\b",
    re.I,
)

MULTI_ENTITY_CONTINUATION_PATTERN = re.compile(
    r"\b(?:which one|each(?: one)?|both(?: of them)?|these two|those two|"
    r"them|these|those|their|the first one|the second one|"
    r"the cheaper one|the more expensive one|between them|"
    r"compare (?:them|these|those)|how do i use each)\b",
    re.I,
)

SUBJECT_SWITCH_PATTERN = re.compile(
    r"\b(?:what about|how about|instead(?: of)?|now (?:for|about)|switch(?:ing)? to)\b",
    re.I,
)

CONTRACTION_FRAGMENT_PATTERN = re.compile(
    r"^['’`](?:s|re|ve|ll|d|m|t)$|^(?:s|re|ve|ll|d)$",
    re.I,
)

COMPARISON_OPERATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("cheaper", re.compile(r"\b(?:cheaper|cheapest|less expensive|lowest(?: of these)?|costs? less)\b", re.I)),
    ("more_expensive", re.compile(r"\b(?:more expensive|most expensive|higher(?: priced)?|highest(?: of these)?)\b", re.I)),
)

PRICE_ROLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("subscription", re.compile(r"subscribe(?:\s*&\s*save)?|subscription", re.I)),
    ("one_time", re.compile(r"one[ -]?time(?: purchase)?", re.I)),
    ("sale", re.compile(r"\bsale(?: price)?\b", re.I)),
    ("regular", re.compile(r"\b(?:regular|list)(?: price)?\b", re.I)),
    ("bundle_per_unit", re.compile(r"per[ -]?(?:bottle|unit|pack|item)|/\s*(?:bottle|unit|pack)", re.I)),
    ("bundle_total", re.compile(r"\bbundle\b|\d+[ -]?packs?\b|\d+[ -]?bottles?\b", re.I)),
    ("monthly", re.compile(r"\bmonthly\b|/\s*mo(?:nth)?\b", re.I)),
    ("annual", re.compile(r"\b(?:annual|yearly)\b|/\s*year\b", re.I)),
    ("primary", re.compile(r"\b(?:current price|priced at|starts? at|now)\b", re.I)),
)

COVERAGE_SUPPORTED = "SUPPORTED"
COVERAGE_ABSENT = "ABSENT_AFTER_ADEQUATE_SEARCH"
COVERAGE_UNCERTAIN = "UNCERTAIN"


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
    price_type: str | None = None


@dataclass
class ResolvedEntity:
    name: str
    document_id: int
    confidence: float


@dataclass
class PriceFact:
    value: str
    currency: str | None
    display: str
    price_type: str
    entity_name: str
    entity_document_id: int | None = None
    source: str = "text"
    confidence: float = 0.9

    def as_prompt_line(self) -> str:
        currency = f" {self.currency}" if self.currency else ""
        entity = self.entity_name or "Item"
        return f"- {entity} | {self.price_type} | {self.display}{currency}"


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
    resolved_entities: list[ResolvedEntity] = field(default_factory=list)
    comparison_operation: str | None = None
    ambiguity_status: str = "clear"
    clarification_prompt: str | None = None

    @property
    def requires_clarification(self) -> bool:
        return self.ambiguity_status != "clear"

    @property
    def is_multi_entity(self) -> bool:
        return len(self.resolved_entities) >= 2 or (
            self.mode == "comparison" and len(self.explicit_document_ids()) >= 2
        )

    def explicit_document_ids(self) -> list[int]:
        ids = [entity.document_id for entity in self.resolved_entities if entity.document_id]
        if not ids and self.subject_document_id:
            ids = [self.subject_document_id]
        return list(dict.fromkeys(ids))

    def cache_fragment(self) -> str:
        payload = {
            "subject": self.resolved_subject,
            "document_id": self.subject_document_id,
            "entities": [
                {"name": entity.name, "document_id": entity.document_id}
                for entity in self.resolved_entities
            ],
            "fields": self.requested_fields,
            "include": self.include_constraints,
            "exclude": self.exclude_constraints,
            "comparison": self.comparison_entities,
            "comparison_operation": self.comparison_operation,
            "catalog_scope": self.catalog_scope,
            "ambiguity": self.ambiguity_status,
            "mode": self.mode,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def to_debug_dict(self) -> dict[str, Any]:
        return asdict(self)

    def compact_diagnostics(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "intent": self.intent,
            "fields": self.requested_fields,
            "entity_document_ids": self.explicit_document_ids(),
            "comparison_entity_count": len(self.comparison_entities),
            "comparison_operation": self.comparison_operation,
            "ambiguity": self.ambiguity_status,
        }


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


def is_contraction_fragment(value: str) -> bool:
    text = (value or "").strip(" \t\r\n,.;:!?\"")
    if not text:
        return True
    if CONTRACTION_FRAGMENT_PATTERN.fullmatch(text):
        return True
    return bool(re.fullmatch(r"['’`][a-z]{1,2}", text, re.I))


def sanitize_entity_label(value: str) -> str | None:
    text = re.sub(r"\s+", " ", (value or "").strip(" \t\r\n,.;:!?"))
    text = re.sub(r"^(?:what|what's|whats|who|who's|it|it's|that|that's|there|there's|here|here's)\s+", "", text, flags=re.I)
    if is_contraction_fragment(text) or len(text) < 2:
        return None
    if len(text.split()) > 12:
        return None
    return text


def sanitize_comparison_entities(entities: Sequence[str]) -> list[str]:
    cleaned: list[str] = []
    for entity in entities:
        label = sanitize_entity_label(str(entity))
        if not label:
            continue
        if label.lower() in {"and", "with", "vs", "versus", "or", "is", "one is", "the"}:
            continue
        cleaned.append(label)
    return list(dict.fromkeys(cleaned))


def detect_comparison_operation(query: str) -> str | None:
    text = normalize_text(query)
    for operation, pattern in COMPARISON_OPERATION_PATTERNS:
        if pattern.search(text):
            return operation
    return None


def classify_price_role(label: str, origin: str = "", nearby_text: str = "") -> str:
    haystack = " ".join(part for part in (label, origin, nearby_text) if part)
    for role, pattern in PRICE_ROLE_PATTERNS:
        if pattern.search(haystack):
            return role
    return "primary"


def _currency_from_text(text: str) -> str | None:
    if "$" in text or re.search(r"\bUSD\b", text, re.I):
        return "USD"
    if "€" in text or re.search(r"\bEUR\b", text, re.I):
        return "EUR"
    if "£" in text or re.search(r"\bGBP\b", text, re.I):
        return "GBP"
    if "₹" in text or re.search(r"\bINR\b", text, re.I):
        return "INR"
    if "¥" in text or re.search(r"\bJPY\b", text, re.I):
        return "JPY"
    return None


def extract_typed_prices_from_text(
    text: str,
    *,
    entity_name: str = "",
    entity_document_id: int | None = None,
    default_currency: str | None = None,
) -> list[PriceFact]:
    content = text or ""
    facts: list[PriceFact] = []
    seen: set[tuple[str, str, str]] = set()
    money_re = re.compile(
        r"(?P<display>(?P<symbol>\$|₹|€|£|¥)\s*(?P<amount>\d+(?:[.,]\d{1,2})?)"
        r"|(?P<amount2>\d+(?:[.,]\d{1,2})?)\s*(?P<code>USD|EUR|GBP|INR|JPY))",
        re.I,
    )
    for match in money_re.finditer(content):
        start = max(0, match.start() - 96)
        window = content[start:match.end() + 96]
        if re.search(r"\b(?:free shipping|orders? over|money-back|refund of)\b", window, re.I):
            continue
        raw_amount = match.group("amount") or match.group("amount2")
        raw_compact = str(raw_amount).replace(",", "")
        try:
            amount = Decimal(raw_compact)
        except (InvalidOperation, TypeError):
            continue
        normalized = format(amount, "f")
        if "." in raw_compact:
            decimals = len(raw_compact.split(".")[-1])
            normalized = format(amount, f".{max(decimals, 2)}f") if decimals <= 2 else format(amount.normalize(), "f")
        elif amount == amount.to_integral_value() and amount >= 0:
            normalized = format(amount.quantize(Decimal("0.01")), "f") if amount != 0 else "0"
        symbol = match.group("symbol") or ""
        code = (match.group("code") or "").upper() or default_currency or _currency_from_text(window)
        display = re.sub(r"\s+", "", match.group("display") or "")
        if symbol and "." in normalized and not re.search(r"\.\d", display):
            display = f"{symbol}{normalized}"
        prefix = content[start:match.start()]
        role = classify_price_role(prefix[-64:], nearby_text=prefix[-64:])
        key = (role, normalized, (code or "").upper())
        if key in seen:
            continue
        seen.add(key)
        facts.append(
            PriceFact(
                value=normalized,
                currency=code,
                display=display or f"{symbol}{normalized}",
                price_type=role,
                entity_name=entity_name,
                entity_document_id=entity_document_id,
                source="text",
                confidence=0.9 if role != "primary" else 0.82,
            )
        )
    return facts


def currencies_are_compatible(facts: Sequence[PriceFact]) -> bool:
    codes = {(fact.currency or "").upper() for fact in facts if fact.currency}
    codes.discard("")
    return len(codes) <= 1


def _primary_price_for_entity(facts: Sequence[PriceFact]) -> PriceFact | None:
    ranked = (
        "sale", "one_time", "primary", "regular", "monthly", "annual",
        "subscription", "bundle_per_unit", "bundle_total",
    )
    by_rank = {fact.price_type: fact for fact in facts}
    for role in ranked:
        if role in by_rank:
            return by_rank[role]
    return facts[0] if facts else None


def compare_entity_prices(
    facts_by_entity: Mapping[str, Sequence[PriceFact]],
    operation: str,
) -> dict[str, Any] | None:
    primaries: list[tuple[str, PriceFact, Decimal]] = []
    for entity_name, facts in facts_by_entity.items():
        primary = _primary_price_for_entity(facts)
        if primary is None:
            continue
        try:
            amount = Decimal(primary.value)
        except (InvalidOperation, TypeError):
            continue
        primaries.append((entity_name, primary, amount))
    if len(primaries) < 2:
        return None
    all_facts = [fact for _name, fact, _amount in primaries]
    if not currencies_are_compatible(all_facts):
        return {
            "status": "incompatible_currency",
            "message": "Prices are in different currencies and cannot be compared directly without conversion.",
            "entities": [
                {"name": name, "display": fact.display, "currency": fact.currency}
                for name, fact, _amount in primaries
            ],
        }
    ordered = sorted(primaries, key=lambda row: row[2])
    if operation in {"cheaper", "lowest"}:
        winner_name, winner_fact, _ = ordered[0]
        kind = "cheaper"
    else:
        winner_name, winner_fact, _ = ordered[-1]
        kind = "more expensive"
    return {
        "status": "compared",
        "operation": operation,
        "winner": winner_name,
        "winner_display": winner_fact.display,
        "winner_currency": winner_fact.currency,
        "kind": kind,
        "entities": [
            {"name": name, "display": fact.display, "currency": fact.currency, "value": fact.value}
            for name, fact, _amount in primaries
        ],
        "message": (
            f"{winner_name} is {kind} "
            f"({winner_fact.display}"
            f"{' ' + winner_fact.currency if winner_fact.currency else ''})."
        ),
    }


def render_price_facts(facts: Sequence[PriceFact]) -> str:
    if not facts:
        return ""
    lines = ["## Typed prices"]
    lines.extend(fact.as_prompt_line() for fact in facts)
    return "\n".join(lines)


def render_price_comparison(result: Mapping[str, Any] | None) -> str:
    if not result:
        return ""
    return "## Deterministic price comparison\n" + str(result.get("message") or "")


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
            price_type = classify_price_role(label, origin=path) if field_name == "price" else None
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
                    price_type=price_type,
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


def match_all_documents(text: str, documents: Sequence[Any], *, min_score: float = 0.72) -> list[tuple[Any, str, float]]:
    matches: list[tuple[Any, str, float]] = []
    for document in documents:
        best_identity = None
        best_score = 0.0
        for identity in _document_values(document):
            score = _identity_score(text, identity)
            if score > best_score:
                best_identity, best_score = identity, score
        if best_score >= min_score:
            display = str(getattr(document, "title", None) or getattr(document, "filename", None) or best_identity)
            matches.append((document, display, best_score))
    matches.sort(key=lambda row: -row[2])
    return matches


def match_document(text: str, documents: Sequence[Any]) -> tuple[Any | None, str | None, float]:
    matches = match_all_documents(text, documents)
    if not matches:
        return None, None, 0.0
    document, display, score = matches[0]
    return document, display, score


def resolve_named_entities(entities: Sequence[str], documents: Sequence[Any]) -> list[ResolvedEntity]:
    resolved: list[ResolvedEntity] = []
    used_ids: set[int] = set()
    for entity in sanitize_comparison_entities(entities):
        document, display, score = match_document(entity, documents)
        document_id = int(getattr(document, "id", 0) or 0) if document is not None else 0
        if document is None or not document_id or document_id in used_ids:
            continue
        used_ids.add(document_id)
        resolved.append(ResolvedEntity(name=display or entity, document_id=document_id, confidence=score))
    return resolved


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


def _clarification_for(fields: Sequence[str], *, compared: bool = False) -> str:
    field_name = fields[0] if fields else "information"
    if compared:
        return f"Which of the compared items would you like the {field_name.replace('_', ' ')} for?"
    noun = {
        "ingredients": "product or item",
        "price": "product, plan, room, course, or service",
        "amenities": "room or property",
        "syllabus": "course",
        "features": "product, plan, or service",
    }.get(field_name, "item")
    return f"Which {noun} would you like the {field_name.replace('_', ' ')} for?"


def _looks_like_comparison(text: str) -> bool:
    return bool(re.search(
        r"\b(?:compare|difference between|\bvs\.?\b|versus|which one is better)\b",
        text,
        re.I,
    ))


def _entities_from_comparison_text(text: str, documents: Sequence[Any]) -> list[ResolvedEntity]:
    named = match_all_documents(text, documents)
    if len(named) >= 2:
        return [
            ResolvedEntity(
                name=display,
                document_id=int(getattr(document, "id", 0) or 0),
                confidence=score,
            )
            for document, display, score in named
            if int(getattr(document, "id", 0) or 0)
        ]
    parts = [
        part.strip(" ,")
        for part in re.split(
            r"\s*,\s*(?:and\s+)?|\s+(?:and|with|vs\.?|versus)\s+",
            re.sub(r"^(?:compare|what's the difference between|what is the difference between)\s+", "", normalize_text(text)),
        )
        if part.strip(" ,")
    ]
    return resolve_named_entities(parts, documents)


def _recent_comparison_scope(
    history: Sequence[Mapping[str, Any]],
    documents: Sequence[Any],
) -> list[ResolvedEntity]:
    user_items = [item for item in history if str(item.get("role", "")).lower() == "user"]
    for item in reversed(user_items):
        content = str(item.get("content", ""))
        if SUBJECT_SWITCH_PATTERN.search(content) and not MULTI_ENTITY_CONTINUATION_PATTERN.search(content):
            named = match_all_documents(content, documents)
            if len(named) == 1:
                return []
        if _looks_like_comparison(content):
            resolved = _entities_from_comparison_text(content, documents)
            if len(resolved) >= 2:
                return resolved
    return []


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
    comparison_entities = sanitize_comparison_entities(list(params.get("entities") or []))
    references = list(dict.fromkeys(match.group(0).lower() for match in REFERENCE_PATTERN.finditer(query)))
    continuation = bool(MULTI_ENTITY_CONTINUATION_PATTERN.search(query))
    singular_reference = bool(SINGULAR_REFERENCE_PATTERN.search(query))
    comparison_operation = detect_comparison_operation(query)

    current_named = [
        ResolvedEntity(
            name=display,
            document_id=int(getattr(document, "id", 0) or 0),
            confidence=score,
        )
        for document, display, score in match_all_documents(query, documents)
        if int(getattr(document, "id", 0) or 0)
    ]
    resolved_entities = resolve_named_entities(comparison_entities, documents)
    if mode == "comparison" and len(resolved_entities) < 2 and len(current_named) >= 2:
        resolved_entities = current_named[:8]

    history_matches = _history_document_matches(history, documents)
    history_scope = _recent_comparison_scope(history, documents)
    explicit_switch = bool(
        SUBJECT_SWITCH_PATTERN.search(query)
        and current_named
        and not continuation
    )
    if not explicit_switch and current_named and history_scope:
        current_ids = {entity.document_id for entity in current_named}
        scope_ids = {entity.document_id for entity in history_scope}
        if current_ids and current_ids.isdisjoint(scope_ids) and not continuation:
            explicit_switch = True

    if explicit_switch:
        resolved_entities = current_named[:1]
        comparison_entities = []
        if mode == "comparison":
            mode = "factual"
    elif continuation and len(resolved_entities) < 2:
        if len(history_scope) >= 2:
            resolved_entities = history_scope
            comparison_entities = [entity.name for entity in resolved_entities]
            mode = "comparison"
        elif not comparison_entities:
            comparison_entities = [subject for _doc, subject, _score in history_matches[:6] if subject]
            resolved_entities = resolve_named_entities(comparison_entities, documents)
            if len(resolved_entities) >= 2:
                mode = "comparison"

    if len(resolved_entities) >= 2:
        mode = "comparison"
        comparison_entities = [entity.name for entity in resolved_entities]

    direct_document, direct_subject, direct_score = match_document(query, documents)
    resolved_document = direct_document
    resolved_subject = direct_subject
    subject_confidence = direct_score

    if len(resolved_entities) >= 2:
        resolved_document = None
        resolved_subject = None
        subject_confidence = min((entity.confidence for entity in resolved_entities), default=0.0)
    elif len(resolved_entities) == 1:
        entity = resolved_entities[0]
        resolved_document = next(
            (document for document in documents if int(getattr(document, "id", 0) or 0) == entity.document_id),
            None,
        )
        resolved_subject = entity.name
        subject_confidence = entity.confidence
    elif resolved_document is None and references and history_matches:
        ordinal = normalize_text(query)
        if "second one" in ordinal and len(history_matches) >= 2:
            resolved_document, resolved_subject, subject_confidence = history_matches[1]
        else:
            resolved_document, resolved_subject, subject_confidence = history_matches[0]
            subject_confidence = min(subject_confidence, 0.94)
        if resolved_document is not None and not resolved_entities:
            resolved_entities = [
                ResolvedEntity(
                    name=resolved_subject or "",
                    document_id=int(getattr(resolved_document, "id", 0) or 0),
                    confidence=subject_confidence,
                )
            ]

    catalog_scope = extract_catalog_scope(query) if mode == "catalog" else []
    ambiguity_status = "clear"
    clarification_prompt = None
    generic_field_query = bool(fields) and (
        bool(re.search(r"^(?:what (?:are|is)|how much|how long|when|does|do)\b", normalize_text(query)))
        or bool(references)
    )
    explicit_subject_phrase = bool(re.search(r"\b(?:of|for|about)\s+[a-z0-9]", normalize_text(query)))
    named_unknown = explicit_subject_phrase and not references
    ambiguous_singular_followup = (
        bool(fields)
        and singular_reference
        and not continuation
        and len(history_scope) >= 2
        and len(current_named) == 0
        and not explicit_switch
    )
    if ambiguous_singular_followup:
        ambiguity_status = "needs_subject_clarification"
        clarification_prompt = _clarification_for(fields, compared=True)
        mode = "factual"
        resolved_entities = []
        comparison_entities = [entity.name for entity in history_scope]
        resolved_document = None
        resolved_subject = None
        subject_confidence = 0.0
    elif (
        fields
        and resolved_document is None
        and len(resolved_entities) < 2
        and not comparison_entities
        and mode not in {"catalog", "filter", "comparison", "policy"}
        and generic_field_query
        and not named_unknown
    ):
        ambiguity_status = "needs_subject_clarification"
        clarification_prompt = _clarification_for(fields)

    resolved_query = normalize_text(query)
    if len(resolved_entities) >= 2:
        names = " and ".join(entity.name for entity in resolved_entities)
        if not any(normalize_text(entity.name) in resolved_query for entity in resolved_entities):
            resolved_query = f"{names} {resolved_query}".strip()
    elif resolved_subject and references:
        resolved_query = REFERENCE_PATTERN.sub(resolved_subject, resolved_query)
    elif resolved_subject and normalize_text(resolved_subject) not in resolved_query:
        resolved_query = f"{resolved_subject} {resolved_query}".strip()

    return QueryContract(
        original_query=query,
        normalized_query=normalize_text(query),
        resolved_query=resolved_query or query,
        intent=intent if len(resolved_entities) < 2 else "comparison",
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
        resolved_entities=resolved_entities,
        comparison_operation=comparison_operation,
        ambiguity_status=ambiguity_status,
        clarification_prompt=clarification_prompt,
    )
