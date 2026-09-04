"""Ordered values and descriptions stay atomic, including single-field turns."""

import unittest
from unittest.mock import patch

from services import conversational_engine as engine
from services import rag_service as rag
from test_phase_l3_multi_entity_conversational_rag import chunk, document
from test_required_evidence_retention import retrieve_fixture


class OrderedFieldEvidenceTests(unittest.TestCase):
    def fixture(self):
        doc = document(1, "Aster")
        texts = [
            "### How soon will I see results?\n\nSome users may notice progress in 2–5 weeks; results vary.",
            "## Schedule\n\n1-2 MONTHS",
            "### Foundation stage\n\nBasic skills may develop with consistent practice.\n\n3-5 MONTHS",
            "### Application stage\n\nIndependent projects may become easier with practice.\n\n7-9 MONTHS",
            "### Advanced stage\n\nComplex work may become manageable; individual progress varies.",
        ]
        pairs = []
        for index, content in enumerate(texts):
            row = chunk(100 + index, index, content)
            row.document_id = 1
            pairs.append((row, doc))
        return doc, pairs

    def retrieve(self):
        doc, pairs = self.fixture()
        result, qc, _ = retrieve_fixture([doc], pairs, "How soon will I see results with Aster?")
        return result, qc

    def test_single_field_reserves_complete_sequence_before_cutoff(self):
        result, qc = self.retrieve()
        self.assertEqual(qc.requested_fields, ["results_timeframe"])
        self.assertEqual(qc.mode, "factual")
        self.assertTrue({100, 101, 102, 103, 104} <= {r["chunk"].id for r in result})
        self.assertTrue(all("results_timeframe" in r["required_fields"] for r in result))

    def test_reordered_scores_cannot_swap_value_description_pairs(self):
        result, qc = self.retrieve()
        for index, row in enumerate(result):
            row["score"] = index / 10
        _used, context = engine.compress_and_rerank_chunks(list(reversed(result)), qc.original_query, 2000, qc.mode, qc)
        self.assertIn("1-2 MONTHS Foundation stage Basic skills may develop", context)
        self.assertIn("3-5 MONTHS Application stage Independent projects may become easier", context)
        self.assertIn("7-9 MONTHS Advanced stage Complex work may become manageable", context)
        self.assertNotIn("7-9 MONTHS Application stage", context)

    def test_tight_budget_only_keeps_whole_pairs(self):
        result, qc = self.retrieve()
        _used, context = engine.compress_and_rerank_chunks(result, qc.original_query, 440, qc.mode, qc)
        self.assertLessEqual(len(context), 440)
        for value, label, body in (
            ("1-2 MONTHS", "Foundation stage", "Basic skills may develop with consistent practice."),
            ("3-5 MONTHS", "Application stage", "Independent projects may become easier with practice."),
            ("7-9 MONTHS", "Advanced stage", "Complex work may become manageable; individual progress varies."),
        ):
            if value in context:
                self.assertIn(f"{value} {label} {body}", context)

    def test_same_atomic_evidence_reaches_generation_and_verifier(self):
        result, qc = self.retrieve()
        _used, context = engine.compress_and_rerank_chunks(result, qc.original_query, 2000, qc.mode, qc)
        generation_prompt = rag.build_rag_prompt(qc.original_query, result, [], context, qc.mode, query_contract=qc)
        # Inspect verifier input without pretending a mock is a live model judgement.
        wrong = "The Application stage may occur in 7-9 months."
        with patch.object(engine, "generate", return_value=wrong) as generate:
            engine.verify_answer(None, qc.original_query, wrong, context, "Use supplied facts only.", True)
        verifier_prompt = generate.call_args.kwargs["prompt"]
        for prompt in (generation_prompt, verifier_prompt):
            self.assertIn("3-5 MONTHS Application stage Independent projects may become easier", prompt)
            self.assertIn("7-9 MONTHS Advanced stage Complex work may become manageable", prompt)
        self.assertIn("Is it factually consistent with the business information?", verifier_prompt)

    def test_single_ordinary_timeline_fact_does_not_enable_group_reservation(self):
        doc, pairs = self.fixture()
        result, qc, _ = retrieve_fixture([doc], pairs[:1], "How soon will I see results with Aster?")
        self.assertFalse(any(r.get("required_fields") for r in result))
        _used, context = engine.compress_and_rerank_chunks(result, qc.original_query, 2000, qc.mode, qc)
        self.assertIn(pairs[0][0].content, context)

    def test_atomic_units_do_not_depend_on_domain_or_time_unit(self):
        doc, pairs = self.fixture()
        for unit in ("WEEKS", "HOURS", "SEATS", "LESSONS"):
            with self.subTest(unit=unit):
                rows = []
                for source, _doc in pairs[1:]:
                    copy = chunk(source.id, source.chunk_index, source.content.replace("MONTHS", unit))
                    rows.append({"chunk": copy, "document": doc, "required_fields": ["duration"], "score": 0.9})
                parts = engine._required_field_parts(rows, "duration")
                self.assertTrue(any(f"3-5 {unit} Application stage Independent projects" in p for p in parts))
                self.assertFalse(any(f"7-9 {unit} Application stage" in p for p in parts))

    def test_different_entity_sequences_are_not_combined(self):
        result, qc = self.retrieve()
        other = document(2, "Boreal")
        rows = list(result)
        for row in result:
            source = row["chunk"]
            copy = chunk(source.id + 100, source.chunk_index, source.content.replace("Application stage", "Studio stage").replace("3-5 MONTHS", "4-6 MONTHS"))
            rows.append({**row, "document": other, "chunk": copy})
        _used, context = engine.compress_and_rerank_chunks(rows, qc.original_query, 4000, "filter", None)
        self.assertIn("3-5 MONTHS Application stage", context)
        self.assertIn("4-6 MONTHS Studio stage", context)
        self.assertNotIn("4-6 MONTHS Application stage", context)


if __name__ == "__main__":
    unittest.main()
