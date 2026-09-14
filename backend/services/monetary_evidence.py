"""Source-bound monetary extraction. No positional nearest-label guessing."""
from decimal import Decimal
import hashlib
import re

MONEY = re.compile(r"(?P<display>(?:(?P<symbol>[$₹€£¥])\s*|(?P<prefix>USD|EUR|GBP|INR|JPY)\s+)(?P<amount>\d+(?:,\d{3})*(?:\.\d{1,2})?)|(?P<amount2>\d+(?:\.\d{1,2})?)\s*(?P<code>USD|EUR|GBP|INR|JPY))", re.I)
SYMBOLS = {"$": "USD", "₹": "INR", "€": "EUR", "£": "GBP", "¥": "JPY"}
ROLE_RULES = (
    ("financing_threshold", r"(?:pay over time|financ|payment).*(?:orders? (?:over|of)|minimum)"),
    ("shipping_threshold", r"(?:shipping.*(?:over|above|minimum|orders)|orders?.*(?:free shipping))"),
    ("installment_payment", r"installments?|instalments?|payments? of"),
    ("per_day_cost", r"/\s*day\b|per day\b|daily cost"),
    ("refund_amount", r"refund(?: amount| of)?\b"),
    ("discount", r"discount|save\s*[:$]|\boff\b"),
    ("subscription", r"subscribe|subscription"),
    ("one_time", r"one[ -]?time(?: purchase)?"),
    ("sale", r"\bsale(?: price)?\b"),
    ("regular", r"\b(?:regular|list)(?: price)?\b"),
    ("bundle_per_unit", r"per[ -]?(?:bottle|unit|pack|item)|/\s*(?:bottle|unit|pack)\b"),
    ("bundle_total", r"\bbundle(?: total| price)?\b|\d+[ -]?packs?\b|\d+[ -]?bottles?\b"),
    ("monthly", r"\bmonthly\b|/\s*mo(?:nth)?\b"),
    ("annual", r"\b(?:annual|yearly)\b|/\s*year\b"),
    ("primary", r"\b(?:price|priced at|costs?|fee|rate|tuition|rent|now)\b"),
)


def role_for_label(label):
    if re.search(r'financ|pay over time|payment', label, re.I) and re.search(r'\b(?:minimum|min|threshold)\b|orders? (?:over|of)', label, re.I):
        return 'financing_threshold'
    options = {role for role, pattern in ROLE_RULES if role in {'subscription', 'one_time', 'sale', 'regular'}
               and re.search(pattern, label, re.I)}
    if len(options) > 1:
        return 'unknown_or_ambiguous'
    for role, pattern in ROLE_RULES:
        if re.search(pattern, label, re.I):
            return role
    return "unknown_or_ambiguous"


def _offer_values(lines):
    """Recognize one bounded, explicitly discounted recurring offer.

    An unlabeled amount sequence alone proves nothing. Require an offer heading,
    a repeated base, an explicit recurring discount, recurrence, and exact Decimal
    arithmetic. Stop at another offer/heading or unrelated monetary line.
    """
    verified = {}
    for index, (_, line) in enumerate(lines):
        if not re.fullmatch(r"\s*subscribe\s*(?:&|and)\s*save(?: more)?[!: ]*", line, re.I):
            continue
        block, row = [], None
        size = 0
        for offset, following in lines[index + 1:index + 13]:
            size += len(following)
            if size > 1200 or re.search(r"^\s*(?:OR\b|#|one[ -]?time|free .*shipping)", following, re.I):
                break
            amounts = list(MONEY.finditer(following))
            if amounts:
                if len(amounts) == 3 and row is None and re.search(r"/\s*(?:bottle|unit|item)\b", following, re.I):
                    row = (offset, following, amounts)
                elif not re.search(r"/day\b|per day\b", following, re.I):
                    break
            block.append(following)
        body = "\n".join(block)
        discount = re.search(r"\bRecurring\s*(\d+(?:\.\d+)?)%\s*OFF\b", body, re.I)
        recurrence = re.search(r"delivered every\s+(\d+\s+(?:days?|weeks?|months?|years?))", body, re.I)
        if not (row and discount and recurrence):
            continue
        offset, raw, amounts = row
        values = [Decimal((m['amount'] or m['amount2']).replace(',', '')) for m in amounts]
        currencies = {SYMBOLS.get(m['symbol']) or (m['code'] or m['prefix'] or '').upper() for m in amounts}
        if len(currencies) == 1 and values[0] == values[2] and (values[0] * (1 - Decimal(discount[1]) / 100)).quantize(Decimal('.01')) == values[1] and values[1] < values[0]:
            verified[offset + amounts[1].start()] = ("subscription", "explicit_recurring_discount_offer", recurrence[1])
    return verified


