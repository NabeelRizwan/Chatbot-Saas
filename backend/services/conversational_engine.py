import json
import re
from time import perf_counter
from typing import Any, Dict, List, Optional, Tuple

from services.embedding_service import generate_embedding
from services.llm_router import generate
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
from services.query_contract import field_evidence_pattern


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
        label_pattern = re.compile(
            r"\b(one[- ]time(?: purchase)?|regular(?: price)?|list(?: price)?|sale(?: price)?|"
            r"subscription(?: price)?|subscribe(?:\s*&\s*save)?|bundle(?: price)?)\b",
            re.I,
        )
        for match in label_pattern.finditer(prefix):
            window = prefix[match.start():match.start() + 220]
            window_prices = list(dict.fromkeys(re.findall(r"(?:\$|₹|€|£|¥)\s*\d+(?:[.,]\d{1,2})?", window)))
            if not window_prices:
                continue
            label = re.sub(r"\s+", " ", match.group(1)).strip().title()
            price_lines.append(f"{label}: {', '.join(window_prices[:4])}")
        for amount, unit in re.findall(
            r"((?:\$|₹|€|£|¥)\s*\d+(?:[.,]\d{1,2})?)\s*/\s*(bottle|day|week|month|year|night|person|seat|license|user)",
            prefix,
            re.I,
        ):
            price_lines.append(f"Per {unit.lower()}: {amount}")
        price_lines = list(dict.fromkeys(price_lines))[:5]
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
    excerpt = text[:limit]
    boundary = max(excerpt.rfind("\n\n"), excerpt.rfind(". "))
    if boundary >= int(limit * 0.65):
        excerpt = excerpt[:boundary + 1]
    return excerpt.rstrip() + "\n[Additional page detail omitted for context allocation.]"


def _required_field_parts(items: list[dict], field: str) -> list[str]:
    """Extract verbatim field paragraphs, keeping split numeric stages together."""
    parts = []
    for item in sorted(items, key=lambda row: int(getattr(row["chunk"], "chunk_index", 0) or 0)):
        raw = str(getattr(item["chunk"], "content", "") or "")
        raw = _condense_primary_detail(raw, [field])
        raw = re.sub(r"(?m)^>.*$", "", raw)
        raw = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", raw)
        # Navigation links are not field values. Canonical URLs are kept in
        # the source header, not mixed into factual paragraph matching.
        raw = re.sub(r"(?m)^\s*(?:[-*]\s*)?(?:\[[^\]]*\]\([^)]*\)\s*)+$", "", raw)
        raw = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", raw)
        raw = re.sub(r"(?m)^\[[^\]\n]+\](?:\s*\[[^\]\n]+\])?\s*", "", raw)
        raw = re.sub(r"(?m)^#{1,6}\s*", "", raw).strip()
        parts.extend(part.strip() for part in re.split(r"\n\s*\n", raw) if part.strip())
    parts = list(dict.fromkeys(parts))
    if field == "entity_detail":
        match = next((i for i, part in enumerate(parts) if re.fullmatch(r"(?:product description|service description|overview)", part, re.I)), None)
        return parts[match + 1:match + 2] if match is not None else parts[:1]
    pattern = field_evidence_pattern(field)
    numeric_section = any(re.fullmatch(r"\d+(?:\s*[-–]\s*\d+)?\s+[a-z]+", part, re.I) for part in parts)
    if numeric_section and len(items) > 1:
        # A number at the end of one chunk belongs to the following body,
        # not the preceding stage. Keep that boundary atomic during trimming.
        units = []
        for index, part in enumerate(parts):
            if re.fullmatch(r"\d+(?:\s*[-–]\s*\d+)?\s+[a-z]+", part, re.I):
                body = parts[index + 1:index + 3]
                units.append(" ".join([part] + body))
        qualifiers = [
            part for index, part in enumerate(parts)
            if len(part.split()) > 8 and (
                pattern.search(part)
                or (index and pattern.search(parts[index - 1]) and len(parts[index - 1].split()) <= 8)
            )
        ]
        numeric_answers = [part for part in qualifiers if re.search(r"\b\d", part)]
        return list(dict.fromkeys(numeric_answers + units + qualifiers))
    selected = []
    for index, part in enumerate(parts):
        if not pattern.search(part):
            continue
        if len(part.split()) <= 6 and index + 1 < len(parts):
            following = parts[index + 1]
            if len(following.split()) > 5:
                selected.append(part + "\n" + following)
        elif len(part.split()) > 6:
            selected.append(part)
    return [part for index, part in enumerate(selected) if not any(part in prior for prior in selected[:index])]


