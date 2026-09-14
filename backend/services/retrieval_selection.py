"""Rank-first selection policy; authorization is established before selection.

Raw cosine is a ranking diagnostic, never an evidence-existence predicate.
Budgets reuse the adaptive recall pool and character-based context limits.
"""
from dataclasses import dataclass
import math
import re

from services.observability_service import RetrievalTrace, evidence_key


@dataclass(frozen=True)
class SelectionPolicy:
    reviewer_max: int = 48
    expansion_seed_max: int = 20
    default_context_chars: int = 10000
    comparison_context_chars: int = 9500
    min_document_context_chars: int = 1100
    reviewer_preview_chars: int = 18000
    reviewer_chunk_preview_chars: int = 2400
    # Existing attribute-ranking scale; a mention is a penalty, never exclusion.
    excluded_term_penalty: float = 0.45
    context_excluded_term_penalty: float = 0.22

    def context_budget(self, mode: str, params: dict) -> int:
        value = int(params.get("context_budget", self.default_context_chars))
        return max(value, self.comparison_context_chars) if mode == "comparison" else max(0, value)

    def select(self, items: list[dict], limit: int, per_document: int,
               preferred_documents=(), trace: RetrievalTrace | None = None) -> list[dict]:
        """Keep the best eligible ranks even when every similarity is low.

        At least one representative per compared/preferred document precedes
        additional depth. No score gap or absolute threshold deletes evidence.
        """
        ranked = sorted(items, key=lambda item: (-number(item.get("evidence_priority")), adjacent_only_rank(item), -number(item.get("score")), evidence_key(item)))
        # Each requested clause gets a representative before duplicate depth.
        # Reserve ahead of per-document caps too, not only after truncation.
        reserved = []
        # Bundles originate in bounded, authorized per-document field search.
        # Reserve every dependency before rank/depth caps; never return a
        # fragment as a complete section when the whole bundle cannot fit.
        by_key = {evidence_key(item): item for item in ranked}
        groups, blocked, counts_reserved = {}, set(), {}
        for item in ranked:
            for bundle in item.get('evidence_bundles', [])[:12]:
                key = (bundle['document_id'], bundle['field'])
                groups.setdefault(key, bundle)
        for (doc_id, field), bundle in sorted(groups.items()):
            keys = [(doc_id, cid) for cid in bundle['chunk_ids'][:5]]
            members = [by_key[k] for k in keys if k in by_key]
            fresh = [m for m in members if m not in reserved]
            if (len(members) != len(keys) or not members
                    or counts_reserved.get(doc_id, 0) + len(fresh) > per_document
                    or len(reserved) + len(fresh) > limit):
                blocked.update(keys)
                # A complete standalone numeric answer is an alternative proof,
                # not a fragment of the heading/body dependency. Preserve it
                # when optional section depth cannot fit; never synthesize text.
                standalone = next((m for m in ranked if m in members
                                   and independently_complete_numeric_field(m, field)), None)
                if (standalone is not None and counts_reserved.get(doc_id, 0) < per_document
                        and len(reserved) < limit):
                    if standalone not in reserved:
                        reserved.append(standalone)
                        counts_reserved[doc_id] = counts_reserved.get(doc_id, 0) + 1
                    if trace:
                        trace.decide(standalone, 'selection', 'reserved_independent_field_support')
                if trace:
                    for m in members:
                        if m not in reserved: trace.decide(m, 'selection', 'excluded_bundle_budget_or_dependency')
                continue
            reserved.extend(fresh)
            counts_reserved[doc_id] = counts_reserved.get(doc_id, 0) + len(fresh)
        # A chunk shared with another admitted field remains material evidence.
        blocked.difference_update(evidence_key(m) for m in reserved)
        ranked = [m for m in ranked if evidence_key(m) not in blocked]
        field_keys = dict.fromkeys((evidence_key(item)[0], field)
                                  for item in ranked for field in item.get('required_fields', []))
        for doc_id, field in field_keys:
            if any(evidence_key(m)[0] == doc_id and field in m.get('required_fields', []) for m in reserved):
                continue
            match = next(item for item in ranked if evidence_key(item)[0] == doc_id
                         and field in item.get('required_fields', []))
            if match not in reserved:
                reserved.append(match)
        for proposition in dict.fromkeys(p for item in ranked for p in item.get("requested_propositions", [])):
            match = next((item for item in ranked if proposition in item.get("requested_propositions", [])), None)
            if match is not None and match not in reserved:
                reserved.append(match)
        ranked = reserved + [item for item in ranked if item not in reserved and item.get('required_fields')] + [item for item in ranked if item not in reserved and not item.get('required_fields')]
        seen, counts, eligible = set(), {}, []
        for item in ranked:
            content = text(item)
            doc_id, _ = evidence_key(item)
            # Identical values in different documents are distinct attribution.
            signature = (doc_id, re.sub(r"\s+", " ", content).strip().lower())
            reason = None
            if not content.strip():
                reason = "excluded_invalid_evidence"
            elif signature in seen:
                reason = "excluded_duplicate"
            elif counts.get(doc_id, 0) >= per_document:
                reason = "excluded_document_cap"
            if reason:
                if trace:
                    trace.decide(item, "selection", reason)
                continue
            seen.add(signature)
            counts[doc_id] = counts.get(doc_id, 0) + 1
            eligible.append(item)
        selected = []
        for doc_id in preferred_documents:
            match = next((item for item in eligible if evidence_key(item)[0] == doc_id), None)
            if match is not None and match not in selected and len(selected) < limit:
                selected.append(match)
        for item in reserved:
            if item in eligible and item not in selected and len(selected) < limit:
                selected.append(item)
        selected += [item for item in eligible if item not in selected][:max(0, limit - len(selected))]
        if trace:
            chosen = {evidence_key(item) for item in selected}
            for item in eligible:
                trace.decide(item, "selection", "kept_rank_floor" if evidence_key(item) in chosen else "excluded_candidate_budget")
            for item in ranked:
                obligations = list(item.get('requested_propositions', [])) or [
                    f'field:{evidence_key(item)[0]}:{field}' for field in item.get('required_fields', [])]
                if obligations:
                    candidate = trace.candidate(item, 'selection')
                    candidate.indicators['field_reservation'] = {
                        'obligations': obligations[:96], 'representative': item in reserved,
                        'reserved': item in reserved and evidence_key(item) in chosen,
                        'drop_reason': None if evidence_key(item) in chosen else candidate.final_reason}
        return selected


