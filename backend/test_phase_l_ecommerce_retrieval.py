"""Deterministic Phase L document-first retrieval contracts.

The fixtures intentionally span retail, SaaS, hospitality, and education.  No
live tenant data or external provider is used.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.conversational_engine import compress_and_rerank_chunks
from services.intent_router import (
    RETRIEVAL_MODE_CATALOG,
    RETRIEVAL_MODE_COMPARISON,
    RETRIEVAL_MODE_FILTER,
    detect_retrieval_mode,
    extract_filter_attributes,
    extract_requested_fields,
)
from services.rag_service import (
    _answer_has_no_supporting_business_fact,
    _catalog_evidence_text,
    _diverse_chunk_selection,
    _format_sources,
)


def item(
    chunk_id: int,
    doc_id: int,
    title: str,
    content: str,
    score: float = 0.85,
    metadata: dict | None = None,
) -> dict:
    return {
        "score": score,
        "match_reasons": ["fixture"],
        "chunk": SimpleNamespace(
            id=chunk_id,
            chunk_index=chunk_id,
            content=content,
            token_count=40,
            metadata_json=metadata or {},
        ),
        "document": SimpleNamespace(
            id=doc_id,
            filename=title,
            title=title,
            source_url=f"https://catalog.test/items/{doc_id}",
            canonical_url=f"https://catalog.test/items/{doc_id}",
            source_type="website",
            metadata_json={},
        ),
    }


class PhaseLQueryAnalysisTests(unittest.TestCase):
    def test_a_four_named_entities_are_extracted(self) -> None:
        mode, params = detect_retrieval_mode(
            "Compare Alpha One, Beta Two, Gamma Three, and Delta Four. Show price and features."
        )
        self.assertEqual(mode, RETRIEVAL_MODE_COMPARISON)
        self.assertEqual(params["entities"], ["alpha one", "beta two", "gamma three", "delta four"])

    def test_b_qualified_catalog_question_routes_to_catalog(self) -> None:
        mode, _ = detect_retrieval_mode(
            "What low-emission travel packages do you have in this catalog? Include price."
        )
        self.assertEqual(mode, RETRIEVAL_MODE_CATALOG)
        for query in (
            "What family rooms do you have?",
            "What accounting plans do you offer?",
            "What data science courses do you offer?",
            "What skin care products do you have?",
        ):
            with self.subTest(query=query):
                self.assertEqual(detect_retrieval_mode(query)[0], RETRIEVAL_MODE_CATALOG)

    def test_catalog_evidence_uses_category_metadata(self) -> None:
        titled = SimpleNamespace(
            title="Botanical Capsules",
            filename="Botanical Capsules",
            canonical_url="https://catalog.test/botanical",
            source_url="https://catalog.test/botanical",
            metadata_json={
                "og:title": "Botanical Capsules",
                "category_path": ["Collections", "Joint Comfort"],
                "description": "Incidental ingredient list must not be required for category matching.",
            },
        )
        unrelated = SimpleNamespace(
            title="Payroll Ledger",
            filename="Payroll Ledger",
            canonical_url="https://catalog.test/payroll",
            source_url="https://catalog.test/payroll",
            metadata_json={"og:title": "Payroll Ledger", "category_path": ["Collections", "Bookkeeping"]},
        )
        self.assertIn("joint", _catalog_evidence_text(titled))
        self.assertIn("comfort", _catalog_evidence_text(titled))
        self.assertNotIn("ingredient", _catalog_evidence_text(titled))
        self.assertNotIn("joint", _catalog_evidence_text(unrelated))

    def test_c_filter_attributes_are_structured(self) -> None:
        mode, params = detect_retrieval_mode(
            "Which products are powders rather than capsules, softgels, or gummies?"
        )
        self.assertEqual(mode, RETRIEVAL_MODE_FILTER)
        self.assertEqual(params["filters"]["include"], ["powder"])
        self.assertEqual(params["filters"]["exclude"], ["capsule", "softgel", "gummy"])

    def test_d_negative_prefix_is_an_exclusion(self) -> None:
        attrs = extract_filter_attributes("Which non-smoking rooms include breakfast?")
        self.assertIn("smoking", attrs["exclude"])

    def test_m_domain_independent_fields_and_filters(self) -> None:
        cases = [
            "Find laptops under 60000 with 16GB RAM and include price",
            "Which plans include SSO? Show price and setup instructions",
            "Which hotels include breakfast? Show rate and amenities",
            "Which courses are under 3 months? Show duration and fees",
        ]
        for query in cases:
            self.assertTrue(extract_requested_fields(query), query)


class PhaseLEvidenceAllocationTests(unittest.TestCase):
    def test_a_four_documents_get_comparison_coverage(self) -> None:
        rows = [
            item(i, i, name, f"# {name}\nOverview. Price ${i}0. Features and directions.", 0.9 - i / 100)
            for i, name in enumerate(("Alpha One", "Beta Two", "Gamma Three", "Delta Four"), start=1)
        ]
        selected = _diverse_chunk_selection(rows, top_k=8, max_per_doc=3, preferred_doc_ids=[1, 2, 3, 4])
        self.assertEqual({row["document"].id for row in selected[:4]}, {1, 2, 3, 4})

    def test_b_catalog_context_is_document_diverse(self) -> None:
        rows = [
            item(1, 1, "Plan A", "# Plan A\nOverview and price $10", 0.99),
            item(2, 1, "Plan A", "Plan A repeated marketing", 0.98),
            item(3, 2, "Plan B", "# Plan B\nOverview and price $20", 0.82),
            item(4, 3, "Plan C", "# Plan C\nOverview and price $30", 0.80),
        ]
        selected = _diverse_chunk_selection(rows, 4, 3, [1, 2, 3])
        self.assertEqual([row["document"].id for row in selected[:3]], [1, 2, 3])

    def test_e_price_evidence_is_prioritized(self) -> None:
        rows = [
            item(1, 1, "Service", "Customer story with general praise", 0.91),
            item(2, 1, "Service", "# Service\nPricing: $49 per month", 0.83),
        ]
        used, context = compress_and_rerank_chunks(rows, "What is the price?", 2000, "factual")
        self.assertEqual(used[0]["chunk"].id, 2)
        self.assertIn("$49", context)

    def test_f_usage_evidence_is_prioritized(self) -> None:
        rows = [
            item(1, 1, "Device", "Generic brand history", 0.90),
            item(2, 1, "Device", "Directions: connect power, then hold Setup for 3 seconds.", 0.82),
        ]
        used, _ = compress_and_rerank_chunks(rows, "Show setup instructions and directions", 2000, "factual")
        self.assertEqual(used[0]["chunk"].id, 2)

    def test_g_one_document_cannot_monopolize_comparison(self) -> None:
        rows = [item(i, 1, "Alpha", f"Alpha evidence {i}", 1.0 - i / 100) for i in range(1, 7)]
        rows += [item(20, 2, "Beta", "Beta evidence", 0.70), item(30, 3, "Gamma", "Gamma evidence", 0.69)]
        selected = _diverse_chunk_selection(rows, 6, 6, [1, 2, 3])
        self.assertEqual([row["document"].id for row in selected[:3]], [1, 2, 3])

    def test_h_cross_sell_card_is_not_catalog_evidence(self) -> None:
        primary = item(1, 1, "Primary", "# Primary\nProduct Description\nPrice $30", 0.80)
        cross_sell = item(
            2,
            1,
            "Primary",
            "### [Unindexed Add-on](https://elsewhere.test/add-on)\nNow$99\nView product",
            0.99,
            {"section": "You may also like"},
        )
        selected = _diverse_chunk_selection([cross_sell, primary], 2, 2, [1])
        self.assertEqual([row["chunk"].id for row in selected], [1])

    def test_i_sources_keep_canonical_and_drop_cross_sell_cta(self) -> None:
        cross_sell = item(
            2,
            1,
            "Primary",
            "### [Unindexed Add-on](https://elsewhere.test/add-on)\nNow$99\nView product",
            metadata={"section": "You may also like", "cta_links": [{"text": "Add-on", "url": "https://elsewhere.test/add-on"}]},
        )
        source = _format_sources([cross_sell])[0]
        self.assertEqual(source["source_url"], "https://catalog.test/items/1")
        self.assertEqual(source["cta_links"], [])

    def test_j_mixed_missing_field_keeps_sources_honest(self) -> None:
        mixed = "* Plan A: $20 per month.\n* Plan B: price not stated on the indexed page."
        self.assertFalse(_answer_has_no_supporting_business_fact(mixed))
        self.assertTrue(_answer_has_no_supporting_business_fact("I don't have information about that item."))

    def test_k_review_chunk_loses_to_specs_for_price_question(self) -> None:
        rows = [
            item(1, 1, "Course", "Verified Reviewer: Amazing course, five stars!", 0.95),
            item(2, 1, "Course", "# Course\nPrice $250. Duration 6 weeks.", 0.78),
        ]
        used, _ = compress_and_rerank_chunks(rows, "What are the price and duration?", 2000, "factual")
        self.assertEqual(used[0]["chunk"].id, 2)

    def test_l_review_query_can_retrieve_reviews(self) -> None:
        rows = [
            item(1, 1, "Hotel", "Verified Reviewer: Quiet rooms and helpful staff.", 0.83),
            item(2, 1, "Hotel", "# Hotel\nRoom dimensions and check-in time.", 0.84),
        ]
        used, context = compress_and_rerank_chunks(rows, "What do customer reviews say?", 2000, "factual")
        self.assertEqual(used[0]["chunk"].id, 1)
        self.assertIn("helpful staff", context)


if __name__ == "__main__":
    unittest.main(verbosity=2)
