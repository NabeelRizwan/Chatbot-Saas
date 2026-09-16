"""Small, conservative source-label rules; no catalog, business ontology or I/O.

Only explicit syntax is typed. Original text is always retained by the adapter.
Pattern provenance and intentional divergences: Phase 4.1B OSS ledger, 4.1C addendum.
"""
from __future__ import annotations

import re
from decimal import Decimal
from urllib.parse import urlsplit

from services.structural_document import CommercialAttributes, LinkAttributes, QuantityAttributes


TIMELINE = re.compile(
    r"(?:\d+(?:\s*[-–]\s*\d+)?\s+(?:days?|weeks?|months?|years?)|"
    r"(?:day|week|month|year)\s+\d+(?:\s*[-–]\s*\d+)?\s*:\s*\S.*)", re.I)
QUALIFIER = re.compile(r"\b(?:may|might|vary|varies|not guaranteed)\b", re.I)
REVIEW_LABEL = re.compile(r"^\s*(?:Review(?:\s+[\w-]+)?|Testimonial(?:\s+[\w-]+)?)\s*:", re.I)
REVIEW_SIGNATURE = re.compile(r"^\s*(?:Verified\s+)?(?:Reviewer|Customer)\s*\\?\|", re.I)
QUESTION = re.compile(r"^(?:Q\s*:\s*|(?:how|what|when|where|why|who|which|can|could|do|does|is|are|will|should)\b).+\?$", re.I)
AMOUNT = re.compile(r"(?:(?<!\w)(?P<iso>USD|EUR|GBP|CAD|AUD|JPY)\s+|(?P<symbol>[$€£]))"
                    r"(?P<value>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?!\d|[.,]\d)")
QUANTITY = re.compile(
    r"(?<![\w.,$])(?P<first>\d+(?:\.\d+)?)(?:\s*[-–]\s*(?P<last>\d+(?:\.\d+)?))?\s+"
    r"(?P<unit>scoops?|capsules?|softgels?|tablets?|servings?|grams?|mg|mcg|g|kg|ml|mL|liters?|oz|ounces?|"
    r"cups?|teaspoons?|tablespoons?|GB|MB|TB|days?|weeks?|months?|years?|hours?|minutes?)\b")
FREQUENCY = re.compile(r"\b(?:once daily|twice daily|daily|weekly|monthly|per day|per week|per month)\b", re.I)


def qualifiers(text: str) -> tuple[str, ...]:
    """Exact source sentences; no transformation into outcome guarantees."""
    return tuple(m.group().strip() for m in re.finditer(r"[^.!?\n]+[.!?]?", text)
                 if QUALIFIER.search(m.group()) or
                 (re.search(r"\bno\b",m.group(),re.I) and re.search(r"\bguaranteed\b",m.group(),re.I)))


def link_attributes(href: str, anchor: str, *, target_count: int = 0) -> LinkAttributes:
    safety, validated, fragment = "unchecked", None, None
    try:
        p = urlsplit(href)
        fragment = p.fragment or None
        if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in href) or p.username or p.password:
            safety = "unsafe"
        elif p.scheme.lower() in ("http", "https") and p.hostname:
            # Syntax only. NOT an SSRF/access decision, URL canonicalization or fetch.
            safety, validated = "safe", href
        elif p.scheme or href.startswith("//"):
            safety = "unsafe"
    except ValueError:
        safety = "unsafe"
    return LinkAttributes(original_href=href, anchor_text=anchor, fragment=fragment,
        safety=safety, validated_href=validated,
        resolution=("resolved" if target_count == 1 else "ambiguous" if target_count > 1 else "unresolved")
        if safety == "safe" else "unresolved")