def extract_monetary(text, default_currency=None):
    lines, offset = [], 0
    for raw in text.splitlines(keepends=True):
        lines.append((offset, raw.rstrip('\r\n')))
        offset += len(raw)
    offers = _offer_values(lines)
    pending_label, blank_count = "", 0
    records = []
    for offset, line in lines:
        if not line.strip():
            blank_count += 1
            if blank_count > 1:
                pending_label = ""
            continue
        matches = list(MONEY.finditer(line))
        for index, match in enumerate(matches):
            # Same row/item, bounded by the neighboring amounts and sentence or
            # semicolon boundaries. No label crosses a newline implicitly.
            left = matches[index-1].end() if index else 0
            right = matches[index+1].start() if index+1 < len(matches) else len(line)
            prefix = re.split(r";|(?<=[.!?])\s+", line[left:match.start()])[-1]
            suffix = re.split(r";|(?<=[.!?])\s+", line[match.end():right])[0]
            label = prefix.strip(' |-*\t')
            # A suffix is a unit or role only if explicit. Do not borrow a later
            # option label preceding the next amount.
            unit = re.match(r"\s*(/\s*(?:day|bottle|unit|pack|month|year)|per\s+(?:day|unit|bottle))\b", suffix, re.I)
            role = role_for_label(label + (' ' + unit[0] if unit else ''))
            rule = "same_row_label"
            if role == 'unknown_or_ambiguous' and len(matches) == 1 and not label and pending_label:
                label, role, rule = pending_label, role_for_label(pending_label), 'explicit_label_value_pair'
            position = offset + match.start()
            recurrence = unit[0].strip() if unit else None
            if position in offers:
                role, rule, recurrence = offers[position]
                label = 'Subscribe & Save; explicit recurring discount'
            # A concatenated unlabeled price row is not three distinct options.
            elif len(matches) > 1 and not label and not re.search(r'[.;]', line[left:match.start()]):
                role = 'unknown_or_ambiguous'
            amount = Decimal((match['amount'] or match['amount2']).replace(',', ''))
            display = match['display'].strip()
            currency = SYMBOLS.get(match['symbol']) or (match['code'] or match['prefix'] or default_currency)
            records.append(dict(value=format(amount, '.2f'), currency=currency.upper() if currency else None,
                display=display, price_type=role, original_label=label[:120], original_value=display,
                unit_recurrence=recurrence, source_span=(position, offset + match.end()),
                fragment_hash=hashlib.sha256(line.encode()).hexdigest()[:20],
                extraction_rule=rule if role != 'unknown_or_ambiguous' else 'ambiguous_source_amount',
                verification_state='verified' if role != 'unknown_or_ambiguous' else 'ambiguous'))
        # Only an exact short label can associate with the immediately following
        # value line, never arbitrary prose/reviews or a persistent heading.
        pending_label = line.strip() if not matches and re.fullmatch(
            r"\s*(?:one[ -]?time(?: purchase)?|subscription(?: price)?|subscribe\s*&\s*save|sale price|regular price|list price|price|monthly|annual)\s*[:|]?\s*", line, re.I) else ''
        blank_count = 0
    return records
