"""Deterministic Phase L.2 conversational field-retrieval contracts."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.intent_router import detect_retrieval_mode
from services.query_contract import (
    build_query_contract,
    extract_requested_fields,
    extract_structured_evidence,
)
from services.rag_service import (
    _answer_field_coverage,
    _format_sources,
    _has_primary_text_price_evidence,
    _needs_field_coverage_correction,
    _retrieval_field_coverage,
    _select_complete_field_evidence,
    _structured_evidence_item,
    semantic_cache_identity,
)


def document(
    doc_id: int,
    title: str,
    *,
    metadata: dict | None = None,
    url: str | None = None,
) -> SimpleNamespace:
    canonical = url or f"https://example.test/items/{doc_id}"
    return SimpleNamespace(
        id=doc_id,
        title=title,
        filename=title,
        source_url=canonical,
        canonical_url=canonical,
        source_type="website",
        metadata_json=metadata or {},
    )


def chunk(
    chunk_id: int,
    index: int,
    content: str,
    *,
    metadata: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=chunk_id,
        chunk_index=index,
        content=content,
        token_count=40,
        metadata_json=metadata or {},
    )


def contract(query: str, docs: list[SimpleNamespace], history: list[dict] | None = None):
    mode, params = detect_retrieval_mode(query, history=history)
    return build_query_contract(
        query,
        history,
        docs,
        intent="knowledge_query",
        mode=mode,
        mode_params=params,
    )


class QueryContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.alpha = document(1, "Product Alpha")
        self.beta = document(2, "Product Beta")
        self.docs = [self.alpha, self.beta]

    def test_a_single_product_one_field(self) -> None:
        result = contract("What are the ingredients of Product Alpha?", self.docs)
        self.assertEqual(result.resolved_subject, "Product Alpha")
        self.assertEqual(result.subject_document_id, 1)
        self.assertEqual(result.requested_fields, ["ingredients"])

    def test_b_single_product_multiple_fields(self) -> None:
        result = contract(
            "What are the ingredients, price and directions for Product Alpha?",
            self.docs,
        )
        self.assertEqual(result.subject_document_id, 1)
        self.assertEqual(result.requested_fields, ["price", "ingredients", "directions"])

    def test_g_and_h_conversation_followups(self) -> None:
        history = [{"role": "user", "content": "Tell me about Product Alpha"}]
        price = contract("how much is it?", self.docs, history)
        ingredients = contract("what are its ingredients?", self.docs, history)
        self.assertEqual(price.subject_document_id, 1)
        self.assertEqual(price.requested_fields, ["price"])
        self.assertEqual(ingredients.subject_document_id, 1)
        self.assertEqual(ingredients.requested_fields, ["ingredients"])

    def test_i_ambiguous_fresh_chat_clarifies(self) -> None:
        result = contract("What are the ingredients?", self.docs)
        self.assertTrue(result.requires_clarification)
        self.assertIn("Which", result.clarification_prompt or "")
        self.assertIsNone(result.subject_document_id)

    def test_j_entity_switch_updates_followup_subject(self) -> None:
        history = [
            {"role": "user", "content": "Tell me about Product Alpha"},
            {"role": "assistant", "content": "Product Alpha overview."},
            {"role": "user", "content": "What about Product Beta?"},
        ]
        result = contract("how much is it?", self.docs, history)
        self.assertEqual(result.subject_document_id, 2)
        self.assertEqual(result.resolved_subject, "Product Beta")

    def test_k_plural_reference_keeps_comparison_entities(self) -> None:
        history = [{"role": "user", "content": "Compare Product Alpha and Product Beta"}]
        result = contract("which one is cheaper?", self.docs, history)
        self.assertEqual(set(result.comparison_entities), {"Product Alpha", "Product Beta"})
        self.assertIn("price", result.requested_fields)

    def test_l_catalog_scope_is_separate_from_entity_evidence(self) -> None:
        docs = [
            document(1, "Solar Basic"),
            document(2, "Solar Plus"),
            document(3, "Storage Pro"),
        ]
        result = contract("What solar plans do you have?", docs)
        self.assertEqual(result.mode, "catalog")
        self.assertEqual(result.catalog_scope, ["solar"])
        self.assertIsNone(result.subject_document_id)

    def test_r_typo_robustness(self) -> None:
        result = contract("wht ingredient of Product Alpha", self.docs)
        self.assertEqual(result.subject_document_id, 1)
        self.assertEqual(result.requested_fields, ["ingredients"])


class FieldEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.doc = document(10, "Product Alpha")

    def test_c_field_split_across_adjacent_list_chunks_is_complete(self) -> None:
        rows = [
            chunk(1, 4, "# Product Alpha\n## Ingredients\n- Component A\n- Component B"),
            chunk(2, 5, "- Component C\n- Component D"),
            chunk(3, 6, "## Customer Reviews\nVerified buyer: Excellent."),
        ]
        selected = _select_complete_field_evidence(rows, "ingredients", self.doc)
        self.assertEqual([item.id for item in selected], [1, 2])

    def test_d_metadata_only_price_becomes_first_class_evidence(self) -> None:
        doc = document(
            11,
            "Product Metadata",
            metadata={"og:price:amount": "55.00", "og:price:currency": "USD"},
        )
        item = _structured_evidence_item(doc, ["price"])
        self.assertIsNotNone(item)
        self.assertIn("$55.00 USD", item["chunk"].content)
        coverage = _retrieval_field_coverage([item], ["price"])
        self.assertTrue(coverage["price"])

    def test_e_text_price_is_selected(self) -> None:
        rows = [
            chunk(1, 0, "A customer story without commercial details."),
            chunk(2, 1, "# Product Alpha\nOne-time purchase price: $33.00"),
        ]
        selected = _select_complete_field_evidence(rows, "price", self.doc)
        self.assertEqual([item.id for item in selected], [2])

    def test_f_multiple_price_types_preserve_labels(self) -> None:
        doc = document(
            12,
            "Plan Pro",
            metadata={
                "regular_price": "49.00",
                "sale_price": "39.00",
                "currency": "USD",
            },
        )
        item = _structured_evidence_item(doc, ["price"])
        content = item["chunk"].content
        self.assertIn("Regular Price: $49.00 USD", content)
        self.assertIn("Sale Price: $39.00 USD", content)

    def test_shipping_threshold_is_not_a_product_price(self) -> None:
        shipping = chunk(20, 0, "Free shipping on orders over $60. Refund of your purchase price is available.")
        purchase = chunk(21, 1, "One-time purchase $33.00. Subscribe & Save $31.35.")
        self.assertFalse(_has_primary_text_price_evidence(shipping))
        self.assertTrue(_has_primary_text_price_evidence(purchase))

    def test_m_image_gallery_does_not_beat_ingredients_section(self) -> None:
        rows = [
            chunk(1, 0, "![Ingredient bottle](a.webp) ![Ingredients](b.webp) ![Gallery](c.webp)"),
            chunk(2, 1, "## Ingredients\n- Component A\n- Component B"),
        ]
        selected = _select_complete_field_evidence(rows, "ingredients", self.doc)
        self.assertEqual(selected[0].id, 2)

    def test_n_cross_sell_does_not_become_primary_evidence(self) -> None:
        rows = [
            chunk(1, 0, "## You may also like\nRelated Product ingredients and price $99", metadata={"section": "You may also like"}),
            chunk(2, 1, "## Ingredients\n- Component A\n- Component B"),
        ]
        selected = _select_complete_field_evidence(rows, "ingredients", self.doc)
        self.assertEqual(selected[0].id, 2)

    def test_o_metadata_source_is_canonical_page(self) -> None:
        doc = document(
            13,
            "Course Advanced",
            metadata={"price": "1200", "currency": "USD"},
            url="https://academy.test/courses/advanced",
        )
        item = _structured_evidence_item(doc, ["price"])
        source = _format_sources([item])[0]
        self.assertEqual(source["source_url"], "https://academy.test/courses/advanced")

    def test_p_mixed_supported_missing_keeps_supported_source(self) -> None:
        supported = {"price": True, "availability": False}
        answered = _answer_field_coverage("It costs $20; availability is not listed.", ["price", "availability"])
        self.assertEqual(_needs_field_coverage_correction("It costs $20; availability is not listed.", supported, answered), [])


class CacheAndDomainIndependenceTests(unittest.TestCase):
    def test_q_same_followup_under_different_subjects_cannot_collide(self) -> None:
        docs = [document(1, "Product Alpha"), document(2, "Product Beta")]
        alpha_contract = contract("how much is it?", docs, [{"role": "user", "content": "Product Alpha"}])
        beta_contract = contract("how much is it?", docs, [{"role": "user", "content": "Product Beta"}])
        bot = SimpleNamespace(provider="gemini", model_name="model", system_prompt="", tone="neutral", capabilities={})
        alpha_identity = semantic_cache_identity(bot, "how much is it?", [], alpha_contract)
        beta_identity = semantic_cache_identity(bot, "how much is it?", [], beta_contract)
        self.assertNotEqual(alpha_identity["resolved_query"], beta_identity["resolved_query"])

    def test_domain_independent_field_ontology(self) -> None:
        cases = {
            "Product Alpha: what are its price and ingredients?": {"price", "ingredients"},
            "Plan Pro: monthly cost and does it include SSO?": {"price", "features"},
            "Suite Deluxe: price, amenities and check-in time": {"price", "amenities", "check_in"},
            "Course Advanced: tuition, duration and syllabus": {"price", "duration", "syllabus"},
            "Service Premium: fee and what is included": {"price", "features"},
        }
        for query, expected in cases.items():
            self.assertTrue(expected.issubset(set(extract_requested_fields(query))), query)

    def test_nested_schema_offer_price_is_supported(self) -> None:
        evidence = extract_structured_evidence(
            {"product": {"offers": {"price": "199", "priceCurrency": "EUR"}}},
            ["price"],
        )
        self.assertTrue(evidence)
        self.assertEqual(evidence[0].currency, "EUR")
        self.assertEqual(evidence[0].display_value, "€199")


if __name__ == "__main__":
    unittest.main(verbosity=2)