def commercial_values(text: str):
    """Yield exact amount spans, retaining unknown roles for flattened offers."""
    matches = list(AMOUNT.finditer(text))
    for m in matches:
        if len(m.group('value'))>32:
            continue  # Very large numeric strings stay raw, not numeric metadata.
        role, conditions = "unknown", []
        # A unique amount in this line/clause is necessary but not sufficient.
        if len(matches) == 1:
            lead, tail = text[:m.start()].strip(), text[m.end():].strip().rstrip(".")
            labels = ((r"(?:one[- ]time(?: purchase)?|single purchase)\s*:?$", "one_time"),
                      (r"subscription\s*:?$", "subscription"), (r"regular(?: price)?\s*:?$", "regular"),
                      (r"(?:sale|offer)(?: price)?\s*:?$", "offer"), (r"(?:fee|shipping fee)\s*:?$", "fee"))
            for pattern, candidate in labels:
                if re.search(pattern, lead, re.I):
                    role = candidate
                    break
            if re.fullmatch(r"Price\s*:", lead, re.I) and re.fullmatch(r"(?:per\s+[\w-]+\s+)?(?:monthly|yearly|weekly)", tail, re.I):
                role = "subscription"
                conditions = re.findall(r"per\s+[\w-]+|monthly|yearly|weekly", tail, re.I)
        source_end = m.end()
        if conditions:
            source_end = len(text.rstrip().rstrip("."))
        yield m.start(), m.end(), CommercialAttributes(source_text=text[m.start():source_end],
            amount=m.group("value").replace(',',''), currency=m.group("iso"), role=role, conditions=tuple(conditions))


def quantities(text: str) -> tuple[QuantityAttributes, ...]:
    result = []
    for m in QUANTITY.finditer(text):
        first, last, unit = m.group("first", "last", "unit")
        if len(first)>32 or (last is not None and len(last)>32):
            continue
        if last is not None and Decimal(last) < Decimal(first):
            continue  # Preserve raw text, do not assert a reversed range.
        # A period inside a decimal is not a clause boundary.
        ending = re.search(r"(?<!\d)[.!?](?:\s|$)|(?<=\d)[.!?](?=\s|$)|[;\n]", text[m.end():])
        clause_end = m.end() + ending.start() if ending else len(text)
        tail = text[m.end():clause_end]
        freq = FREQUENCY.search(tail)
        qualifier = None
        # An explicitly adjacent instruction may qualify a serving, not water volume.
        following = text[clause_end:]
        follow = re.match(r"[.!?]\s+Take\s+(daily|weekly|monthly)\s+(as directed)\b", following, re.I)
        if not freq and follow and re.fullmatch(r"scoops?|capsules?|softgels?|tablets?", unit):
            frequency, qualifier = follow.group(1), follow.group(2)
        else:
            frequency = freq.group() if freq else None
        water = re.match(r"\s+of\s+(water(?:\s+or\s+your\s+favorite\s+beverage)?)", tail, re.I)
        per = re.match(r"\s+(per\s+[\w-]+)", tail, re.I)
        if water:
            qualifier, frequency = water.group(1), None
        elif per:
            qualifier = per.group(1)
        source_end = m.end() + per.end() if per else m.end()
        result.append(QuantityAttributes(source_text=text[m.start():source_end],
            value=first if last is None else None, range_min=first if last is not None else None,
            range_max=last, unit=unit, frequency=frequency, qualifier=qualifier))
    return tuple(result)


def enumeration_spans(text: str) -> tuple[tuple[int, int], ...]:
    """Explicit comma enumeration after a listing verb; no ingredient/card ontology.

    Require >=3 bounded entries and a closing conjunction. Ambiguous clauses abstain.
    This records a complete *source enumeration*, never real-world exhaustiveness.
    """
    lead = re.search(r"\b(?:combines|including)\s+", text, re.I)
    if lead is None:
        return ()
    start = lead.end()
    # A paired dash explicitly brackets an enumeration, e.g. 'five types — A, B, and C —'.
    dash = re.match(r"[^,.;\n]{0,100}\s[—–]\s", text[start:])
    if dash:
        start += dash.end()
    ending = re.search(r"\s[—–]\s|[.;\n]|\s+and\s+(?:is|are|was|were)\b", text[start:])
    end = start + ending.start() if ending else len(text)
    value = text[start:end]
    if not re.search(r",\s+and\s+[^,]+$", value) or len(value) > 3000:
        return ()
    pieces = []
    for m in re.finditer(r"[^,]+", value):
        a, b = start + m.start(), start + m.end()
        while a < b and text[a].isspace(): a += 1
        if text[a:b].lower().startswith("and "): a += 4
        while b > a and text[b-1].isspace(): b -= 1
        if not a < b or b-a > 300 or re.search(r"\b(?:is|are|was|were|designed|formulated)\b", text[a:b], re.I):
            return ()
        pieces.append((a,b))
    return tuple(pieces) if 3 <= len(pieces) <= 64 else ()
