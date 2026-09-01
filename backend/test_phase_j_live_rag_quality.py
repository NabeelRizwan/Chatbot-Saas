"""Deterministic Phase J contract and regression coverage.

These tests exercise query understanding, evidence ordering, catalog context,
source links, and cache read-back without calling external providers or mutating
the configured database.  The separate Phase J report records real-corpus live
answer evidence.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.conversational_engine import compress_and_rerank_chunks, polish_answer
from services.intent_router import (
    RETRIEVAL_MODE_CATALOG,
    RETRIEVAL_MODE_COMPARISON,
    RETRIEVAL_MODE_ENTITY,
    RETRIEVAL_MODE_FACTUAL,
    RETRIEVAL_MODE_FILTER,
    RETRIEVAL_MODE_POLICY,
    RETRIEVAL_MODE_PURCHASE,
    detect_retrieval_mode,
    rewrite_query_for_retrieval,
)
from services import rag_service
from services.rag_service import (
    _answer_has_no_supporting_business_fact,
    _format_sources,
    clean_retrieved_chunks,
    retrieve_relevant_chunks_cached,
    semantic_cache_identity,
)


def _item(chunk_id: int, index: int, content: str, score: float, doc_id: int = 1) -> dict:
    return {
        "score": score,
        "match_reasons": [f"rank-{chunk_id}"],
        "chunk": SimpleNamespace(
            id=chunk_id,
            chunk_index=index,
            content=content,
            token_count=20,
            metadata_json={},
        ),
        "document": SimpleNamespace(
            id=doc_id,
            filename=f"doc-{doc_id}",
            title=f"Document {doc_id}",
            source_url=f"https://example.test/{doc_id}",
            canonical_url=f"https://example.test/{doc_id}/canonical",
            source_type="website",
            metadata_json={},
        ),
    }


class PhaseJQueryContractTests(unittest.TestCase):
    def test_exact_customer_sequence_resolves_truthfully(self) -> None:
        history: list[dict] = []
        expected = [
            ("do you have hallway storage?", RETRIEVAL_MODE_FACTUAL, "do you have hallway storage?"),
            ("what about wardrobes", RETRIEVAL_MODE_FACTUAL, "wardrobes"),
            ("well wht all wardrobes do you have?", RETRIEVAL_MODE_CATALOG, "well what all wardrobes do you have?"),
            ("list items u have for storage?", RETRIEVAL_MODE_CATALOG, "list items you have for storage?"),
        ]
        assistant_turns = [
            "Yes, shoe organisers start from Rs. 89.",
            "PAX is one wardrobe option.",
            "BRIMNES and NODELAND are also available.",
            "Storage boxes and organisers are available.",
        ]

        for (question, expected_mode, expected_rewrite), assistant in zip(expected, assistant_turns):
            mode, _ = detect_retrieval_mode(question, history=history)
            self.assertEqual(mode, expected_mode)
            self.assertEqual(rewrite_query_for_retrieval(question, history=history), expected_rewrite)
            history.extend([
                {"role": "user", "content": question},
                {"role": "assistant", "content": assistant},
            ])

    def test_assistant_capitalization_cannot_poison_followup(self) -> None:
        history = [
            {"role": "user", "content": "Do you have hallway storage?"},
            {"role": "assistant", "content": "Yes, prices start at Rs. 89."},
        ]
        rewritten = rewrite_query_for_retrieval("what about wardrobes", history=history)
        self.assertEqual(rewritten, "wardrobes")
        self.assertNotIn("Yes", rewritten)
        self.assertNotIn("Rs", rewritten)

    def test_named_entity_attribute_followup_is_preserved(self) -> None:
        history = [
            {"role": "user", "content": "Tell me about Invisalign clear aligners."},
            {"role": "assistant", "content": "Treatment generally lasts 12 to 18 months."},
        ]
        self.assertEqual(
            rewrite_query_for_retrieval("What about treatment duration?", history=history),
            "Invisalign clear aligners treatment duration",
        )
        self.assertIn(
            "Invisalign clear aligners",
            rewrite_query_for_retrieval("How much does it cost?", history=history),
        )

    def test_40_query_natural_language_router_benchmark(self) -> None:
        benchmark = [
            # Catalog/list (10, across retail, healthcare, education, travel, legal, SaaS)
            ("What treatments do you offer?", RETRIEVAL_MODE_CATALOG),
            ("List all courses", RETRIEVAL_MODE_CATALOG),
            ("What apartments are available?", RETRIEVAL_MODE_CATALOG),
            ("What dishes do you have on the menu?", RETRIEVAL_MODE_CATALOG),
            ("Well, what all wardrobes do you have?", RETRIEVAL_MODE_CATALOG),
            ("List items you have for storage", RETRIEVAL_MODE_CATALOG),
            ("What plans do you offer?", RETRIEVAL_MODE_CATALOG),
            ("Which tours are available?", RETRIEVAL_MODE_CATALOG),
            ("What are your practice areas?", RETRIEVAL_MODE_CATALOG),
            ("Show all products", RETRIEVAL_MODE_CATALOG),
            # Factual (8)
            ("Do you have hallway storage?", RETRIEVAL_MODE_FACTUAL),
            ("How long is the data science program?", RETRIEVAL_MODE_FACTUAL),
            ("What is the clinic phone number?", RETRIEVAL_MODE_FACTUAL),
            ("Is breakfast included?", RETRIEVAL_MODE_FACTUAL),
            ("How many bedrooms does the penthouse have?", RETRIEVAL_MODE_FACTUAL),
            ("What material is this cabinet made from?", RETRIEVAL_MODE_FACTUAL),
            ("When does the tour depart?", RETRIEVAL_MODE_FACTUAL),
            ("Does the Pro plan include analytics?", RETRIEVAL_MODE_FACTUAL),
            # Filter (5)
            ("Which products support fast charging?", RETRIEVAL_MODE_FILTER),
            ("Show all apartments with two bedrooms", RETRIEVAL_MODE_FILTER),
            ("Which dishes are vegan?", RETRIEVAL_MODE_FILTER),
            ("Which courses require calculus?", RETRIEVAL_MODE_FILTER),
            ("Which plans include SSO?", RETRIEVAL_MODE_FILTER),
            # Comparison (5)
            ("Compare the Basic plan and Pro plan", RETRIEVAL_MODE_COMPARISON),
            ("PAX vs BRIMNES", RETRIEVAL_MODE_COMPARISON),
            ("What is the difference between the studio and penthouse?", RETRIEVAL_MODE_COMPARISON),
            ("Compare root canal treatment with Invisalign", RETRIEVAL_MODE_COMPARISON),
            ("Which is better, the city tour or mountain tour?", RETRIEVAL_MODE_COMPARISON),
            # Policy (4)
            ("What is your return policy?", RETRIEVAL_MODE_POLICY),
            ("How do refunds work?", RETRIEVAL_MODE_POLICY),
            ("How long does delivery take?", RETRIEVAL_MODE_POLICY),
            ("Do you offer a warranty?", RETRIEVAL_MODE_POLICY),
            # Purchase/action (4)
            ("Where can I buy the wardrobe?", RETRIEVAL_MODE_PURCHASE),
            ("How do I book a consultation?", RETRIEVAL_MODE_PURCHASE),
            ("I want to reserve the penthouse", RETRIEVAL_MODE_PURCHASE),
            ("Where can I enroll in the course?", RETRIEVAL_MODE_PURCHASE),
            # Entity/deep detail (4)
            ("Tell me everything about the PAX system", RETRIEVAL_MODE_ENTITY),
            ("Give me an overview of the Executive MBA", RETRIEVAL_MODE_ENTITY),
            ("All details about the Matterhorn trek", RETRIEVAL_MODE_ENTITY),
            ("Everything about the Enterprise plan", RETRIEVAL_MODE_ENTITY),
        ]
        self.assertEqual(len(benchmark), 40)
        failures = [
            (question, expected, detect_retrieval_mode(question)[0])
            for question, expected in benchmark
            if detect_retrieval_mode(question)[0] != expected
        ]
        self.assertEqual(failures, [])


class PhaseJEvidenceContractTests(unittest.TestCase):
    def tearDown(self) -> None:
        rag_service._RETRIEVAL_CACHE.clear()

    def test_cleanup_preserves_relevance_order(self) -> None:
        retrieved = [
            _item(1, 1, "moderately relevant evidence", 0.71),
            _item(2, 40, "strongest exact hallway storage evidence", 0.94),
            _item(3, 2, "other evidence", 0.73),
        ]
        cleaned = clean_retrieved_chunks(retrieved, top_k=3, max_per_doc=4)
        self.assertEqual([row["chunk"].id for row in cleaned], [2, 3, 1])

    def test_catalog_context_uses_structured_matching_items(self) -> None:
        retrieved = [
            _item(1, 1, "### [BRIMNES](https://shop.test/brimnes) Wardrobe with 3 doors", 0.91),
            _item(2, 2, "### [PAX](https://shop.test/pax) Modular wardrobe combination", 0.89),
            _item(3, 3, "### [NODELAND](https://shop.test/nodeland) Black wardrobe with 3 doors", 0.87),
            _item(4, 4, "Storage boxes can be placed inside wardrobes.", 0.93, doc_id=2),
        ]
        used, context = compress_and_rerank_chunks(
            retrieved,
            "what all wardrobes do you have?",
            max_context_chars=5000,
            mode="catalog",
        )
        self.assertEqual({row["chunk"].id for row in used}, {1, 2, 3})
        self.assertIn("BRIMNES", context)
        self.assertIn("PAX", context)
        self.assertIn("NODELAND", context)
        self.assertNotIn("Storage boxes", context)

    def test_sources_include_canonical_and_direct_item_links(self) -> None:
        item = _item(
            11,
            5,
            "### [BRIMNES](https://shop.test/products/brimnes) Wardrobe with 3 doors",
            0.9,
        )
        sources = _format_sources([item])
        self.assertEqual(sources[0]["source_url"], "https://example.test/1/canonical")
        self.assertIn(
            {"label": "BRIMNES", "url": "https://shop.test/products/brimnes"},
            sources[0]["cta_links"],
        )

    def test_unknown_answer_does_not_expose_unrelated_sources(self) -> None:
        answer = "We do not sell kayaks. I can only help with this business's catalog."
        self.assertTrue(_answer_has_no_supporting_business_fact(answer))
        evidence = [] if _answer_has_no_supporting_business_fact(answer) else [_item(1, 1, "Storage", 0.8)]
        self.assertEqual(_format_sources(evidence), [])

    def test_retrieval_cache_roundtrip_retains_provenance(self) -> None:
        source_item = _item(21, 7, "Exact source evidence", 0.88)
        with patch.object(rag_service, "retrieve_relevant_chunks", return_value=[source_item]) as retrieve:
            first = retrieve_relevant_chunks_cached(object(), 99, "query", top_k=4, mode="factual")
            second = retrieve_relevant_chunks_cached(object(), 99, "query", top_k=4, mode="factual")
        self.assertEqual(retrieve.call_count, 1)
        self.assertEqual(first[0]["match_reasons"], second[0]["match_reasons"])
        self.assertEqual(second[0]["document"].canonical_url, "https://example.test/1/canonical")
        self.assertEqual(second[0]["document"].source_type, "website")

    def test_markdown_spacing_does_not_trigger_polish_llm(self) -> None:
        bot = SimpleNamespace()
        with patch("services.conversational_engine.generate", side_effect=AssertionError("LLM should not run")):
            answer = polish_answer(
                bot,
                "List the options",
                "*   First option\n*   Second option",
                "system",
            )
        self.assertEqual(answer, "* First option\n* Second option")

    def test_cache_identity_is_history_and_config_scoped(self) -> None:
        bot = SimpleNamespace(
            provider="gemini",
            model_name="gemini-2.5-flash",
            system_prompt=None,
            tone="neutral",
            capabilities={},
        )
        a = semantic_cache_identity(
            bot,
            "what about it?",
            [{"role": "user", "content": "Tell me about Plan A"}],
        )
        b = semantic_cache_identity(
            bot,
            "what about it?",
            [{"role": "user", "content": "Tell me about Plan B"}],
        )
        self.assertNotEqual(a["history_fingerprint"], b["history_fingerprint"])
        self.assertNotEqual(a["resolved_query"], b["resolved_query"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
