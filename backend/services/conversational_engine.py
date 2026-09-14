import json
import re
from time import perf_counter
from typing import Any, Dict, List, Optional, Tuple

from services.embedding_service import generate_embedding
from services.llm_router import generate, verification_mode, get_last_auxiliary_metadata
from services.intent_router import (
    classify_intent as pattern_classify_intent,
    detect_length_preference,
    rewrite_query_for_retrieval,
    extract_requested_fields,
    extract_filter_attributes,
    INTENT_GREETING,
    INTENT_FAREWELL,
    INTENT_GRATITUDE,
    INTENT_IDENTITY,
    INTENT_SMALL_TALK,
    INTENT_SUMMARIZE_PREVIOUS,
    INTENT_SIMPLIFY_PREVIOUS,
    INTENT_REPHRASE_CONTINUE,
    INTENT_PRONOUN_FOLLOWUP,
    INTENT_KNOWLEDGE_QUERY,
)
from services.query_contract import FIELD_EVIDENCE_PATTERNS as CONTRACT_FIELD_EVIDENCE_PATTERNS
from services.query_contract import field_evidence_pattern, usage_compatibility_targets, USAGE_ACTION_EVIDENCE
from services.retrieval_selection import POLICY, signals, adjacent_only_rank, text as evidence_text
from services.observability_service import ChatTrace, evidence_key


from services.tenant_cache_service import TenantSafeCache, global_tenant_cache

SemanticCache = TenantSafeCache
global_semantic_cache = global_tenant_cache



class ContextMemory:
    """Lightweight conversation memory tracking entities, current topic, and history summary."""

    def __init__(self, history: Optional[List[Dict[str, str]]] = None):
        self.history = history or []
        self.entities: List[str] = []
        self.current_topic: Optional[str] = None
        self._analyze_history()

    def _analyze_history(self) -> None:
        if not self.history:
            return
        # Extract potential entities (capitalized words, numbers, key terms)
        for item in self.history:
            content = str(item.get("content", ""))
            # Extract capitalized terms (names, products, organizations)
            caps = re.findall(r"\b[A-Z][a-zA-Z0-9'-]+\b", content)
            for c in caps:
                if c.lower() not in {"the", "a", "an", "i", "you", "we", "they", "he", "she", "it", "is", "are", "was", "were", "what", "how", "why"}:
                    if c not in self.entities:
                        self.entities.append(c)

        # Set current topic from last user turn
        for item in reversed(self.history):
            if str(item.get("role", "")).lower() == "user":
                self.current_topic = str(item.get("content", ""))[:100]
                break

    def get_summary(self) -> Dict[str, Any]:
        return {
            "entities": self.entities[:10],
            "current_topic": self.current_topic,
            "turns_count": len(self.history),
        }


_CONTEXT_FIELD_PATTERNS = {
    "price": re.compile(r"(?:\$|₹|€|£)\s*\d|\b(?:price|pricing|cost|rate|fee)s?\b", re.I),
    "ingredients": re.compile(r"\b(?:ingredient|composition|component|material)s?\b", re.I),
    "directions": re.compile(r"\b(?:how to use|directions?|usage|dosage|dose|serving|instructions?|take \d|mix \d|setup)\b", re.I),
    "form": re.compile(r"\b(?:form|format|variant|capsules?|softgels?|gumm(?:y|ies)|powder|liquid|tablets?)\b", re.I),
    "benefits": re.compile(r"\b(?:benefits?|purpose|supports?|capabilities|features)\b", re.I),
    "flavor": re.compile(r"\b(?:flavou?r|taste)\b", re.I),
    "reviews": re.compile(r"\b(?:reviews?|ratings?|verified reviewer|testimonials?|feedback)\b", re.I),
}
_CONTEXT_FIELD_PATTERNS.update(CONTRACT_FIELD_EVIDENCE_PATTERNS)


def _context_cross_sell(content: str, metadata: dict | None = None) -> bool:
    section = str((metadata or {}).get("section") or (metadata or {}).get("heading") or "")
    if re.search(
        r"\b(?:you may also like|related products?|recommended(?: for you)?|frequently bought|customers also)\b",
        section,
        re.I,
    ):
        return True
    if re.search(
        r"(?:^|\n)#{1,4}\s*(?:you may also like|related products?|recommended(?: for you)?|"
        r"frequently bought|customers also (?:viewed|bought))\b|\bview productview product\b|"
        r"\badd to wishlist\b",
        content,
        re.I,
    ):
        return True
    return bool(
        re.search(r"(?:^|\n)#{2,4}\s+\[[^\]]+\]\(https?://[^)]+\)", content)
        and re.search(r"\b(?:now\s*[$€£₹]?\d|view product|add to wishlist)\b", content, re.I)
        and not re.search(r"\b(?:product description|specifications?|how to use|ingredients?)\b", content, re.I)
    )


def _condense_primary_detail(content: str, requested_fields: list[str]) -> str:
    """Remove checkout chrome while preserving the page's factual sections."""
    detail = re.search(r"\b(?:product description|overview|service description)\b", content, re.I)
    if not detail:
        return content
    prefix = content[:detail.start()]
    first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
    prices = list(dict.fromkeys(re.findall(r"(?:\$|₹|€|£|¥)\s*\d+(?:[.,]\d{1,2})?", prefix)))
    price_lines: list[str] = []
    if "price" in requested_fields and prices:
        from services.query_contract import extract_typed_prices_from_text
        facts = extract_typed_prices_from_text(prefix)
        price_lines = list(dict.fromkeys(
            f"{fact.price_type}: {fact.display}" for fact in facts
            if fact.verification_state == "verified"))
        # Unknown amounts remain verbatim, never relabeled as commercial options.
        ambiguous_lines = [line for line in prefix.splitlines() if any(
            fact.verification_state == "ambiguous" and fact.original_value in line for fact in facts)]
        if ambiguous_lines:
            price_lines.append("Unclassified source amounts (not verified prices):\n" + "\n".join(ambiguous_lines))
        if not price_lines:
            return content
    price_line = "\n".join(price_lines)
    # Keep the section heading separate from the title/price paragraph. The
    # required-field assembler locates that heading before taking its body;
    # merging it with the title silently substitutes a label for the evidence.
    return "\n\n".join(part for part in (first_line, price_line, content[detail.start():]) if part)


