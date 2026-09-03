"""Offline explicit-field completeness tests; no provider calls or corpus writes."""

import unittest
from types import SimpleNamespace

from services.query_contract import extract_requested_fields, field_evidence_pattern
from services.rag_service import (
    _entity_field_completeness_missing, _select_complete_field_evidence,
    build_entity_field_matrix, build_rag_prompt,
)
from services.conversational_engine import compress_and_rerank_chunks
from test_phase_l3_multi_entity_conversational_rag import document, chunk, item, contract


class ExplicitFieldCompletenessTests(unittest.TestCase):
    def test_plural_field_names_are_normalized(self):
        fields = extract_requested_fields("Compare Alpha and Beta on ingredients, directions, prices and results timelines. Include direct product links.")
        self.assertTrue({"ingredients", "directions", "price", "results_timeframe", "link"} <= set(fields))

    def test_singular_fields_still_work(self):
        self.assertIn("results_timeframe", extract_requested_fields("What is the results timeline?"))

    def test_hotel_fields_are_all_retained(self):
        fields = extract_requested_fields("Compare these hotels on price, breakfast, check-in time and cancellation")
        self.assertTrue({"price", "breakfast", "check_in", "policy"} <= set(fields))

    def test_plan_fields_are_all_retained(self):
        fields = extract_requested_fields("Compare these plans on price, storage, limits and renewal terms")
        self.assertTrue({"price", "storage", "limits", "policy"} <= set(fields))

    def test_course_fields_are_all_retained(self):
        fields = extract_requested_fields("Compare these courses on duration, topics, prerequisites and certificate")
        self.assertTrue({"duration", "topics", "eligibility", "certificate"} <= set(fields))

    def test_unknown_explicit_field_gets_escaped_lexical_evidence_pattern(self):
        self.assertTrue(field_evidence_pattern("limits").search("The limit is 12 seats."))
        self.assertTrue(field_evidence_pattern("certificate").search("Certificates are issued after assessment."))
        self.assertFalse(field_evidence_pattern("a.*b").search("arbitrary b"))

    def test_field_matrix_includes_unknown_and_absent_fields_per_entity(self):
        docs = {1: document(1, "Alpha"), 2: document(2, "Beta")}
        chunks = {1: [chunk(1, 0, "Storage: 15 GB. Limits: 3 seats.")], 2: [chunk(2, 0, "Storage: 25 GB.")]}
        selected, coverage = build_entity_field_matrix(chunks, docs, [1, 2], ["storage", "limits"])
        self.assertEqual(coverage["1:limits"], "SUPPORTED")
        self.assertEqual(coverage["2:limits"], "ABSENT_AFTER_ADEQUATE_SEARCH")
        self.assertEqual({c.id for c in selected}, {1, 2})

    def test_numeric_section_retains_values_and_adjacent_bodies(self):
        chunks = [
            chunk(1, 1, "## How soon will I see results?\nIndividual results vary."),
            chunk(2, 4, "## What to Expect\n\n2-3 WEEKS"),
            chunk(3, 5, "### Initial stage\nProgress may begin.\n\n5-7 WEEKS"),
            chunk(4, 6, "### Later stage\nProgress may continue.\n\n9-11 WEEKS"),
            chunk(5, 7, "### Final stage\nOutcomes still vary."),
            chunk(6, 8, "## Refund policy\nUnrelated policy."),
        ]
        selected = _select_complete_field_evidence(chunks, "results_timeframe", document(1, "Alpha"))
        self.assertEqual({c.id for c in selected}, {1, 2, 3, 4, 5})

    def test_numeric_section_works_without_faq_anchor(self):
        rows = [chunk(1, 0, "## Schedule\n2-3 WEEKS"), chunk(2, 1, "### First stage\nTiming is approximate.")]
        selected = _select_complete_field_evidence(rows, "results_timeframe", document(1, "Alpha"))
        self.assertEqual([c.id for c in selected], [1, 2])

    def test_context_keeps_later_field_for_each_entity(self):
        docs = [document(1, "Alpha"), document(2, "Beta")]
        qc = contract("Compare Alpha and Beta on price, ingredients, directions and results timelines", docs)
        rows = []
        for doc_id, name in [(1, "Alpha"), (2, "Beta")]:
            for index, text in enumerate(["Price: $12", "Ingredients: A, B and C.", "Directions: Use daily.", "Results may appear in 2-3 weeks; individual results vary."]):
                rows.append(item(doc_id*10+index, doc_id, name, f"[{name}] {text}", priority=0.30))
        selected, context = compress_and_rerank_chunks(rows, qc.original_query, mode="comparison", query_contract=qc)
        self.assertEqual(len(selected), 8)
        self.assertEqual(context.count("Results may appear"), 2)
        self.assertLessEqual(len(context), 10000)

    def test_one_entity_value_does_not_cover_the_other(self):
        rows = [item(1, 1, "Alpha", "Price $12. Results may appear in 2-3 weeks."), item(2, 2, "Beta", "Price $15. Results may appear in 5-7 weeks.")]
        answer = "**Alpha**\nPrice: $12. Results: 2-3 weeks.\n\n**Beta**\nPrice: $15. Results vary."
        missing = _entity_field_completeness_missing(answer, rows, ["price", "results_timeframe"])
        self.assertTrue(any("Beta: results_timeframe" in field for field in missing))
        self.assertFalse(any("Alpha:" in field for field in missing))

    def test_absence_must_name_the_entity_and_field(self):
        rows = [item(1, 1, "Alpha", "Price $12."), item(2, 2, "Beta", "Price $15.")]
        answer = "Alpha\nPrice: $12. Certificate: not available.\n\nBeta\nPrice: $15."
        missing = _entity_field_completeness_missing(answer, rows, ["price", "certificate"])
        self.assertTrue(any("Beta: certificate" in field for field in missing))
        self.assertFalse(any("Alpha:" in field for field in missing))

    def test_unavailable_field_is_explicitly_accounted_for(self):
        rows = [item(1, 1, "Alpha", "Price $12."), item(2, 2, "Beta", "Price $15.")]
        answer = "Alpha\nPrice: $12. Certificate: not available.\n\nBeta\nPrice: $15. Certificate: not available."
        self.assertEqual(_entity_field_completeness_missing(answer, rows, ["price", "certificate"]), [])

    def test_false_absence_is_not_accepted_when_value_is_supplied(self):
        rows = [item(1, 1, "Alpha", "Price $12. Certificate awarded."), item(2, 2, "Beta", "Price $15. Certificate awarded.")]
        answer = "Alpha\nPrice: $12. Certificate awarded.\n\nBeta\nPrice: $15. Certificate not available."
        missing = _entity_field_completeness_missing(answer, rows, ["price", "certificate"])
        self.assertTrue(any("Beta: certificate (supply" in field for field in missing))

    def test_complete_values_pass_per_entity(self):
        rows = [item(1, 1, "Alpha", "Price $12. Storage: 15 GB."), item(2, 2, "Beta", "Price $15. Storage: 25 GB.")]
        answer = "Alpha\nPrice: $12. Storage: 15 GB.\n\nBeta\nPrice: $15. Storage: 25 GB."
        self.assertEqual(_entity_field_completeness_missing(answer, rows, ["price", "storage"]), [])

    def test_prompt_requires_values_or_entity_specific_absence(self):
        qc = contract("Compare Alpha and Beta on price and certificate", [document(1, "Alpha"), document(2, "Beta")])
        prompt = build_rag_prompt(qc.original_query, [], compressed_context="Alpha costs $12. Beta costs $15.", query_contract=qc)
        self.assertIn("concrete supported value", prompt)
        self.assertIn("explicitly identify that entity and field as unavailable", prompt)


if __name__ == "__main__":
    unittest.main()
