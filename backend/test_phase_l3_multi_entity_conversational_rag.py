"""Deterministic Phase L.3 multi-entity conversational RAG contracts."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.conversational_engine import compress_and_rerank_chunks
from services.intent_router import detect_retrieval_mode, is_comparison_query
from services.query_contract import (
    COVERAGE_SUPPORTED,
    PriceFact,
    build_query_contract,
    compare_entity_prices,
    extract_typed_prices_from_text,
    is_contraction_fragment,
    sanitize_comparison_entities,
)
from services.rag_service import (
    _answer_has_no_supporting_business_fact,
    _diverse_chunk_selection,
    _format_sources,
    _select_complete_field_evidence,
    _structured_evidence_item,
    build_entity_field_matrix,
    collect_price_facts,
    semantic_cache_identity,
)


def document(doc_id: int, title: str, *, metadata: dict | None = None, url: str | None = None):
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


def chunk(chunk_id: int, index: int, content: str, *, metadata: dict | None = None):
    return SimpleNamespace(
        id=chunk_id,
        chunk_index=index,
        content=content,
        token_count=40,
        metadata_json=metadata or {},
    )


def item(chunk_id: int, doc_id: int, title: str, content: str, score: float = 0.85, priority: float = 0.0, metadata: dict | None = None):
    return {
        "score": score,
        "evidence_priority": priority,
        "match_reasons": ["fixture"],
        "chunk": SimpleNamespace(
            id=chunk_id,
            chunk_index=chunk_id,
            content=content,
            token_count=40,
            metadata_json=metadata or {},
        ),
        "document": document(doc_id, title),
    }


def contract(query: str, docs: list, history: list[dict] | None = None):
    mode, params = detect_retrieval_mode(query, history=history)
    return build_query_contract(
        query,
        history,
        docs,
        intent="knowledge_query",
        mode=mode,
        mode_params=params,
    )


class ContractionAndSubjectSetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.alpha = document(1, "Product Alpha")
        self.beta = document(2, "Product Beta")
        self.gamma = document(3, "Product Gamma")
        self.docs = [self.alpha, self.beta, self.gamma]

    def test_a_contraction_is_not_an_entity(self) -> None:
        self.assertTrue(is_contraction_fragment("'s"))
        self.assertTrue(is_contraction_fragment("'re"))
        self.assertEqual(sanitize_comparison_entities(["'s", "Product Alpha", "Product Beta"]), ["Product Alpha", "Product Beta"])
        is_comp, entities = is_comparison_query(
            "What's the difference between Product Alpha and Product Beta?"
        )
        self.assertTrue(is_comp)
        self.assertNotIn("'s", entities)
        self.assertEqual(len(entities), 2)
        result = contract("What's the difference between Product Alpha and Product Beta?", self.docs)
        self.assertNotIn("'s", result.comparison_entities)
        self.assertEqual({entity.document_id for entity in result.resolved_entities}, {1, 2})
        self.assertTrue(result.is_multi_entity)
        self.assertIsNone(result.subject_document_id)

    def test_b_explicit_pair_guarantees_both_documents(self) -> None:
        result = contract("Compare Product Alpha and Product Beta", self.docs)
        self.assertEqual(result.mode, "comparison")
        self.assertEqual(result.explicit_document_ids(), [1, 2])
        rows = [
            item(1, 1, "Product Alpha", "Alpha overview", 0.99),
            item(2, 1, "Product Alpha", "More Alpha", 0.98),
            item(3, 2, "Product Beta", "Beta overview", 0.70),
        ]
        selected = _diverse_chunk_selection(rows, top_k=4, max_per_doc=3, preferred_doc_ids=[1, 2])
        self.assertEqual({row["document"].id for row in selected}, {1, 2})

    def test_c_three_entities_all_receive_evidence(self) -> None:
        result = contract("Compare Product Alpha, Product Beta, and Product Gamma", self.docs)
        self.assertEqual(set(result.explicit_document_ids()), {1, 2, 3})
        rows = [
            item(1, 1, "Product Alpha", "# Product Alpha\nPrimary overview and specifications for Alpha.", 0.99),
            item(2, 2, "Product Beta", "# Product Beta\nPrimary overview and specifications for Beta.", 0.40),
            item(3, 3, "Product Gamma", "# Product Gamma\nPrimary overview and specifications for Gamma.", 0.41),
            item(4, 1, "Product Alpha", "# Product Alpha extra\nAdditional supporting Alpha detail.", 0.98),
        ]
        selected = _diverse_chunk_selection(rows, top_k=6, max_per_doc=3, preferred_doc_ids=[1, 2, 3])
        self.assertEqual({row["document"].id for row in selected}, {1, 2, 3})

    def test_d_followup_retains_comparison_scope(self) -> None:
        history = [{"role": "user", "content": "What's the difference between Product Alpha and Product Beta?"}]
        result = contract("Which one is cheaper?", self.docs, history)
        self.assertEqual(result.mode, "comparison")
        self.assertEqual(set(result.explicit_document_ids()), {1, 2})
        self.assertIn("price", result.requested_fields)
        self.assertEqual(result.comparison_operation, "cheaper")

    def test_e_followup_retains_directions_for_each(self) -> None:
        history = [{"role": "user", "content": "Compare Product Alpha and Product Beta"}]
        result = contract("How do I use each one?", self.docs, history)
        self.assertEqual(set(result.explicit_document_ids()), {1, 2})
        self.assertIn("directions", result.requested_fields)

    def test_f_per_entity_per_field_coverage(self) -> None:
        history = [{"role": "user", "content": "Compare Product Alpha and Product Beta"}]
        result = contract("What are their prices and ingredients?", self.docs, history)
        self.assertEqual(set(result.requested_fields) & {"price", "ingredients"}, {"price", "ingredients"})
        chunks_by_document = {
            1: [
                chunk(11, 0, "One-time purchase $10.00"),
                chunk(12, 1, "## Ingredients\n- Component A\n- Component B"),
            ],
            2: [
                chunk(21, 0, "Price $20.00"),
                chunk(22, 1, "## Ingredients\n- Component C"),
            ],
        }
        docs_by_id = {1: self.alpha, 2: self.beta}
        selected, coverage = build_entity_field_matrix(
            chunks_by_document, docs_by_id, [1, 2], ["price", "ingredients"]
        )
        self.assertEqual(coverage["1:price"], COVERAGE_SUPPORTED)
        self.assertEqual(coverage["1:ingredients"], COVERAGE_SUPPORTED)
        self.assertEqual(coverage["2:price"], COVERAGE_SUPPORTED)
        self.assertEqual(coverage["2:ingredients"], COVERAGE_SUPPORTED)
        self.assertGreaterEqual(len(selected), 4)

    def test_g_explicit_switch_to_new_subject(self) -> None:
        history = [
            {"role": "user", "content": "Compare Product Alpha and Product Beta"},
            {"role": "assistant", "content": "Alpha vs Beta overview."},
            {"role": "user", "content": "What about Product Gamma?"},
        ]
        result = contract("how much is it?", self.docs, history)
        self.assertEqual(result.subject_document_id, 3)
        self.assertEqual(result.resolved_subject, "Product Gamma")
        self.assertFalse(result.is_multi_entity)
        self.assertIn("price", result.requested_fields)

    def test_h_unrelated_document_cannot_replace_requested_pair(self) -> None:
        result = contract("Compare Product Alpha and Product Beta", self.docs)
        rows = [
            item(1, 1, "Product Alpha", "# Product Alpha\nAlpha listed price is $10.00 for a one-time purchase.", 0.70, 0.30),
            item(2, 2, "Product Beta", "# Product Beta\nBeta listed price is $20.00 for a one-time purchase.", 0.69, 0.30),
            item(3, 3, "Product Gamma", "# Product Gamma\nUnrelated sibling product priced at $99.00.", 0.99, 0.05),
        ]
        used, context = compress_and_rerank_chunks(
            rows, "Compare Product Alpha and Product Beta", 4000, "comparison", query_contract=result
        )
        self.assertEqual({row["document"].id for row in used}, {1, 2})
        self.assertNotIn("Unrelated sibling", context)

    def test_i_storage_cannot_outrank_serving_directions(self) -> None:
        rows = [
            chunk(1, 0, "Storage: keep in a cool dry place. Warning: do not use if the safety seal is damaged."),
            chunk(2, 1, "## How to use\nTake 1 capsule daily, preferably with a meal."),
        ]
        selected = _select_complete_field_evidence(rows, "directions", self.alpha)
        self.assertEqual(selected[0].id, 2)

    def test_r_single_entity_l2_behavior_unchanged(self) -> None:
        result = contract("What are the ingredients of Product Alpha?", self.docs)
        self.assertEqual(result.subject_document_id, 1)
        self.assertEqual(result.requested_fields, ["ingredients"])
        self.assertFalse(result.is_multi_entity)

    def test_s_ambiguous_fresh_query_still_clarifies(self) -> None:
        result = contract("What are the ingredients?", self.docs)
        self.assertTrue(result.requires_clarification)
        self.assertIsNone(result.subject_document_id)

    def test_ambiguous_singular_followup_after_comparison_clarifies(self) -> None:
        history = [{"role": "user", "content": "Compare Product Alpha and Product Beta"}]
        result = contract("how much is it?", self.docs, history)
        self.assertTrue(result.requires_clarification)


class PriceTypingAndComparisonTests(unittest.TestCase):
    def test_j_one_time_and_subscription_are_preserved(self) -> None:
        facts = extract_typed_prices_from_text(
            "One-time purchase $33.00. Subscribe & Save $31.35.",
            entity_name="Plan Alpha",
            entity_document_id=1,
        )
        roles = {fact.price_type: fact.value for fact in facts}
        self.assertEqual(roles.get("one_time"), "33.00")
        self.assertEqual(roles.get("subscription"), "31.35")
        rendered = "\n".join(fact.as_prompt_line() for fact in facts)
        self.assertIn("one_time", rendered)
        self.assertIn("subscription", rendered)
        self.assertNotIn("Prices: $33, $31.35", rendered)

    def test_k_sale_and_regular_are_preserved(self) -> None:
        doc = document(
            12,
            "Plan Pro",
            metadata={"regular_price": "49.00", "sale_price": "39.00", "currency": "USD"},
        )
        item_row = _structured_evidence_item(doc, ["price"])
        content = item_row["chunk"].content
        self.assertIn("Regular Price: $49.00 USD", content)
        self.assertIn("Sale Price: $39.00 USD", content)

    def test_l_bundle_and_per_unit_are_preserved(self) -> None:
        facts = extract_typed_prices_from_text(
            "6-bottle pack $247.50. $41.25 / bottle.",
            entity_name="Bundle Item",
            entity_document_id=4,
        )
        types = {fact.price_type for fact in facts}
        self.assertTrue({"bundle_total", "bundle_per_unit"} & types or any("41.25" in fact.value for fact in facts))

    def test_m_deterministic_cheaper_comparison(self) -> None:
        facts = {
            "Product Alpha": [PriceFact("33.00", "USD", "$33.00", "one_time", "Product Alpha", 1)],
            "Product Beta": [PriceFact("55.00", "USD", "$55.00", "one_time", "Product Beta", 2)],
        }
        result = compare_entity_prices(facts, "cheaper")
        self.assertEqual(result["status"], "compared")
        self.assertEqual(result["winner"], "Product Alpha")

    def test_n_different_currencies_are_not_compared(self) -> None:
        facts = {
            "Plan Alpha": [PriceFact("40.00", "USD", "$40.00", "one_time", "Plan Alpha", 1)],
            "Plan Beta": [PriceFact("35.00", "EUR", "€35.00", "one_time", "Plan Beta", 2)],
        }
        result = compare_entity_prices(facts, "cheaper")
        self.assertEqual(result["status"], "incompatible_currency")


class SourcesCacheAndCatalogTests(unittest.TestCase):
    def test_o_mixed_available_missing_retains_valid_sources(self) -> None:
        mixed = "Product Alpha is $20. I don't have the ingredients for Product Beta."
        self.assertFalse(_answer_has_no_supporting_business_fact(mixed))
        evidence = [item(1, 1, "Product Alpha", "Price $20", 0.9)]
        sources = _format_sources(evidence)
        self.assertEqual(sources[0]["source_url"], "https://example.test/items/1")

    def test_p_successful_comparison_keeps_both_sources(self) -> None:
        rows = [
            item(1, 1, "Product Alpha", "Alpha details", 0.9),
            item(2, 2, "Product Beta", "Beta details", 0.9),
        ]
        sources = _format_sources(rows)
        self.assertEqual({source["document_id"] for source in sources}, {1, 2})

    def test_q_cache_isolation_between_comparison_scopes(self) -> None:
        docs_ab = [document(1, "Product Alpha"), document(2, "Product Beta")]
        docs_cd = [document(3, "Product Charlie"), document(4, "Product Delta")]
        history_ab = [{"role": "user", "content": "Compare Product Alpha and Product Beta"}]
        history_cd = [{"role": "user", "content": "Compare Product Charlie and Product Delta"}]
        ab = contract("Which one is cheaper?", docs_ab, history_ab)
        cd = contract("Which one is cheaper?", docs_cd, history_cd)
        bot = SimpleNamespace(provider="gemini", model_name="model", system_prompt="", tone="neutral", capabilities={})
        identity_ab = semantic_cache_identity(bot, "Which one is cheaper?", history_ab, ab)
        identity_cd = semantic_cache_identity(bot, "Which one is cheaper?", history_cd, cd)
        self.assertNotEqual(identity_ab["resolved_query"], identity_cd["resolved_query"])

    def test_t_catalog_behavior_unchanged(self) -> None:
        docs = [document(1, "Solar Basic"), document(2, "Solar Plus"), document(3, "Storage Pro")]
        result = contract("What solar plans do you have?", docs)
        self.assertEqual(result.mode, "catalog")
        self.assertEqual(result.catalog_scope, ["solar"])
        self.assertIsNone(result.subject_document_id)

    def test_catalog_title_overlap_stays_broad(self) -> None:
        docs = [
            document(1, "Family Rooms"),
            document(2, "Deluxe Family Rooms"),
            document(3, "Garden Suite"),
        ]
        catalog = contract("What family rooms do you have?", docs)
        self.assertEqual(catalog.mode, "catalog")
        self.assertIsNone(catalog.subject_document_id)
        exact = contract("Tell me about Family Rooms", docs)
        self.assertEqual(exact.subject_document_id, 1)


class CrossDomainComparisonTests(unittest.TestCase):
    def test_saas_comparison_followup(self) -> None:
        docs = [document(1, "Basic"), document(2, "Pro")]
        first = contract("What's the difference between Basic and Pro?", docs)
        self.assertEqual(set(first.explicit_document_ids()), {1, 2})
        follow = contract(
            "Which one is cheaper and does each include SSO?",
            docs,
            [{"role": "user", "content": "What's the difference between Basic and Pro?"}],
        )
        self.assertEqual(set(follow.explicit_document_ids()), {1, 2})
        self.assertIn("price", follow.requested_fields)
        self.assertIn("features", follow.requested_fields)

    def test_hotel_comparison_followup(self) -> None:
        docs = [document(1, "Standard Room"), document(2, "Deluxe Suite")]
        follow = contract(
            "Which one is cheaper and what amenities does each have?",
            docs,
            [{"role": "user", "content": "Compare Standard Room and Deluxe Suite."}],
        )
        self.assertEqual(set(follow.explicit_document_ids()), {1, 2})
        self.assertIn("price", follow.requested_fields)
        self.assertIn("amenities", follow.requested_fields)

    def test_education_comparison_followup(self) -> None:
        docs = [document(1, "Beginner Python"), document(2, "Advanced Python")]
        follow = contract(
            "Which one is cheaper and how long is each course?",
            docs,
            [{"role": "user", "content": "Compare Beginner Python and Advanced Python."}],
        )
        self.assertEqual(set(follow.explicit_document_ids()), {1, 2})
        self.assertIn("price", follow.requested_fields)
        self.assertIn("duration", follow.requested_fields)

    def test_services_comparison_followup(self) -> None:
        docs = [document(1, "Starter Package"), document(2, "Premium Package")]
        follow = contract(
            "Which costs less and what does each include?",
            docs,
            [{"role": "user", "content": "Compare Starter Package and Premium Package."}],
        )
        self.assertEqual(set(follow.explicit_document_ids()), {1, 2})
        self.assertIn("price", follow.requested_fields)
        self.assertTrue(set(follow.requested_fields) & {"features", "ingredients"})

    def test_collect_price_facts_keeps_roles(self) -> None:
        rows = [
            item(
                1,
                1,
                "Plan Alpha",
                "One-time: $33.00\nSubscribe & Save: $31.35",
                metadata={
                    "structured_fields": [
                        {"field": "price", "display_value": "$33.00", "normalized_value": "33.00", "currency": "USD", "price_type": "one_time"},
                        {"field": "price", "display_value": "$31.35", "normalized_value": "31.35", "currency": "USD", "price_type": "subscription"},
                    ]
                },
            )
        ]
        facts = collect_price_facts(rows)
        types = {fact.price_type for fact in facts}
        self.assertIn("one_time", types)
        self.assertIn("subscription", types)


if __name__ == "__main__":
    unittest.main(verbosity=2)
