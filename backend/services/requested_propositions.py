"""Typed, deterministic clauses on the existing query contract and evidence."""
from dataclasses import asdict, dataclass, field
from decimal import Decimal
import re


@dataclass
class RequestedProposition:
    id: str
    type: str
    original_clause: str
    source_span: tuple[int, int]
    applicable_entity: int | None = None
    support_state: str = "missing"
    supporting_candidate_ids: list[list[int]] = field(default_factory=list)
    contradicting_candidate_ids: list[list[int]] = field(default_factory=list)
    unresolved_reason: str | None = "not_searched"
    requested_field: str | None = None


PATTERNS = {
    'purchase_condition': r'\b(?:buy|purchase|order)\b[^,;?]*?[$€£₹]\s*\d+(?:\.\d+)?',
    'shipping_eligibility': r'\bshipping\b',
    'guarantee_eligibility': r'\b(?:money[ -]back|guarantee|refund)\b',
    'repeat_purchase_condition': r'\b(?:repeat|first[ -]time|first|subsequent) purchases?\b',
    'result_timeline': r'\b(?:results?.{0,60}(?:weeks?|days?|months?|timeline)|how soon|see results|results? timeline)\b',
    'guaranteed_result': r'\b(?:results?[^?;]{0,80}guaranteed|guaranteed[^?;]{0,80}results?)\b',
    'entity_applicability': r'\b(?:results?.{0,60}(?:weeks?|days?|months?|timeline)|how soon|see results|results? timeline)\b',
    'inventory': r'\b(?:stock|inventory|warehouse|available right now)\b',
}
EVIDENCE_PATTERNS = {
    'shipping_eligibility': r'\bshipping\b',
    'guarantee_eligibility': r'\b(?:money[ -]back|guarantee|refund)\b',
    'repeat_purchase_condition': r'\b(?:repeat|first[ -]time|first|subsequent) purchases?\b',
    'result_timeline': r'\b(?:results?.{0,100}(?:weeks?|days?|months?)|(?:weeks?|days?|months?).{0,100}results?)\b',
    'guaranteed_result': r'\b(?:results?.{0,100}(?:var(?:y|ies)|guarantee|individual)|(?:var(?:y|ies)|guarantee|individual).{0,100}results?)\b',
    'inventory': r'\b(?:stock|inventory|warehouse)\b',
}
PROPOSITION_FIELDS = {'shipping_eligibility': 'shipping', 'guarantee_eligibility': 'guarantee',
    'repeat_purchase_condition': 'guarantee', 'result_timeline': 'results_timeframe',
    'guaranteed_result': 'results_timeframe', 'inventory': 'availability'}


def bind_field_obligations(contract):
    """Bind the final resolved comparison to bounded, per-resource field cells.

    This never resolves/authorizes an entity. Rebinding after discovery replaces
    stale field cells, preserving the independent conditional propositions.
    """
    entities = list(dict.fromkeys(e.document_id for e in contract.resolved_entities))[:8]
    fields = list(dict.fromkeys(contract.requested_fields))[:12]
    old = {p.id: p for p in contract.requested_propositions if p.type == 'requested_field'}
    kept = [p for p in contract.requested_propositions if p.type != 'requested_field']
    if entities and len(fields) >= 2 and (len(entities) >= 2 or len(contract.comparison_entities) >= 2):
        for doc_id in entities:
            for name in fields:
                identity = f'field:{doc_id}:{name}'
                kept.append(old.get(identity) or RequestedProposition(identity, 'requested_field',
                    contract.original_query[:500], (0, len(contract.original_query)),
                    applicable_entity=doc_id, requested_field=name))
    contract.requested_propositions = kept


def proposition_pattern(proposition):
    if proposition.type == 'requested_field':
        from services.query_contract import field_evidence_pattern
        return field_evidence_pattern(proposition.requested_field)
    value = EVIDENCE_PATTERNS.get(proposition.type)
    return re.compile(value, re.I) if value else None