POLICY = SelectionPolicy()


def independently_complete_numeric_field(item, field):
    """One prose statement must bind a number to the requested field itself.

    Separate headings, isolated ranges and adjacent benefits are insufficient.
    This is an alternative selection proof, not a change to reviewer support.
    """
    from services.query_contract import field_evidence_pattern
    pattern = field_evidence_pattern(field)
    for paragraph in re.split(r'\n\s*\n|\n(?=#+\s)', text(item)[:18000]):
        if paragraph.lstrip().startswith('#'):
            continue
        for sentence in re.split(r'(?<=[.!?])\s+', paragraph):
            if (pattern.search(sentence) and re.search(r'\d', sentence)
                    and len(sentence.split()) >= 9
                    and re.search(r'\b(?:notice|report|see|develop|appear|improve|takes?|use|mix|apply|receive|arrive|delivered|complete|lasts?|within)\b', sentence, re.I)):
                return True
    return False


def adjacent_only_rank(item: dict) -> int:
    """Expansion-only defaults cannot outrank primary recall on synthetic scores.

    Explicit reviewer selection can promote adjacent evidence; reviewer failure
    cannot. Reserved section/field evidence retains its own higher priority.
    """
    return int(bool(item.get("adjacent_only")) and not item.get("semantic_review_selected", False))


def number(value) -> float:
    try:
        result = float(value or 0)
        return result if math.isfinite(result) else 0.0
    except (ValueError, TypeError):
        return 0.0


def text(item: dict) -> str:
    chunk = item.get("chunk")
    value = chunk.get("content") if isinstance(chunk, dict) else getattr(chunk, "content", None)
    return value if isinstance(value, str) else ""


def signals(item: dict, stage: str, values: dict[str, float], trace: RetrievalTrace | None = None) -> float:
    """Apply each named ranking signal once across selection/context stages."""
    applied = item.setdefault("selection_signals", {})
    current = {name: number(value) for name, value in values.items() if value and name not in applied}
    applied.update(current)
    if trace and current:
        trace.candidate(item, stage).signals[stage] = current
    return sum(current.values())