def _assemble_required_context(candidates: list[dict], fields: list[str], budget: int) -> tuple[list[dict], str]:
    """Reserve one value per entity/field before optional text consumes budget."""
    grouped = {}
    for candidate in candidates:
        item = candidate["item"]
        if item.get("required_fields"):
            grouped.setdefault(int(getattr(item["document"], "id", 0)), []).append(item)
    cells = []
    headers = {}
    used_items = []
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
            parts = [str(value["display_value"]) for value in structured] if structured else _required_field_parts(evidence, field)
            if not parts and detail_items:
                parts = _required_field_parts(detail_items, field)
                evidence = detail_items
            if not parts:
                parts = ["Unavailable after the field search." if coverage.get(field) == "ABSENT_AFTER_ADEQUATE_SEARCH" else "No concrete value supplied; do not infer one."]
            cells.append({"doc_id": doc_id, "field": field, "parts": parts, "text": "",
                          "score": max((float(item.get("score") or 0) for item in evidence), default=0.0),
                          "continuation": len(evidence) > 1})
            used_items.extend(evidence)
    overhead = sum(len(header) + 1 for header in headers.values()) + sum(len(cell["field"]) + 5 for cell in cells)
    remaining = max(0, budget - overhead)
    # Fair first allocation across the complete matrix. Short values release
    # budget to longer values; no entity can consume it before another gets a slot.
    pending = list(cells)
    while pending and remaining:
        share = remaining // len(pending)
        short = [cell for cell in pending if len(cell["parts"][0]) <= share]
        if not short:
            return [], "Required entity/field evidence exceeds the context budget; details are not supplied."[:budget]
        for cell in short:
            cell["text"] = cell["parts"][0]
            remaining -= len(cell["text"])
            pending.remove(cell)
    # Add whole supplemental paragraphs only after every matrix cell has a value.
    for cell in sorted(cells, key=lambda value: (not value["continuation"], -value["score"])):
        for part in cell["parts"][1:]:
            addition = " " + part
            if len(addition) <= remaining:
                cell["text"] += addition
                remaining -= len(addition)
    blocks = []
    for doc_id, header in headers.items():
        lines = [f"- {cell['field']}: {cell['text'] or '[Context budget insufficient; detail not supplied]'}" for cell in cells if cell["doc_id"] == doc_id]
        blocks.append(header + "\n".join(lines))
    text = "\n\n".join(blocks)
    if len(text) > budget:
        # An impossibly small budget must not emit a truncated factual claim.
        return [], "Required entity/field evidence exceeds the context budget; details are not supplied."[:budget]
    unique = {(getattr(item["document"], "id", None), getattr(item["chunk"], "id", None)): item for item in used_items}
    return list(unique.values()), text