def proposition_matches(proposition, item):
    from services.observability_service import evidence_key
    if proposition.applicable_entity is not None and evidence_key(item)[0] != proposition.applicable_entity:
        return False
    if proposition.type == 'requested_field' and 'context_field_evidence' in item:
        # This map is produced only by whole-field context admission, including
        # ordered heading/body units and canonical source headers. Re-matching
        # their condensed text by heading keywords loses valid numeric values.
        return bool(item['context_field_evidence'].get(proposition.requested_field))
    if proposition.type == 'requested_field' and proposition.requested_field not in item.get('required_fields', []):
        return False  # A policy window cannot certify a separately requested duration.
    pattern = proposition_pattern(proposition)
    return bool(pattern and pattern.search(str(getattr(item['chunk'], 'content', '') or '')))


def extract_propositions(query):
    result = []
    for kind, pattern in PATTERNS.items():
        match = re.search(pattern, query, re.I)
        if match:
            start = max(query.rfind(',', 0, match.start()), query.rfind(';', 0, match.start())) + 1
            ends = [v for v in (query.find(',', match.end()), query.find(';', match.end()), len(query)) if v >= 0]
            end = min(ends)
            result.append(RequestedProposition(kind, kind, query[start:end].strip()[:500], (start, end)))
    return result


def availability_subtype(text):
    rules = (
        ('stock_quantity', r'\b(?:how many|quantity|count)\b.*\b(?:stock|warehouse|inventory)\b'),
        ('live_inventory', r'\b(?:current inventory|warehouse|in stock.*(?:now|today)|available right now)\b'),
        ('stock_status', r'\b(?:stock|inventory|sold out)\b'),
        ('financing_availability', r'\b(?:financing|payment options?|pay over time|credit)\b.*\b(?:available|eligib|states)\w*'),
        ('geographic_availability', r'\b(?:available|availability)\b.*\b(?:states?|countries|regions?|locations?)\b'),
        ('appointment_availability', r'\b(?:appointment|booking|schedule|slot)s?\b'),
        ('purchasing_availability', r'\b(?:available (?:to|for) (?:buy|purchase)|can (?:i|we) (?:buy|purchase))\b'),
        ('generic_availability', r'\b(?:available|availability)\b'),
    )
    return next((kind for kind, pattern in rules if re.search(pattern, text, re.I)), None)


def annotate_candidates(contract, items, trace=None):
    """Reserve distinct clauses before duplicate rank depth, without claiming proof.

    Items are copies: caller-owned ORM rows and shared cached candidates are not
    changed. All inputs already passed scope/lifecycle/profile gates.
    """
    bind_field_obligations(contract)
    result = []
    for item in items:
        row = dict(item)
        text = str(getattr(row['chunk'], 'content', '') or '')
        matches = [p.id for p in contract.requested_propositions
                   if (p.type == 'requested_field' and p.applicable_entity == row['document'].id
                       and p.requested_field in row.get('required_fields', []))
                   or (p.type != 'requested_field' and proposition_matches(p, row))]
        row['requested_propositions'] = matches
        if matches:
            row['required_fields'] = list(dict.fromkeys(list(row.get('required_fields') or []) +
                [PROPOSITION_FIELDS[p] for p in matches if p in PROPOSITION_FIELDS]))
        if contract.availability_subtype:
            evidence_types = sorted({kind for line in text.splitlines() if (kind := availability_subtype(line))})
            live = contract.availability_subtype in {'live_inventory', 'stock_quantity', 'stock_status'}
            if trace and evidence_types:
                trace.retrieval.availability.setdefault('evidence', []).append({
                    'document_id': row['document'].id, 'chunk_id': row['chunk'].id,
                    'subtypes': evidence_types,
                    'mismatch_reason': 'non_inventory_availability' if live and not set(evidence_types) & {'live_inventory', 'stock_quantity', 'stock_status'} else None})
            if live and not set(evidence_types) & {'live_inventory', 'stock_quantity', 'stock_status'}:
                row['required_fields'] = [f for f in row.get('required_fields', []) if f != 'availability']
        result.append(row)
    return result


