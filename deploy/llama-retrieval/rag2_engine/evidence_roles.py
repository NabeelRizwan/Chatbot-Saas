"""Conservative roles declared by document metadata or structural headings.

These labels describe where evidence occurs, not whether its claims are true.
Body text and sentiment never determine a role.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

ROLES = frozenset({"REVIEW", "FAQ", "POLICY", "PRIMARY", "UNKNOWN"})
_HEADINGS = {
    "REVIEW": {"reviews", "customer reviews", "product reviews", "testimonials"},
    "FAQ": {"faq", "faqs", "faq s", "frequently asked questions"},
    "POLICY": {"policy", "policies", "review policy", "reviews policy", "return policy",
               "returns policy", "refund policy", "shipping policy", "privacy policy"},
    "PRIMARY": {"product details", "product description", "technical description",
                "specifications", "technical specifications", "measurements", "dimensions",
                "materials", "material", "care", "use instructions", "directions for use"},
}


def evidence_role(metadata: Mapping, headings: Sequence[str]) -> dict[str, str]:
    """Prefer exact section declarations; otherwise use an explicit source role.

    A review subtree or explicitly declared review document remains review
    evidence even if a reviewer includes a Specifications heading. Declarations
    describe source type, never verified truth. Crawled page metadata is not an
    authenticated declaration and is not passed here by the SaaS adapter.
    """
    matches = []
    for heading in headings:
        normalized = re.sub(r"[^\w]+", " ", heading.casefold()).strip()
        # Explicit policy/FAQ labels take precedence over review words appearing
        # in their subject. Questions themselves never establish review context.
        if re.search(r"\b(?:review|reviews|testimonial|testimonials) policy\b", normalized):
            matches.append(("POLICY", heading))
            continue
        if re.match(r"^(?:faqs?|frequently asked questions)\b", normalized):
            matches.append(("FAQ", heading))
            continue
        question = "?" in heading or re.match(r"^(?:how|what|when|where|why|who|which|can|does|is|are)\b", normalized)
        if not question and re.search(r"\b(?:customer reviews|testimonials)\b", normalized):
            matches.append(("REVIEW", heading))
            continue
        for role, labels in _HEADINGS.items():
            if normalized in labels:
                matches.append((role, heading))
                break
    declared = str(metadata.get("source_role", "")).strip().upper()
    # A review document cannot promote its own technical subheadings into the
    # factual-source tier. Likewise a FAQ/policy document retains that context
    # for technical subheadings; explicit review sections still take precedence.
    reviews = [item for item in matches if item[0] == "REVIEW"]
    contextual = [item for item in matches if item[0] != "PRIMARY"]
    if not reviews and (declared == "REVIEW" or
                        (declared in {"FAQ", "POLICY"} and not contextual)):
        return {"evidence_role": declared, "evidence_role_basis": "metadata:source_role"}
    if contextual or matches:
        role, heading = (reviews or contextual or matches)[-1]
        return {"evidence_role": role, "evidence_role_basis": "heading:" + heading}
    if declared in ROLES and declared != "UNKNOWN":
        return {"evidence_role": declared, "evidence_role_basis": "metadata:source_role"}
    return {"evidence_role": "UNKNOWN", "evidence_role_basis": "unclassified"}