def _trim_evidence(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    suffix = "\n[Additional page detail omitted for context allocation.]"
    if limit <= len(suffix):
        return ""
    # A sentence/character boundary may remove the exception to a commercial
    # condition. Reuse whole paragraph units; never slice a long factual unit.
    parts = []
    for part in re.split(r"\n\s*\n", text):
        if len("\n\n".join(parts + [part])) + len(suffix) > limit:
            break
        parts.append(part)
    excerpt = "\n\n".join(parts).rstrip()
    if not excerpt or ("\n" not in excerpt and excerpt.startswith(("#", "["))):
        return ""
    return excerpt + suffix


def _source_reference_url(value, document):
    """Only literal, unsigned same-origin references; never synthesize a URL."""
    from urllib.parse import urlsplit
    from services.resource_catalog import safe_navigation_url
    url = safe_navigation_url(value)
    canonical = safe_navigation_url(getattr(document, 'canonical_url', None) or getattr(document, 'source_url', ''))
    if url and canonical:
        target, source = urlsplit(url), urlsplit(canonical)
        if (target.scheme, target.netloc.lower()) == (source.scheme, source.netloc.lower()):
            return url
    return None


def admitted_reference_links(item):
    """References from the runtime admission ledger, not raw chunks/metadata."""
    links = {}
    for parts in item.get('context_field_evidence', {}).values():
        for part in parts:
            for label, value in re.findall(r'\[([^\]\n]+)\]\(([^\s)]+)\)', part):
                url = _source_reference_url(value, item['document'])
                if url and url not in links and len(links) < 8:
                    links[url] = {'label': label[:120], 'url': url}
    return list(links.values())


def _primary_field_keys(items, field):
    return {evidence_key(item) for item in items if any(
        bundle.get('field') == field and bundle.get('primary_chunk_id') == getattr(item['chunk'], 'id', None)
        for bundle in item.get('evidence_bundles', []))}


def _required_field_parts(items: list[dict], field: str, origins: dict[str, set[tuple[int, int]]] | None = None, preserve_links: bool = False, usage_query: str = "") -> list[str]:
    """Extract verbatim field paragraphs, keeping split numeric stages together."""
    if origins is None:
        origins = {}
    parts = []
    for item in sorted(items, key=lambda row: int(getattr(row["chunk"], "chunk_index", 0) or 0)):
        raw = str(getattr(item["chunk"], "content", "") or "")
        raw = _condense_primary_detail(raw, [field])
        raw = re.sub(r"(?m)^>.*$", "", raw)
        raw = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", raw)
        # Standalone navigation is not field evidence. When links are requested,
        # retain safe references inside factual paragraphs; normal admission
        # then charges their full length and omits them with any rejected part.
        raw = re.sub(r"(?m)^\s*(?:[-*]\s*)?(?:\[[^\]]*\]\([^)]*\)\s*)+$", "", raw)
        raw = re.sub(r"\[([^\]]+)\]\(([^)]*)\)",
                     lambda m: m[0] if preserve_links and _source_reference_url(m[2], item['document']) else m[1], raw)
        raw = re.sub(r"(?m)^\[[^\]\n]+\](?:\s*\[[^\]\n]+\])?\s*", "", raw)
        raw = re.sub(r"(?m)^#{1,6}\s*", "", raw).strip()
        item_parts = [part.strip() for part in re.split(r"\n\s*\n", raw) if part.strip()]
        parts.extend(item_parts)
        if origins is not None:
            for part in item_parts:
                origins.setdefault(part, set()).add(evidence_key(item))

    def joined(values, separator=" "):
        value = separator.join(values)
        if origins is not None:
            origins[value] = set().union(*(origins.get(part, set()) for part in values))
        return value

    parts = list(dict.fromkeys(parts))
    if field == "entity_detail":
        match = next((i for i, part in enumerate(parts) if re.fullmatch(r"(?:product description|service description|overview)", part, re.I)), None)
        return parts[match + 1:match + 2] if match is not None else parts[:1]
    pattern = field_evidence_pattern(field)
    def field_text(part):
        # A destination path containing a field word must not select unrelated
        # prose. Match the same visible text used before reference retention.
        return re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", part)
    requested_targets = usage_compatibility_targets(usage_query) if field in {"directions", "specifications"} else []
    def compatibility(part):
        return any(wanted & supplied for wanted in requested_targets
                   for supplied in usage_compatibility_targets(field_text(part)))
    def action(part):
        return field == "directions" and bool(USAGE_ACTION_EVIDENCE.search(field_text(part)))
    def field_match(part):
        visible = field_text(part)
        for match in pattern.finditer(visible):
            # A noun such as 'the color mix looks...' is not an instruction.
            # Preserve imperative/modal verb positions and every other field.
            if field == "directions" and match[0].lower().startswith('mix '):
                prefix = visible[:match.start()].rstrip()
                if prefix and prefix[-1] not in '.!?:\n-*' and not re.search(
                        r"\b(?:please|then|to|must|should|can|may)$", prefix, re.I):
                    continue
            return True
        return False
    numeric_section = any(re.fullmatch(r"\d+(?:\s*[-–]\s*\d+)?\s+[a-z]+", part, re.I) for part in parts)
    if numeric_section and len(items) > 1:
        # A number at the end of one chunk belongs to the following body,
        # not the preceding stage. Keep that boundary atomic during trimming.
        units = []
        for index, part in enumerate(parts):
            if re.fullmatch(r"\d+(?:\s*[-–]\s*\d+)?\s+[a-z]+", part, re.I):
                body = parts[index + 1:index + 3]
                units.append(joined([part] + body))
        qualifiers = [
            part for index, part in enumerate(parts)
            if len(part.split()) > 8 and (
                pattern.search(field_text(part))
                or (index and pattern.search(field_text(parts[index - 1])) and len(parts[index - 1].split()) <= 8)
            )
        ]
        numeric_answers = [part for part in qualifiers if re.search(r"\b\d", part)]
        return list(dict.fromkeys(numeric_answers + units + qualifiers))
    selected = []
    for index, part in enumerate(parts):
        if not (field_match(part) or action(part) or compatibility(part)):
            continue
        # A short heading plus its value can share a paragraph. Do not drop
        # that complete section merely because it contains six words or fewer.
        if "\n" in part and len(part.split()) > 1:
            selected.append(part)
        elif (len(part.split()) <= 6 and index + 1 < len(parts)
              and not re.search(r":\s*\S|\b\d", part)):
            following = parts[index + 1]
            if len(following.split()) > 5 or action(following) or compatibility(following):
                selected.append(joined([part, following], "\n"))
            elif not pattern.fullmatch(field_text(part)):
                selected.append(part)
        elif len(part.split()) > 1 and not pattern.fullmatch(field_text(part)):
            selected.append(part)
    selected = [part for index, part in enumerate(selected) if not any(part in prior for prior in selected[:index])]
    primary = _primary_field_keys(items, field)
    if primary:
        # Honor the field scanner's concrete primary evidence, not page order.
        # Short labels in that same chunk cannot crowd out its substantive body.
        # Ordered numeric sections returned above keep their adjacency/order.
        selected.sort(key=lambda part: (not bool(origins.get(part, set()) & primary),
                                        len(field_text(part).split()) <= 8))
    # A requested use target qualifies the resource; it must not be optional
    # depth behind serving instructions. Keep the best action + up to two
    # matching capability paragraphs as one verbatim, budgeted evidence unit.
    compatible = [part for part in selected if compatibility(part)][:2]
    if compatible:
        core = next((part for part in selected if action(part)), None)
        bundle = list(dict.fromkeys(([core] if core else []) + compatible))
        combined = joined(bundle, "\n")
        selected = [combined] + [part for part in selected if part not in bundle]
    return selected


def _render_required_cells(cells, headers):
    return "\n\n".join(header + "\n".join(
        f"- {cell['field']}: {cell['text']}" for cell in cells
        if cell['doc_id'] == doc_id and cell['text'])
        for doc_id, header in headers.items()
        if any(cell['doc_id'] == doc_id and cell['text'] for cell in cells))


def _admit_required_cells(cells, headers, candidates, budget, contract, trace):
    """Overflow only: reuse ranked field units, reserving breadth before depth.

    Units are the existing whole field paragraphs/ordered section associations,
    never arbitrary character slices or generated summaries. Header/label costs
    are charged only when a unit is admitted, including every separator.
    """
    from services.requested_propositions import proposition_pattern
    ranks = {evidence_key(c['item']): i for i, c in enumerate(candidates)}
    items = {evidence_key(c['item']): c['item'] for c in candidates}
    entries = [(cell, part) for cell in cells for part in cell['parts'] if cell['origins'].get(part)]
    entries.sort(key=lambda pair: (
        not bool(pair[0]['origins'][pair[1]] & pair[0]['primary_keys']),
        len(pair[1].split()) <= 8,
        min(ranks[key] for key in pair[0]['origins'][pair[1]])))
    for cell in cells:
        cell['text'], cell['included_parts'] = '', []
        cell['excluded_parts'] = {}
    compared = set(contract.explicit_document_ids()) if contract else set()
    entity_scoped = len(compared) > 1 or getattr(contract, 'mode', None) in {'catalog', 'filter', 'comparison'}
    seen = set()

    def admit(cell, part, reason):
        if part in cell['included_parts']:
            return True
        # Identical facts remain separately attributable for explicit comparisons.
        signature = (cell['doc_id'] if entity_scoped else None, re.sub(r'\s+', ' ', part).casefold())
        if signature in seen:
            cell['excluded_parts'][part] = 'excluded_duplicate_depth'
            return False
        previous = cell['text']
        cell['text'] = ' '.join(filter(None, [previous, part]))
        if len(_render_required_cells(cells, headers)) > budget:
            cell['text'] = previous
            cell['excluded_parts'][part] = 'excluded_context_budget'
            if trace:
                for key in cell['origins'][part]:
                    trace.candidate(items[key], 'required_context').decision('required_context', 'required_item_exceeds_budget')
            return False
        cell['included_parts'].append(part)
        cell['excluded_parts'].pop(part, None)
        seen.add(signature)
        if trace:
            for key in cell['origins'][part]:
                trace.candidate(items[key], 'required_context').decision('required_context', reason)
        return True

    # Same proposition contract and candidate rank as recall/reviewer reservation.
    # Prefer its explicit contradicting references when answering a condition.
    for proposition in getattr(contract, 'requested_propositions', []):
        if proposition.support_state == 'applicability_unresolved':
            continue
        pattern = proposition_pattern(proposition)
        applicable = [cell for cell in cells
                      if (proposition.applicable_entity is None or cell['doc_id'] == proposition.applicable_entity)
                      and (not proposition.requested_field or cell['field'] == proposition.requested_field)]
        if pattern and any(pattern.search(part) for cell in applicable for part in cell['included_parts']):
            continue
        matches = [(cell, part) for cell, part in entries if cell in applicable and pattern and pattern.search(part)]
        contradictions = {tuple(key) for key in proposition.contradicting_candidate_ids}
        matches.sort(key=lambda pair: not bool(pair[0]['origins'][pair[1]] & contradictions))
        for cell, part in matches:
            if admit(cell, part, 'admitted_required_proposition'):
                break
    # One explicit field before repeated documents/paragraphs for that field.
    for field in dict.fromkeys(cell['field'] for cell in cells):
        if not any(cell['included_parts'] for cell in cells if cell['field'] == field):
            for cell, part in entries:
                if cell['field'] == field and admit(cell, part, 'admitted_required_field'):
                    break
    # Preserve reviewer contradictions independently of ordinary ranked depth.
    contradictions = {tuple(key) for key in (trace.reviewer_outcome.get('contradictory_candidate_ids', []) if trace else [])}
    for cell, part in entries:
        if cell['origins'][part] & contradictions:
            admit(cell, part, 'admitted_contradiction')
    # The existing matrix supplies entity/field breadth; only then add depth.
    for cell in cells:
        if not cell['included_parts']:
            for part in cell['parts']:
                if cell['origins'].get(part) and admit(cell, part, 'admitted_required_field'):
                    break
    for cell, part in entries:
        admit(cell, part, 'admitted_ranked_depth')
    # Absence markers cannot crowd out facts or stand in for factual context.
    for cell in cells:
        if not cell['text'] and not cell['origins'] and any(c['included_parts'] for c in cells if c['doc_id'] == cell['doc_id']):
            cell['text'] = cell['parts'][0]
            if len(_render_required_cells(cells, headers)) > budget:
                cell['text'] = ''


def _assemble_required_context(candidates: list[dict], fields: list[str], budget: int, trace=None, contract=None) -> tuple[list[dict], str]:
    """Reserve one value per entity/field before optional text consumes budget."""
    grouped = {}
    for candidate in candidates:
        item = candidate["item"]
        if item.get("required_fields"):
            grouped.setdefault(int(getattr(item["document"], "id", 0)), []).append(item)
    cells = []
    headers = {}
    for doc_id, items in grouped.items():
        doc = items[0]["document"]
        title = getattr(doc, "title", None) or getattr(doc, "filename", "")
        url = getattr(doc, "canonical_url", None) or getattr(doc, "source_url", "")
        headers[doc_id] = f"### Source: {title} | URL: {url}\n"
        coverage = items[0].get("field_coverage", {})
        detail_items = [item for item in items if "entity_detail" in item.get("required_fields", [])]
        for field in (["entity_detail"] if detail_items else []) + fields:
            if field == "link" and url:
                continue  # The canonical header is already the supplied value.
            evidence = [item for item in items if field in item.get("required_fields", [])]
            structured = [value for item in evidence for value in (getattr(item["chunk"], "metadata_json", {}) or {}).get("structured_fields", []) if value.get("field") == field]
            # Structured values augment a field section; they do not replace
            # other supported options or qualifications in its body text.
            textual_evidence = [item for item in evidence if not (getattr(item["chunk"], "metadata_json", {}) or {}).get("structured_fields")]
            origins = {}
            for item in evidence:
                for value in (getattr(item["chunk"], "metadata_json", {}) or {}).get("structured_fields", []):
                    if value.get("field") == field:
                        origins.setdefault(str(value["display_value"]), set()).add(evidence_key(item))
            parts = list(dict.fromkeys([str(value["display_value"]) for value in structured]
                                       + _required_field_parts(textual_evidence, field, origins, preserve_links='link' in fields, usage_query=getattr(contract, 'original_query', ''))))
            if not parts and detail_items:
                parts = _required_field_parts(detail_items, field, origins, preserve_links='link' in fields, usage_query=getattr(contract, 'original_query', ''))
                evidence = detail_items
            if not parts and coverage.get(field) == "SUPPORTED":
                # The same admitted document may state this value in another
                # required field's section. Reuse its verbatim evidence and
                # origins before emitting a contradictory missing-value cell.
                parts = _required_field_parts(items, field, origins, preserve_links='link' in fields, usage_query=getattr(contract, 'original_query', ''))
                if parts:
                    evidence = items
            if not parts:
                parts = ["Unavailable after the field search." if coverage.get(field) == "ABSENT_AFTER_ADEQUATE_SEARCH" else "No concrete value supplied; do not infer one."]
            cells.append({"doc_id": doc_id, "field": field, "parts": parts, "text": "",
                          "primary_keys": _primary_field_keys(evidence, field),
                          "origins": origins, "included_parts": [],
                          "score": max((float(item.get("score") or 0) for item in evidence), default=0.0),
                          "continuation": len(evidence) > 1})
    overhead = sum(len(header) + 1 for header in headers.values()) + sum(len(cell["field"]) + 5 for cell in cells)
    remaining = max(0, budget - overhead)
    # Fair first allocation across the complete matrix. Short values release
    # budget to longer values; no entity can consume it before another gets a slot.
    pending = list(cells)
    while pending and remaining:
        share = remaining // len(pending)
        short = [cell for cell in pending if len(cell["parts"][0]) <= share]
        if not short:
            break
        for cell in short:
            cell["text"] = cell["parts"][0]
            cell["included_parts"].append(cell["parts"][0])
            remaining -= len(cell["text"])
            pending.remove(cell)
    # Add whole supplemental paragraphs only after every matrix cell has a value.
    for cell in ([] if pending else sorted(cells, key=lambda value: (not value["continuation"], -value["score"]))):
        for part in cell["parts"][1:]:
            addition = " " + part
            if len(addition) <= remaining:
                cell["text"] += addition
                cell["included_parts"].append(part)
                remaining -= len(addition)
    text = _render_required_cells(cells, headers)
    if pending or len(text) > budget:
        _admit_required_cells(cells, headers, candidates, budget, contract, trace)
        text = _render_required_cells(cells, headers)
    all_items = {evidence_key(item): item for items in grouped.values() for item in items}
    included_keys = set()
    included_text = {}
    included_fields = {}
    for cell in cells:
        for part in cell["parts"]:
            included = part in cell["included_parts"]
            for key in cell["origins"].get(part, set()):
                if included:
                    included_keys.add(key)
                    included_text.setdefault(key, []).append(part)
                    included_fields.setdefault(key, {}).setdefault(cell['field'], []).append(part)
                if trace:
                    candidate = trace.candidate(all_items[key], "required_context")
                    omission = cell.get('excluded_parts', {}).get(part, 'excluded_context_budget')
                    name = "included_field_parts" if included else ("duplicate_field_parts" if omission == 'excluded_duplicate_depth' else "budget_omitted_field_parts")
                    counts = candidate.indicators.setdefault(name, {})
                    counts[cell["field"]] = counts.get(cell["field"], 0) + 1
                    if not included and omission == 'excluded_context_budget':
                        candidate.indicators["truncated_context_budget"] = True
    if trace:
        from services.requested_propositions import proposition_pattern
        attempted, admitted, excluded = [], [], []
        for proposition in getattr(contract, 'requested_propositions', []):
            pattern = proposition_pattern(proposition)
            if not pattern or proposition.support_state == 'applicability_unresolved':
                continue
            matches = [(cell, part) for cell in cells for part in cell['parts']
                       if (proposition.applicable_entity is None or cell['doc_id'] == proposition.applicable_entity)
                       and (not proposition.requested_field or cell['field'] == proposition.requested_field)
                       and cell['origins'].get(part) and pattern.search(part)]
            if matches:
                attempted.append(proposition.id)
                (admitted if any(part in cell['included_parts'] for cell, part in matches) else excluded).append(proposition.id)
        trace.context_assembly.update(required_proposition_representatives_attempted=attempted,
            required_proposition_representatives_admitted=admitted,
            required_proposition_representatives_excluded=excluded)
        for key, item in all_items.items():
            trace.candidate(item, 'required_context').indicators['requested_propositions'] = list(item.get('requested_propositions', []))
            if key not in included_keys:
                reason = ("excluded_context_budget" if trace.candidate(item, "required_context").indicators.get("budget_omitted_field_parts")
                          else ("excluded_duplicate_depth" if trace.candidate(item, "required_context").indicators.get('duplicate_field_parts') else "excluded_field_condensation"))
                trace.decide(item, "required_context", reason)
    result = []
    for key, item in all_items.items():
        if key not in included_keys:
            continue
        field_view = included_fields[key]
        # The canonical URL is supplied by the admitted source header, not a
        # body-text keyword. Never certify an omitted source's navigation.
        url = getattr(item['document'], 'canonical_url', None) or getattr(item['document'], 'source_url', '')
        if 'link' in fields and url and headers[key[0]].strip() in text:
            field_view = dict(field_view, link=[url])
        result.append(dict(item, context_evidence_text='\n\n'.join(dict.fromkeys(included_text[key])),
                           context_field_evidence=field_view))
    return result, text if included_keys else ''


def compress_and_rerank_chunks(
    retrieved: List[Dict[str, Any]],
    query: str,
    max_context_chars: int = POLICY.default_context_chars,
    mode: Optional[str] = None,
    query_contract: Any = None,
    trace: ChatTrace | None = None,
) -> Tuple[List[Dict[str, Any]], str]:
    """
    Reranks retrieved candidates using semantic score + exact keyword/term overlap,
    filters duplicates, preserves document/entity diversity for catalog/comparison,
    and assembles structure-preserving context with source attribution.
    """
    rt = trace.retrieval if trace else None
    if rt:
        rt.context_assembly = dict(retained_evidence_count_before_context=len(retrieved),
            context_budget_chars=max_context_chars, evidence_existed_before_context=bool(retrieved),
            required_proposition_representatives_attempted=[], required_proposition_representatives_admitted=[],
            required_proposition_representatives_excluded=[])
        rt.stage("context_input", retrieved)
    if not retrieved:
        if rt:
            rt.context([])
        return [], ""
    # Cached/previous-stage rows remain immutable to context-only boosts.
    retrieved = [dict(item, selection_signals=dict(item.get("selection_signals", {}))) for item in retrieved]

    query_tokens = set(re.findall(r"[a-z0-9']+", query.lower()))
    requested_fields = (
        list(getattr(query_contract, "requested_fields", None) or [])
        or extract_requested_fields(query)
    )
    filter_attributes = extract_filter_attributes(query)
    include_attributes = [
        token for value in filter_attributes.get("include", [])
        for token in re.findall(r"[a-z0-9][a-z0-9'-]*", value.lower())
        if token not in {"and", "or"}
    ]
    exclude_attributes = [
        token for value in filter_attributes.get("exclude", [])
        for token in re.findall(r"[a-z0-9][a-z0-9'-]*", value.lower())
        if token not in {"and", "or"}
    ]
    review_query = "reviews" in requested_fields or bool(re.search(
        r"\b(?:reviews?|ratings?|customers? say|testimonials?|feedback)\b", query, re.I
    ))
    recommendation_query = bool(re.search(
        r"\b(?:recommend|recommended|you may also like|alternatives?)\b", query, re.I
    ))
    action_query = bool(re.search(
        r"\b(?:buy|purchase|order|book|booking|schedule|reserve|tour|enroll|register|subscribe|checkout)\b",
        query,
        re.I,
    ))
    catalog_request_tokens = {
        "what", "which", "all", "other", "available", "different", "list",
        "show", "give", "name", "have", "offer", "sell", "provide", "stock",
        "carry", "items", "products", "services", "offerings", "options",
        "models", "types", "kinds", "ones", "treatments", "courses", "degrees",
        "programs", "plans", "packages", "dishes", "meals", "tours", "listings",
        "units", "solutions", "amenities", "features", "specialties", "you", "your", "we", "our",
        "do", "does", "are", "is", "for", "of", "in", "from", "the", "a",
        "an", "well", "me",
    }
    catalog_focus_tokens = query_tokens.difference(catalog_request_tokens)
    catalog_focus_tokens.update(
        token[:-1] for token in list(catalog_focus_tokens)
        if token.endswith("s") and len(token) > 4
    )
    query_numbers = set(re.findall(r"\b\d+(?:\.\d+)?(?:[a-zA-Z]+)?\b", query.lower()))
    cleaned = []
    seen_texts: set[str] = set()

    for item in retrieved:
        chunk = item.get("chunk")
        content = evidence_text(item).strip()

        if not content:
            if rt:
                rt.decide(item, "context_validation", "excluded_invalid_evidence")
            continue

        content_lower = content.lower()
        content_tokens = set(re.findall(r"[a-z0-9']+", content_lower))

        chunk_metadata = getattr(chunk, "metadata_json", {}) if hasattr(chunk, "metadata_json") else (chunk.get("metadata_json", {}) if isinstance(chunk, dict) else {})
        if _context_cross_sell(content, chunk_metadata if isinstance(chunk_metadata, dict) else {}) and not recommendation_query:
            if rt:
                rt.decide(item, "context_validation", "excluded_source_attribution")
            continue
        exclusion_penalty = 0.0
        if mode == "filter" and include_attributes:
            has_include = any(term in content_lower for term in include_attributes)
            has_exclude = any(term in content_lower for term in exclude_attributes)
            # Keep secondary field chunks from an already qualified document,
            # but never promote an incompatible product-card/form block.
            if has_exclude and not has_include:
                exclusion_penalty = -POLICY.context_excluded_term_penalty

        # Token overlap
        overlap = len(query_tokens.intersection(content_tokens)) if query_tokens else 0

        # Number / spec match bonus (e.g. 5000mAh, 16GB, $29)
        number_bonus = 0.0
        for num in query_numbers:
            if num in content_lower:
                number_bonus += 0.08

        # Exact phrase match bonus
        phrase_bonus = 0.12 if query.lower().strip() in content_lower else 0.0

        original_score = float(item.get("score") or 0.0)
        field_bonus = sum(
            0.10 for field in requested_fields
            if field_evidence_pattern(field).search(content)
        )
        include_bonus = 0.22 if include_attributes and any(term in content_lower for term in include_attributes) else 0.0
        review_adjustment = 0.0
        if re.search(r"\b(?:verified reviewer|real customers|what people are saying|rated \d|reviews?)\b", content, re.I):
            review_adjustment = 0.18 if review_query else -0.30
        noise_penalty = 0.18 if re.search(
            r"^\s*\[?skip to (?:main )?content|\bsubscribe\s*&?\s*save\b|"
            r"\bmoney-back guarantee\b|\bquality certification\b",
            content,
            re.I,
        ) else 0.0
        boosted_score = original_score + signals(item, "context_ranking", {
            "lexical_term_match": 0.0 if item.get("lexical_backend") == "postgres_fts" else overlap * 0.02,
            "numeric_match": 0.0 if item.get("lexical_backend") == "postgres_fts" else number_bonus,
            "entity_exact_match": 0.0 if item.get("lexical_backend") == "postgres_fts" else phrase_bonus,
            "requested_field_match": field_bonus,
            "entity_alias_match": include_bonus, "review_section": review_adjustment,
            "navigation_noise": -noise_penalty, "excluded_term_mention": exclusion_penalty,
            "reviewer_rank": 0.5 / (1 + int(item["semantic_review_rank"])) if "semantic_review_rank" in item else 0.0,
        }, rt)

        cleaned.append({
            "item": item,
            "score": boosted_score,
            "evidence_priority": float(item.get("evidence_priority") or 0.0),
            "content": content,
        })

    if rt:
        rt.stage("context_validated", [candidate["item"] for candidate in cleaned])
    explicit_ids = []
    if query_contract is not None and hasattr(query_contract, "explicit_document_ids"):
        explicit_ids = [int(doc_id) for doc_id in query_contract.explicit_document_ids() if doc_id]
    if explicit_ids and len(explicit_ids) >= 2 and not recommendation_query:
        filtered = []
        for candidate in cleaned:
            doc_obj = candidate["item"].get("document")
            doc_id = int(getattr(doc_obj, "id", 0) or 0)
            if doc_id in explicit_ids:
                filtered.append(candidate)
            elif rt:
                rt.decide(candidate["item"], "context_scope", "excluded_document_scope")
        cleaned = filtered

    def _allocation_pass(candidate: Dict[str, Any]) -> int:
        if float(candidate.get("evidence_priority") or 0.0) >= 0.24:
            return 0
        doc_obj = candidate["item"].get("document")
        doc_id = int(getattr(doc_obj, "id", 0) or 0)
        if explicit_ids and doc_id in explicit_ids:
            return 1
        return 2

    cleaned.sort(
        key=lambda x: (
            _allocation_pass(x), -x["evidence_priority"],
            adjacent_only_rank(x["item"]), -x["score"], evidence_key(x["item"]),
        ),
    )
    if rt:
        rt.stage("context_ranked", [candidate["item"] for candidate in cleaned])
    distinct = []
    for candidate in cleaned:
        signature = (evidence_key(candidate["item"])[0], re.sub(r"\s+", " ", candidate["content"]).lower())
        if signature in seen_texts:
            if rt:
                rt.decide(candidate["item"], "context_selection", "excluded_duplicate")
            continue
        seen_texts.add(signature)
        distinct.append(candidate)
    cleaned = distinct
    if rt:
        rt.stage("context_distinct", [candidate["item"] for candidate in cleaned])

    # When a catalog request names a concrete offering type and the evidence
    # contains structured item headings for that type, enumerate those items
    # instead of interleaving pages that merely mention the word in prose.
    catalog_uses_structured_items = False
    if mode in ("catalog", "filter") and catalog_focus_tokens:
        structured_matches = []
        for candidate in cleaned:
            heading_match = re.search(
                r"(?:^|\n)(#{2,4}\s+\[[^\]]+\]\(https?://[^)]+\)[^\n]*)",
                candidate["content"],
            )
            heading = heading_match.group(1).lower() if heading_match else ""
            if heading and any(token in heading for token in catalog_focus_tokens):
                structured_matches.append(candidate)
        if len(structured_matches) >= 2 and not any(c["item"].get("required_fields") for c in cleaned):
            # Heading identity improves order; ordinary matching descriptions
            # remain eligible for the same bounded context allocation.
            cleaned = structured_matches + [c for c in cleaned if c not in structured_matches]
            if rt:
                for candidate in structured_matches:
                    rt.candidate(candidate["item"], "context_ranking").indicators["heading_match"] = True
            catalog_uses_structured_items = True

    # For catalog, filter, and comparison modes, interleave to prevent a single document dominating
    has_required_evidence = any(c["item"].get("required_fields") for c in cleaned)
    if mode in ("catalog", "filter", "comparison") and len(cleaned) > 4:
        # Requested catalog facts have their own bounded field reservation.
        # They must not consume (or remove) the ordinary optional-document slot.
        reserved_catalog = [c for c in cleaned if c["item"].get("required_fields")] if (
            mode == "catalog" and not catalog_uses_structured_items) else []
        reserved_keys = {evidence_key(c["item"]) for c in reserved_catalog}
        doc_grouped: Dict[str, List[Dict[str, Any]]] = {}
        for c in cleaned:
            if evidence_key(c["item"]) in reserved_keys:
                continue
            doc_obj = c["item"].get("document")
            doc_key = str(getattr(doc_obj, "id", "") or "default")
            doc_grouped.setdefault(doc_key, []).append(c)

        interleaved: List[Dict[str, Any]] = list(reserved_catalog)
        max_depth = max((len(v) for v in doc_grouped.values()), default=0)
        if mode == "catalog" and not catalog_uses_structured_items:
            max_depth = 1
        elif mode in ("filter", "comparison") and len(requested_fields) < 2 and not has_required_evidence:
            max_depth = min(max_depth, 2)
        for depth_idx in range(max_depth):
            for doc_key in doc_grouped:
                if depth_idx < len(doc_grouped[doc_key]):
                    interleaved.append(doc_grouped[doc_key][depth_idx])
        if rt:
            retained = {evidence_key(c["item"]) for c in interleaved}
            for candidate in cleaned:
                if evidence_key(candidate["item"]) not in retained:
                    rt.decide(candidate["item"], "context_selection", "excluded_document_cap")
        cleaned = interleaved

    if rt:
        rt.stage("context_fair_allocation", [candidate["item"] for candidate in cleaned])
    # Assemble structured context up to max_context_chars
    context_blocks: List[str] = []
    used_chars = 0
    top_items: List[Dict[str, Any]] = []
    if requested_fields and has_required_evidence:
        top_items, reserved_context = _assemble_required_context(cleaned, requested_fields, max_context_chars, rt, query_contract)
        context_blocks = [reserved_context] if reserved_context else []
        used_chars = len(reserved_context)
        if rt:
            reserved = {evidence_key(item) for item in top_items}
            for candidate in cleaned:
                if (candidate["item"].get("required_fields") and evidence_key(candidate["item"]) not in reserved
                        and not (rt.candidate(candidate["item"], "required_context").final_reason or "").startswith("excluded_")):
                    rt.decide(candidate["item"], "required_context", "excluded_context_budget")
        cleaned = [c for c in cleaned if not c["item"].get("required_fields")]
    context_doc_keys = []
    for candidate in cleaned:
        candidate_doc = candidate["item"].get("document")
        candidate_key = str(getattr(candidate_doc, "id", "") or "default")
        if candidate_key not in context_doc_keys:
            context_doc_keys.append(candidate_key)
    per_doc_budget = max_context_chars
    if mode in ("catalog", "filter", "comparison") and len(context_doc_keys) > 1 and (mode == "catalog" or len(requested_fields) < 2):
        per_doc_budget = max(POLICY.min_document_context_chars, max_context_chars // len(context_doc_keys))
    doc_chars: Dict[str, int] = {}

    for c in cleaned:
        raw_text = re.sub(r"\[Skip to Content\]\([^)]*\)", "", c["content"], flags=re.IGNORECASE).strip()
        raw_text = _condense_primary_detail(raw_text, requested_fields)
        if len(requested_fields) >= 2 and c["evidence_priority"] >= 0.24:
            # Image URLs are not field values; keep their labels so required
            # text sections fit without sacrificing later entity/field rows.
            raw_text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", raw_text)
        if not raw_text:
            if rt:
                rt.decide(c["item"], "context_validation", "excluded_invalid_evidence")
            continue

        # Filter out standalone table-of-content link blocks (e.g. "[Eligibility for Returns](...) [Conditions for Return](...)")
        if re.search(r"^(\[[^\]]+\]\(https?://[^\)]+\)\s*){2,}$", raw_text):
            if rt:
                rt.decide(c["item"], "context_validation", "excluded_navigation_only")
            continue

        # Short factual values and heading/value pairs are valid evidence.
        # Only a standalone document identity is structural noise.
        doc_identity = getattr(c["item"].get("document"), "title", None) or getattr(c["item"].get("document"), "filename", "")
        if raw_text.strip(" #[]\n\t").casefold() == str(doc_identity).strip().casefold():
            if rt:
                rt.decide(c["item"], "context_validation", "excluded_heading_only")
            continue

        doc_obj = c["item"].get("document")
        doc_title = ""
        source_url = ""
        if doc_obj:
            if hasattr(doc_obj, "title") and getattr(doc_obj, "title"):
                doc_title = getattr(doc_obj, "title")
            elif hasattr(doc_obj, "filename") and getattr(doc_obj, "filename"):
                doc_title = getattr(doc_obj, "filename")
            if hasattr(doc_obj, "source_url") and getattr(doc_obj, "source_url"):
                source_url = getattr(doc_obj, "source_url")
        doc_key = str(getattr(doc_obj, "id", "") or "default")

        header_line = ""
        if doc_title and source_url:
            header_line = f"### Source: {doc_title} | URL: {source_url}"
        elif doc_title:
            header_line = f"### Source: {doc_title}"
        elif source_url:
            header_line = f"### URL: {source_url}"

        # Attach CTA links from chunk metadata if available
        chunk_obj = c["item"].get("chunk")
        chunk_meta = getattr(chunk_obj, "metadata_json", {}) if hasattr(chunk_obj, "metadata_json") else {}
        cta_links = chunk_meta.get("cta_links", []) if isinstance(chunk_meta, dict) else []
        cta_str = ""
        if cta_links:
            cta_items = []
            for cta in cta_links[:2]:
                if isinstance(cta, dict) and cta.get("url"):
                    cta_url = str(cta["url"]).strip()
                    cta_label = str(cta.get("text") or cta.get("label") or "View").strip()
                    canonical_match = bool(source_url) and cta_url.split("#", 1)[0].rstrip("/") == source_url.split("#", 1)[0].rstrip("/")
                    label_norm = set(re.findall(r"[a-z0-9]+", cta_label.lower()))
                    title_norm = set(re.findall(r"[a-z0-9]+", doc_title.lower()))
                    label_match = bool(label_norm and title_norm and len(label_norm & title_norm) >= max(1, min(2, len(title_norm))))
                    if mode == "purchase" or action_query or canonical_match or label_match:
                        cta_items.append(f"{cta_label}: {cta_url}")
            if cta_items:
                cta_str = "\nActionable Links: " + " | ".join(cta_items)

        remaining_global = max_context_chars - used_chars - (7 if context_blocks else 0)
        remaining_doc = per_doc_budget - doc_chars.get(doc_key, 0)
        available = min(remaining_global, remaining_doc)
        header_cost = len(header_line) + len(cta_str) + 2
        if available <= header_cost:
            if rt:
                rt.decide(c["item"], "context_budget", "excluded_context_budget")
            continue
        original_length = len(raw_text)
        raw_text = _trim_evidence(raw_text, available - header_cost)
        if not raw_text:
            if rt:
                rt.decide(c["item"], "context_budget", "excluded_context_budget")
            continue
        if rt and original_length > available - header_cost:
            rt.candidate(c["item"], "context_budget").indicators["truncated_context_budget"] = True
        block_str = f"{header_line}\n{raw_text}{cta_str}" if header_line else f"{raw_text}{cta_str}"
        block_len = len(block_str)
        sep_len = 7 if context_blocks else 0

        if used_chars + block_len + sep_len > max_context_chars and context_blocks:
            if rt:
                rt.decide(c["item"], "context_budget", "excluded_context_budget")
            continue

        context_blocks.append(block_str)
        used_chars += (block_len + sep_len)
        doc_chars[doc_key] = doc_chars.get(doc_key, 0) + block_len
        top_items.append(c["item"])

    assembled_context = "\n\n---\n\n".join(context_blocks)
    if not top_items and has_required_evidence:
        # Compatibility for direct compressor callers; this is not factual
        # context and the answer path must take the technical failure terminal.
        assembled_context = "Required entity/field evidence exceeds the context budget; details are not supplied."[:max_context_chars]
    if rt:
        rt.context(top_items)
        rt.stage_counts["final_context_chars"] = len(assembled_context)
        budget_lost = any(c.indicators.get('budget_omitted_field_parts') or c.final_reason == 'excluded_context_budget'
                          for c in rt.candidates.values())
        rt.context_assembly.update(admitted_context_items=len(top_items),
            excluded_context_items=len(retrieved) - len(top_items), context_budget_exhausted=budget_lost,
            context_assembly_status=('partial' if budget_lost else 'complete') if top_items else 'failed',
            context_assembly_failure_reason=None if top_items else (
                'context_budget_exhausted' if budget_lost else 'context_validation_no_usable_evidence'))
        if not top_items:
            rt.fallback("empty_context_after_validation")
    return top_items, assembled_context


class CritiqueResult(dict):
    def __init__(self, passed, grounding_issue=False, hallucination=False, missing_business_info=False, style_issue=False, answer_relevance_issue=False, reason=""):
        super().__init__({
            "passed": passed,
            "grounding_issue": grounding_issue,
            "hallucination": hallucination,
            "missing_business_info": missing_business_info,
            "style_issue": style_issue,
            "answer_relevance_issue": answer_relevance_issue,
            "reason": reason
        })

    def __iter__(self):
        yield self["passed"]
        yield self

    def __str__(self):
        return self["reason"]


def critique_response(answer: str, question: str, strict_grounding: bool = False) -> CritiqueResult:
    """
    Evaluate generated answer before returning/streaming to user.
    """
    if not answer or not answer.strip():
        return CritiqueResult(
            passed=False,
            missing_business_info=True,
            reason="Answer is empty."
        )

    lower_answer = answer.lower()
    trimmed_ans = answer.strip().lower()

    # Heuristic 1: Question meaningful keywords check (except when answer honestly acknowledges missing info)
    is_missing_info_acknowledgment = any(
        phrase in lower_answer for phrase in (
            "not available", "don't have", "do not have", "cannot find", "no information",
            "not found", "does not appear", "does not contain", "not mentioned", "not listed"
        )
    )
    if not is_missing_info_acknowledgment:
        q_words = re.findall(r"\b[a-zA-Z0-9']{3,}\b", question.lower())
        stop_words = {
            "the", "and", "for", "are", "you", "your", "what", "how", "why", "who", "where",
            "when", "which", "this", "that", "these", "those", "there", "here", "with", "from",
            "about", "can", "could", "would", "should", "will", "shall", "does", "doesnt",
            "did", "didnt", "have", "has", "had", "please", "help", "info", "information",
            "know", "tell", "explain", "about", "product", "business"
        }
        meaningful_keywords = [w for w in q_words if w not in stop_words]
        if meaningful_keywords:
            if not any(k in lower_answer for k in meaningful_keywords):
                return CritiqueResult(
                    passed=False,
                    answer_relevance_issue=True,
                    reason="Answer does not address the question keywords."
                )

    # Heuristic 2: Repeated sentences check
    sentences = re.split(r"(?<=[.!?])\s+", answer.strip())
    seen_sents = set()
    for s in sentences:
        s_clean = s.strip().lower()
        if len(s_clean) > 8:
            if s_clean in seen_sents:
                return CritiqueResult(
                    passed=False,
                    style_issue=True,
                    reason="Answer contains duplicate sentences."
                )
            seen_sents.add(s_clean)

    # Heuristic 3: Excessive filler at the beginning
    filler_prefixes = [
        "certainly", "i'd be happy to help", "i would be happy to help",
        "of course", "as an ai"
    ]
    for p in filler_prefixes:
        if trimmed_ans.startswith(p):
            return CritiqueResult(
                passed=False,
                style_issue=True,
                reason="Answer starts with excessive filler."
            )

    # Heuristic 4: Robotic wording checks
    robotic_phrases = [
        "according to document", "the provided context", "in document 1",
        "retrieved information states", "as an ai model", "according to the context",
        "based on the retrieved information", "the uploaded documents", "the knowledge base",
        "internal documents", "source documents", "the context states"
    ]
    if any(phrase in lower_answer for phrase in robotic_phrases):
        return CritiqueResult(
            passed=False,
            grounding_issue=True,
            reason="Answer contains internal retrieval jargon."
        )

    # Heuristic 5: Very short incomplete answers check
    q_words_all = re.findall(r"\b\w+\b", question)
    ans_words_all = re.findall(r"\b\w+\b", answer)
    if len(q_words_all) > 6 and len(ans_words_all) <= 2:
        return CritiqueResult(
            passed=False,
            style_issue=True,
            reason="Answer is too short/incomplete for the question."
        )

    return CritiqueResult(passed=True, reason="Passed critique.")


def generate_proactive_followups(answer: str, question: str) -> List[str]:
    """
    Generate 1-2 natural follow-up suggestions when appropriate.
    """
    q_lower = question.lower()
    if any(k in q_lower for k in ("price", "pricing", "cost", "plan")):
        return ["Would you like to know about our enterprise discounts?", "Can I help you compare plans?"]
    if any(k in q_lower for k in ("feature", "features", "capability", "what can")):
        return ["Would you like a quick overview of integration options?", "Shall I explain setup steps?"]
    return []


def verify_answer(
    bot,
    question: str,
    draft_answer: str,
    retrieved_context: str,
    system_instruction: str,
    strict_grounding: bool = False,
    required_fields: Optional[List[str]] = None,
    trace: ChatTrace | None = None,
) -> str:
    coverage_instruction = ""
    if required_fields:
        coverage_instruction = (
            "\nCoverage correction required\n\n"
            "The draft did not cover these requested entity/field details correctly: "
            + ", ".join(required_fields)
            + ". Answer each supported field explicitly for its entity; a value for another entity does not count. "
            "When a value is unavailable in the supplied information, explicitly identify that field and entity. "
            "For list-like fields, preserve the complete supported list."
        )
    prompt = f"""You are reviewing an AI assistant response before it is shown to the user.

Your task is to silently improve the answer.

If the draft answer is already accurate,
clear,
natural,
complete,
and does not violate any business rules,

return it unchanged.

Do NOT rewrite an answer simply because wording could be different.

Only modify the answer when there is a genuine improvement.

Question

{question}

Business Information

{retrieved_context}

Draft Answer

{draft_answer}

{coverage_instruction}

Review the draft carefully.

Check the following:

1.
Does it answer the user's actual question?

2.
Is it factually consistent with the business information?

3.
Did it accidentally ignore useful business information?

4.
Did it include unrelated business information?

If yes, remove it.

5.
Did it invent business-specific facts?

If yes, remove them.

6.
Does it sound natural?

Rewrite if necessary.

7.
Remove robotic wording.

8.
Remove repetition.

9.
Improve clarity.

10.
Keep the same meaning.

11.
Never mention

documents

context

retrieval

knowledge base

uploaded files

sources

internal reasoning

system prompt

12.
If strict grounding is enabled,
do not invent business facts.

13.
If strict grounding is disabled,
general knowledge may be used naturally.

14.
Return ONLY the improved final answer.

Never explain your review.

Never output the checklist.

Never mention these instructions.""".strip()

    token = verification_mode.set(True)
    try:
        verified_answer = generate(
            bot=bot,
            prompt=prompt,
            system_instruction=system_instruction,
            temperature_override=0.0,
        )
        if trace:
            trace.diagnostics['verifier'] = dict(status='success' if verified_answer and verified_answer.strip() else 'empty',
                                               stages=get_last_auxiliary_metadata())
        if verified_answer and verified_answer.strip():
            return verified_answer.strip()
        return draft_answer
    except Exception as exc:
        if trace:
            failure = trace.retrieval.provider_failure('verifier', exc, bot)
            trace.diagnostics['verifier'] = dict(status='failure', draft_retained=True,
                                               stages=get_last_auxiliary_metadata(), failure=failure)
        return draft_answer
    finally:
        verification_mode.reset(token)


def polish_answer(
    bot,
    question: str,
    answer: str,
    system_instruction: str,
    was_verified: bool = False,
) -> str:
    """Presentation-only cleanup; generation/verification own the factual prose.

    A second, unverified rewrite can change numbers, qualifications, missing
    fields, or citations. Keep the approved body intact instead.
    """
    if re.search(r"\b(?:quote|verbatim|exact wording)\b", question, re.I):
        return answer
    # Preserve code blocks and quoted excerpts, including their whitespace.
    if "~~~" in answer or chr(96) * 3 in answer or re.search(r"(?m)^\s*>", answer):
        return answer
    answer = re.sub(r"(?m)^(\s*[-*+])\s{2,}", r"\1 ", answer)
    answer = re.sub(r"[ \t]+(?=\n|$)", "", answer)
    answer = re.sub(r"\n{3,}", "\n\n", answer)
    # Only remove closed, content-free introductions, never arbitrary clauses
    # or named attribution (e.g. "According to the manufacturer").
    preamble = re.compile(
        r"^(?:(?:certainly|sure|great question|i['’]d be happy to help)[!,:.]\s+"
        r"|(?:according to|based on) (?:the )?"
        r"(?:provided context|knowledge base|retrieved chunks|supplied documents)"
        r"[, :]+\s*"
        r"|the (?:provided context|knowledge base|retrieved chunks|supplied documents)"
        r" (?:states?|says?|indicates?)(?: that |[:]\s*))",
        re.I,
    )
    for _ in range(4):
        cleaned = preamble.sub("", answer, count=1)
        if not cleaned.strip() or cleaned == answer:
            break
        answer = cleaned
    return answer.strip()
