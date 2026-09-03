"""Offline regressions for negative mentions and positive comparison scope."""

import unittest
from types import SimpleNamespace

from services.intent_router import detect_retrieval_mode, extract_filter_attributes, is_comparison_query
from services.query_contract import build_query_contract, extract_catalog_scope, match_all_documents, split_exclusions


def document(doc_id, title):
    return SimpleNamespace(id=doc_id, title=title, filename=title, metadata_json={}, source_url="")


def contract(query, documents, history=None, **overrides):
    mode, params = detect_retrieval_mode(query, history)
    return build_query_contract(query, history, documents, intent="knowledge_query",
                                mode=overrides.get("mode", mode), mode_params=overrides.get("params", params))


class ExclusionEntityTests(unittest.TestCase):
    def setUp(self):
        self.docs = [document(1, "Cedar Suite"), document(2, "Lake Villa"), document(3, "Garden Loft")]

    def assert_exclusion(self, phrase):
        query = f"{phrase} Cedar Suite and compare Lake Villa and Garden Loft"
        result = contract(query, self.docs)
        self.assertEqual(set(result.explicit_document_ids()), {2, 3})
        self.assertIsNone(result.subject_document_id)
        self.assertNotIn("Cedar Suite", result.comparison_entities)
        self.assertIn("cedar suite", result.exclude_constraints)

    def test_avoiding(self):
        self.assert_exclusion("I'm avoiding")

    def test_exclude(self):
        self.assert_exclusion("Exclude")

    def test_not(self):
        self.assert_exclusion("Not")

    def test_without(self):
        self.assert_exclusion("Without")

    def test_anything_except(self):
        self.assert_exclusion("Anything except")

    def test_dont_want(self):
        self.assert_exclusion("I don't want")

    def test_unicode_contraction(self):
        self.assert_exclusion("I don’t want")

    def test_instead_of_does_not_trigger_single_subject_switch(self):
        self.assert_exclusion("Instead of")

    def test_positive_exact_entity_unchanged(self):
        result = contract("Tell me about Cedar Suite", self.docs)
        self.assertEqual(result.subject_document_id, 1)
        self.assertEqual(result.exclude_constraints, [])

    def test_positive_comparison_unchanged(self):
        result = contract("Compare Cedar Suite and Lake Villa", self.docs)
        self.assertEqual(result.explicit_document_ids(), [1, 2])

    def test_negative_only_never_becomes_subject(self):
        result = contract("I don't want Cedar Suite", self.docs)
        self.assertIsNone(result.subject_document_id)
        self.assertEqual(result.explicit_document_ids(), [])
        self.assertIn("cedar suite", result.exclude_constraints)

    def test_negative_list_stops_at_positive_clause(self):
        positive, excluded = split_exclusions("Exclude Cedar Suite, Lake Villa and Garden Loft; tell me about Alpine Cabin")
        self.assertEqual(excluded, ["cedar suite", "lake villa", "garden loft"])
        self.assertIn("alpine cabin", positive)
        self.assertNotIn("cedar", positive)

    def test_negative_attribute_does_not_erase_positive_entity(self):
        result = contract("Tell me about Cedar Suite without breakfast", self.docs)
        self.assertEqual(result.subject_document_id, 1)
        self.assertIn("breakfast", result.exclude_constraints)

    def test_not_only_is_positive(self):
        query = "Compare not only Cedar Suite but also Lake Villa"
        self.assertEqual({doc.id for doc, _name, _score in match_all_documents(query, self.docs)}, {1, 2})
        self.assertEqual(split_exclusions(query)[1], [])

    def test_negative_tokens_cannot_combine_with_positive_qualifier(self):
        docs = [document(1, "Cedar Suites"), document(2, "Cedar Cabins")]
        query = "I'm avoiding suites: which cedar-lined stays are quiet and how do they compare on price?"
        self.assertEqual(match_all_documents(query, docs), [])
        result = contract(query, docs)
        self.assertEqual(result.mode, "filter")
        self.assertIsNone(result.resolved_subject)
        self.assertEqual(result.explicit_document_ids(), [])
        self.assertIn("they", result.resolved_query)
        self.assertIn("suites", result.exclude_constraints)

    def test_local_plural_set_does_not_inherit_previous_entity(self):
        history = [{"role": "user", "content": "Tell me about Cedar Suite"}]
        query = "Without Cedar Suite, which lakeside stays are quiet and how do they compare on price?"
        result = contract(query, self.docs, history)
        self.assertIsNone(result.resolved_subject)
        self.assertEqual(result.explicit_document_ids(), [])
        self.assertIn("they", result.resolved_query)

    def test_local_plural_set_does_not_collapse_qualifier_title(self):
        query = "Which lake villa stays are quiet and how do they compare on price?"
        result = contract(query, self.docs)
        self.assertIsNone(result.resolved_subject)
        self.assertEqual(result.explicit_document_ids(), [])

    def test_they_followup_preserves_positive_pair(self):
        history = [{"role": "user", "content": "Compare Lake Villa and Garden Loft"}]
        result = contract("How do they compare on price?", self.docs, history)
        self.assertEqual(set(result.explicit_document_ids()), {2, 3})

    def test_history_exclusion_cannot_become_active_subject(self):
        history = [{"role": "user", "content": "Exclude Cedar Suite; tell me about Lake Villa"}]
        result = contract("How much is it?", self.docs, history)
        self.assertEqual(result.subject_document_id, 2)

    def test_new_exclusion_removes_old_active_subject(self):
        history = [{"role": "user", "content": "Tell me about Cedar Suite"}]
        result = contract("Exclude Cedar Suite; how much is it?", self.docs, history)
        self.assertIsNone(result.subject_document_id)
        self.assertEqual(result.explicit_document_ids(), [])

    def test_excluded_history_not_resurrected_from_assistant(self):
        history = [
            {"role": "user", "content": "Tell me about Cedar Suite"},
            {"role": "assistant", "content": "Cedar Suite is spacious."},
            {"role": "user", "content": "Exclude Cedar Suite"},
        ]
        result = contract("How much is it?", self.docs, history)
        self.assertIsNone(result.subject_document_id)

    def test_history_comparison_keeps_only_positive_entities(self):
        history = [{"role": "user", "content": "Exclude Cedar Suite and compare Lake Villa and Garden Loft"}]
        result = contract("How do they compare on price?", self.docs, history)
        self.assertEqual(set(result.explicit_document_ids()), {2, 3})

    def test_exclusion_not_positive_catalog_scope(self):
        self.assertNotIn("cedar", extract_catalog_scope("Exclude Cedar Suite; list lakeside stays"))
        self.assertNotIn("suite", extract_catalog_scope("Exclude Cedar Suite; list lakeside stays"))

    def test_router_comparison_entities_exclude_negative_clause(self):
        is_comparison, names = is_comparison_query("Exclude Cedar Suite and compare Lake Villa and Garden Loft")
        self.assertTrue(is_comparison)
        self.assertEqual(names, ["lake villa", "garden loft"])

    def test_existing_filter_exclusions_preserved(self):
        for query, expected in [
            ("Which are powders rather than capsules, softgels, or gummies?", {"capsule", "softgel", "gummy"}),
            ("Show non-smoking rooms", {"smoking"}),
            ("Show rooms without breakfast", {"breakfast"}),
        ]:
            with self.subTest(query=query):
                self.assertEqual(set(extract_filter_attributes(query)["exclude"]), expected)

    def test_failed_widget_question_keeps_positive_result_set(self):
        docs = [document(1, "Turmeric Gummies"), document(2, "Joint Support"), document(3, "Turmeric Boost")]
        query = (
            "I'm avoiding gummies: which turmeric-containing products in your catalog support joint comfort, "
            "and how do they compare on key ingredients, daily serving/use directions, listed single-bottle price, "
            "and the product pages' results timelines? Include direct product links, tell me the price difference, "
            "and keep any timelines qualified rather than guaranteed."
        )
        result = contract(query, docs)
        self.assertIsNone(result.resolved_subject)
        self.assertEqual(result.explicit_document_ids(), [])
        self.assertEqual(result.comparison_entities, [])
        self.assertIn("gummies", result.exclude_constraints)
        self.assertIn("they", result.resolved_query)
        self.assertNotIn("turmeric gummies", result.resolved_query)
        self.assertEqual(result.mode, "filter")


if __name__ == "__main__":
    unittest.main()