def update_support(contract, items, trace=None):
    from services.observability_service import evidence_key
    from services.monetary_evidence import extract_monetary
    amount = next((m for p in contract.requested_propositions if p.type == 'purchase_condition'
                   for m in extract_monetary(p.original_clause)), None)
    for p in contract.requested_propositions:
        if p.type != 'requested_field':
            p.applicable_entity = contract.subject_document_id
        p.supporting_candidate_ids, p.contradicting_candidate_ids = [], []
        p.support_state, p.unresolved_reason = 'missing', 'bounded_recall_no_evidence'
        matches = [item for item in items if proposition_matches(p, item)]
        if p.type == 'purchase_condition':
            p.support_state, p.unresolved_reason = 'supported', 'user_supplied_condition_not_catalog_identity'
        elif p.type in {'result_timeline', 'entity_applicability', 'guaranteed_result'} and not contract.resolved_entities:
            p.support_state, p.unresolved_reason = 'applicability_unresolved', 'product_specific_clause_requires_entity'
        elif p.type == 'inventory':
            p.unresolved_reason = 'live_inventory_source_unavailable'
        elif matches:
            # Keyword hits are evidence candidates, not a semantic proof. The
            # existing reviewer may confirm or reject individual propositions.
            p.support_state, p.unresolved_reason = 'ambiguous', 'candidate_evidence_requires_review'
            p.supporting_candidate_ids = [list(evidence_key(item)) for item in matches[:8]]
            if p.type == 'shipping_eligibility' and amount:
                thresholds = [(item, fact) for item in matches for fact in extract_monetary(item['chunk'].content)
                              if fact['price_type'] == 'shipping_threshold' and fact['currency'] == amount['currency']]
                if thresholds and all(Decimal(amount['value']) < Decimal(fact['value']) for _, fact in thresholds):
                    p.support_state, p.unresolved_reason = 'contradicted', 'purchase_below_stated_shipping_threshold'
                    p.contradicting_candidate_ids = [list(evidence_key(item)) for item, _ in thresholds[:8]]
            if p.type == 'repeat_purchase_condition':
                negative = [item for item in matches if re.search(
                    r'(?:does not cover|excludes?)\s+(?:ordinary\s+)?repeat purchases?|'
                    r'repeat purchases?\s+(?:(?:are|is)\s+)?(?:not (?:eligible|covered)|excluded|ineligible)\b', item['chunk'].content, re.I)]
                if negative:
                    p.support_state, p.unresolved_reason = 'contradicted', 'explicit_repeat_purchase_exclusion'
                    p.contradicting_candidate_ids = [list(evidence_key(item)) for item in negative[:8]]
        if trace:
            # Reviewer support is usable only for references that survived into
            # this context, and cannot override unresolved entity applicability.
            outcome = next((v for v in trace.retrieval.reviewer_outcome.get('proposition_support', [])
                            if v['proposition_id'] == p.id), None)
            present = {tuple(evidence_key(item)) for item in items
                       if p.applicable_entity is None or evidence_key(item)[0] == p.applicable_entity}
            if outcome and p.support_state != 'applicability_unresolved':
                refs = outcome['supporting_candidate_ids'] + outcome['contradicting_candidate_ids']
                if refs and all(tuple(ref) in present for ref in refs):
                    p.support_state = outcome['support_state']
                    p.supporting_candidate_ids = outcome['supporting_candidate_ids']
                    p.contradicting_candidate_ids = outcome['contradicting_candidate_ids']
                    p.unresolved_reason = None if p.support_state in {'supported', 'contradicted'} else 'reviewer_uncertain'
                elif outcome['support_state'] == 'missing':
                    p.support_state, p.unresolved_reason = 'missing', 'reviewer_missing_proposition'
    if trace:
        trace.retrieval.requested_propositions = [asdict(v) for v in contract.requested_propositions]
        if any(p.unresolved_reason == 'bounded_recall_no_evidence' for p in contract.requested_propositions):
            trace.retrieval.fallback('proposition_recall_limit_phase2', terminal=False)


def proposition_instructions(contract):
    if not contract.requested_propositions:
        return ''
    # The exact original question is already in the generation prompt. Do not
    # duplicate long clauses or full trace ledgers in the bounded context.
    rows = [f"- {p.requested_field or p.type}: {p.support_state}; entity={p.applicable_entity}; reason={p.unresolved_reason}"
            for p in contract.requested_propositions]
    return ('\nRequested clause coverage (candidate references are not facts):\n' +
            '\n'.join(rows) +
            '\nAnswer supported clauses even when another clause is missing. Never infer an entity from a price. '
            'Use only supplied source wording; state which specific fact is unavailable. '
            'For applicability_unresolved, ask at most ONE targeted entity clarification for that clause, '
            'without withholding supported policy clauses. Never apply a product-specific timeline globally. '
            'Do not treat a result timeline as a guarantee or candidate matching as proof.\n')