def compress_and_rerank_chunks(
    retrieved: List[Dict[str, Any]],
    query: str,
    max_context_chars: int = 10000,
    mode: Optional[str] = None,
    query_contract: Any = None,
) -> Tuple[List[Dict[str, Any]], str]:
    """
    Reranks retrieved candidates using semantic score + exact keyword/term overlap,
    filters duplicates, preserves document/entity diversity for catalog/comparison,
    and assembles structure-preserving context with source attribution.
    """
    if not retrieved:
        return [], ""

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
        content = chunk.content.strip() if hasattr(chunk, "content") else str(chunk.get("content", "")).strip()

        if len(content) < 10:
            continue

        normalized = re.sub(r"\s+", " ", content.lower()).strip()
        if item.get("required_fields"):
            normalized = str(getattr(item.get("document"), "id", "")) + ":" + normalized
        if normalized in seen_texts:
            continue
        seen_texts.add(normalized)

        content_lower = content.lower()
        content_tokens = set(re.findall(r"[a-z0-9']+", content_lower))

        chunk_metadata = getattr(chunk, "metadata_json", {}) if hasattr(chunk, "metadata_json") else (chunk.get("metadata_json", {}) if isinstance(chunk, dict) else {})
        if _context_cross_sell(content, chunk_metadata if isinstance(chunk_metadata, dict) else {}) and not recommendation_query:
            continue
        if mode == "filter" and include_attributes:
            has_include = any(term in content_lower for term in include_attributes)
            has_exclude = any(term in content_lower for term in exclude_attributes)
            # Keep secondary field chunks from an already qualified document,
            # but never promote an incompatible product-card/form block.
            if has_exclude and not has_include:
                continue

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
        boosted_score = original_score + (overlap * 0.02) + number_bonus + phrase_bonus + field_bonus + include_bonus + review_adjustment - noise_penalty

        cleaned.append({
            "item": item,
            "score": boosted_score,
            "evidence_priority": float(item.get("evidence_priority") or 0.0),
            "content": content,
        })

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
        if filtered:
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
            int(getattr(x["item"].get("chunk"), "chunk_index", 0) or 0)
            if x["evidence_priority"] >= 0.24 else -x["score"],
        ),
    )

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
            cleaned = structured_matches
            catalog_uses_structured_items = True

    # For catalog, filter, and comparison modes, interleave to prevent a single document dominating
    has_required_evidence = any(c["item"].get("required_fields") for c in cleaned)
    if mode in ("catalog", "filter", "comparison") and len(cleaned) > 4:
        doc_grouped: Dict[str, List[Dict[str, Any]]] = {}
        for c in cleaned:
            doc_obj = c["item"].get("document")
            doc_key = str(getattr(doc_obj, "id", "") or "default")
            doc_grouped.setdefault(doc_key, []).append(c)

        interleaved: List[Dict[str, Any]] = []
        max_depth = max(len(v) for v in doc_grouped.values())
        if mode == "catalog" and not catalog_uses_structured_items and not has_required_evidence:
            max_depth = 1
        elif mode in ("filter", "comparison") and len(requested_fields) < 2 and not has_required_evidence:
            max_depth = min(max_depth, 2)
        for depth_idx in range(max_depth):
            for doc_key in doc_grouped:
                if depth_idx < len(doc_grouped[doc_key]):
                    interleaved.append(doc_grouped[doc_key][depth_idx])
        cleaned = interleaved

    # Assemble structured context up to max_context_chars
    context_blocks: List[str] = []
    used_chars = 0
    top_items: List[Dict[str, Any]] = []
    if requested_fields and has_required_evidence:
        top_items, reserved_context = _assemble_required_context(cleaned, requested_fields, max_context_chars)
        context_blocks = [reserved_context] if reserved_context else []
        used_chars = len(reserved_context)
        cleaned = [c for c in cleaned if not c["item"].get("required_fields")]
    context_doc_keys = []
    for candidate in cleaned:
        candidate_doc = candidate["item"].get("document")
        candidate_key = str(getattr(candidate_doc, "id", "") or "default")
        if candidate_key not in context_doc_keys:
            context_doc_keys.append(candidate_key)
    per_doc_budget = max_context_chars
    if mode in ("catalog", "filter", "comparison") and len(context_doc_keys) > 1 and (mode == "catalog" or len(requested_fields) < 2):
        per_doc_budget = max(1100, max_context_chars // len(context_doc_keys))
    doc_chars: Dict[str, int] = {}

    for c in cleaned:
        raw_text = re.sub(r"\[Skip to Content\]\([^)]*\)", "", c["content"], flags=re.IGNORECASE).strip()
        raw_text = _condense_primary_detail(raw_text, requested_fields)
        if len(requested_fields) >= 2 and c["evidence_priority"] >= 0.24:
            # Image URLs are not field values; keep their labels so required
            # text sections fit without sacrificing later entity/field rows.
            raw_text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", raw_text)
        if not raw_text or len(raw_text) < 15:
            continue

        # Filter out standalone table-of-content link blocks (e.g. "[Eligibility for Returns](...) [Conditions for Return](...)")
        if re.search(r"^(\[[^\]]+\]\(https?://[^\)]+\)\s*){2,}$", raw_text):
            continue

        # If a chunk is just an isolated heading with no body (e.g. < 70 chars with no punctuation/verbs and starts with # or []), skip standalone header-only noise
        if len(raw_text) < 70 and ("\n## " in raw_text or raw_text.startswith("## ") or raw_text.startswith("# ") or raw_text.startswith("[")):
            has_compact_evidence = any(pattern.search(raw_text) for pattern in _CONTEXT_FIELD_PATTERNS.values())
            if not has_compact_evidence and not any(v in raw_text.lower() for v in (" is ", " are ", " if ", " will ", " must ", " can ", " we ", " our ", " please ", " contact ")):
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
        if available <= header_cost + 160:
            continue
        raw_text = _trim_evidence(raw_text, available - header_cost)
        block_str = f"{header_line}\n{raw_text}{cta_str}" if header_line else f"{raw_text}{cta_str}"
        block_len = len(block_str)
        sep_len = 7 if context_blocks else 0

        if used_chars + block_len + sep_len > max_context_chars and context_blocks:
            continue

        context_blocks.append(block_str)
        used_chars += (block_len + sep_len)
        doc_chars[doc_key] = doc_chars.get(doc_key, 0) + block_len
        top_items.append(c["item"])

    assembled_context = "\n\n---\n\n".join(context_blocks)
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

    import concurrent.futures

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(
            generate,
            bot=bot,
            prompt=prompt,
            system_instruction=system_instruction,
            temperature_override=0.0,
        )
        verified_answer = future.result(timeout=5.0)
        if verified_answer and verified_answer.strip():
            return verified_answer.strip()
        return draft_answer
    except (concurrent.futures.TimeoutError, Exception):
        return draft_answer
    finally:
        executor.shutdown(wait=False)


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
