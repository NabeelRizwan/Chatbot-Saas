"""Offline regressions for descriptive criteria and locally defined comparisons."""

import unittest

from services.query_contract import is_result_set_reference, match_all_documents
from test_exclusion_entity_resolution import contract, document


FAILED_QUERY = (
    "I'm avoiding gummies. Which turmeric-containing options support joint comfort, "
    "and how do their single-bottle prices compare, including the price difference?"
)


class QualifierComparisonTests(unittest.TestCase):
    def setUp(self):
        self.docs = [document(1, "Joint Support"), document(2, "Turmeric Boost"),
                     document(3, "Turmeric Gummies")]

    def assert_broad(self, result):
        self.assertIsNone(result.resolved_subject)
        self.assertIsNone(result.subject_document_id)
        self.assertEqual(result.explicit_document_ids(), [])
        self.assertEqual(result.comparison_entities, [])
        self.assertFalse(result.requires_clarification)

    def test_reordered_qualifier_tokens_are_not_a_name(self):
        query = "Which products support joint comfort?"
        self.assertEqual(match_all_documents(query, self.docs), [])
        self.assert_broad(contract(query, self.docs))

    def test_scattered_tokens_are_not_a_name(self):
        self.assertEqual(match_all_documents("Tell me about joint comfort and daily support", self.docs), [])

    def test_literal_capability_qualifier_is_not_a_plan_subject(self):
        docs = [document(10, "Team Collaboration"), document(11, "Business Plan")]
        self.assert_broad(contract("Which plans support team collaboration?", docs))

    def test_literal_stay_qualifier_is_not_a_room_subject(self):
        docs = [document(10, "Family Stays"), document(11, "Garden Room")]
        self.assert_broad(contract("Which rooms support family stays?", docs))

    def test_exact_subject_preserved(self):
        self.assertEqual(contract("Tell me about Joint Support", self.docs).subject_document_id, 1)

    def test_exact_subject_price_preserved(self):
        result = contract("How much is Joint Support?", self.docs)
        self.assertEqual(result.subject_document_id, 1)
        self.assertIn("price", result.requested_fields)

    def test_punctuation_equivalent_name_preserved(self):
        docs = [document(10, "Studio-Flex")]
        self.assertEqual(contract("Tell me about Studio Flex", docs).subject_document_id, 10)

    def test_explicit_comparison_preserved(self):
        result = contract("Compare Joint Support and Turmeric Boost", self.docs)
        self.assertEqual(result.explicit_document_ids(), [1, 2])
        self.assertEqual(result.mode, "comparison")

    def test_explicit_comparison_with_exclusion_preserved(self):
        result = contract("Exclude Turmeric Gummies and compare Joint Support and Turmeric Boost", self.docs)
        self.assertEqual(result.explicit_document_ids(), [1, 2])
        self.assertIn("turmeric gummies", result.exclude_constraints)

    def test_catalog_qualifier_stays_broad(self):
        result = contract("What joint support products do you have?", self.docs)
        self.assert_broad(result)
        self.assertEqual(result.mode, "catalog")

    def test_local_possessive_comparison_without_history(self):
        query = "Which options match these requirements and how do their prices compare?"
        result = contract(query, self.docs)
        self.assertTrue(is_result_set_reference(query))
        self.assert_broad(result)
        self.assertEqual(result.mode, "filter")
        self.assertIn("their", result.conversation_references)
        self.assertIn("price", result.requested_fields)

    def test_local_plural_comparison_forms(self):
        for ending in ("how do they compare on price", "compare them on price",
                       "how do those compare on price", "how do these compare on price",
                       "compare their prices"):
            with self.subTest(ending=ending):
                query = f"Which cabins match my requirements and {ending}?"
                self.assertTrue(is_result_set_reference(query))
                self.assert_broad(contract(query, self.docs))

    def test_local_scope_does_not_inherit_single_subject(self):
        history = [{"role": "user", "content": "Tell me about Joint Support"}]
        self.assert_broad(contract(FAILED_QUERY, self.docs, history))

    def test_local_scope_does_not_inherit_named_comparison(self):
        history = [{"role": "user", "content": "Compare Joint Support and Turmeric Gummies"}]
        self.assert_broad(contract(FAILED_QUERY, self.docs, history))

    def test_possessive_followup_keeps_existing_pair(self):
        history = [{"role": "user", "content": "Compare Joint Support and Turmeric Boost"}]
        query = "How do their prices compare?"
        self.assertFalse(is_result_set_reference(query))
        self.assertEqual(contract(query, self.docs, history).explicit_document_ids(), [1, 2])

    def test_singular_followup_preserved(self):
        history = [{"role": "user", "content": "Tell me about Joint Support"}]
        self.assertEqual(contract("How much is it?", self.docs, history).subject_document_id, 1)

    def test_failed_widget_query_uses_positive_result_set(self):
        result = contract(FAILED_QUERY, self.docs)
        self.assert_broad(result)
        self.assertEqual(match_all_documents(FAILED_QUERY, self.docs), [])
        self.assertTrue(is_result_set_reference(FAILED_QUERY))
        self.assertEqual(result.mode, "filter")
        self.assertTrue({"gummy", "gummies"}.issubset(result.exclude_constraints))
        self.assertIn("their", result.conversation_references)
        self.assertIn("their single-bottle prices compare", result.resolved_query)
        self.assertIn("turmeric-containing", result.resolved_query)
        self.assertIn("joint comfort", result.resolved_query)
        self.assertIn("price", result.requested_fields)
        self.assertNotIn("joint support", result.resolved_query)


if __name__ == "__main__":
    unittest.main()
