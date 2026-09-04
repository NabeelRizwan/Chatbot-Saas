"""Qualification evidence survives compact context; all provider calls are mocked."""

import re
import unittest
from unittest.mock import patch

from services import conversational_engine as engine
from services import rag_service as rag
from test_phase_l3_multi_entity_conversational_rag import contract, document, item
from test_required_evidence_retention import retrieve_fixture


class QualificationContextTests(unittest.TestCase):
    query = (
        "Which options support team collaboration with offline access, "
        "and how do their prices compare?"
    )
    first_detail = "Includes offline access and supports team collaboration for distributed work."
    second_detail = "Supports team collaboration and includes offline access for remote work."

    def rows(self, second_detail=None, heading="Product Description"):
        rows = []
        for doc_id, name, detail, price in (
            (1, "Aster", self.first_detail, 12),
            (2, "Boreal", second_detail or self.second_detail, 18),
        ):
            row = item(doc_id, doc_id, name,
                       f"# {name}\n\nOne-time purchase\n\n${price}\n\n"
                       f"{heading}\n\n{detail}\n\nUnrequested section\n\nOptional text.")
            row["required_fields"] = ["entity_detail", "price", "benefits"]
            row["field_coverage"] = {"price": "SUPPORTED", "benefits": "SUPPORTED"}
            rows.append(row)
        return rows

    def assemble(self, rows):
        qc = contract(self.query, [r["document"] for r in rows])
        used, context = engine.compress_and_rerank_chunks(rows, self.query, 2500, qc.mode, qc)
        return qc, used, context

    def test_two_qualifying_descriptions_reach_final_answer_requirements(self):
        rows = self.rows()
        qc, used, context = self.assemble(rows)
        prompt = rag.build_rag_prompt(self.query, rows, [], context, qc.mode, query_contract=qc)
        self.assertEqual({r["document"].id for r in used}, {1, 2})
        for name, detail in (("Aster", self.first_detail), ("Boreal", self.second_detail)):
            section = next(s for s in re.split(r"(?=### Source:)", context) if s.startswith(f"### Source: {name} |"))
            self.assertIn(f"- entity_detail: {detail}", section)
            self.assertIn(detail, prompt)
        self.assertIn("Do not invent or omit matching items", prompt)
        self.assertLessEqual(len(context), 2500)

    def test_missing_qualification_is_not_invented_or_copied_between_entities(self):
        unavailable = "Supports team collaboration; a network connection is required."
        _qc, _used, context = self.assemble(self.rows(second_detail=unavailable))
        sections = {name: next(s for s in re.split(r"(?=### Source:)", context) if s.startswith(f"### Source: {name} |"))
                    for name in ("Aster", "Boreal")}
        self.assertIn("offline access", sections["Aster"])
        self.assertNotIn("offline access", sections["Boreal"])
        self.assertIn(unavailable, sections["Boreal"])

    def test_excluded_entity_stays_out_while_both_positive_bodies_survive(self):
        rows = self.rows()
        excluded = item(3, 3, "Trial Tier", "# Trial Tier\n\nProduct Description\n\n" + self.first_detail + " Price $8.")
        pairs = [(r["chunk"], r["document"]) for r in rows + [excluded]]
        for chunk, doc in pairs:
            chunk.document_id = doc.id
        query = "Exclude Trial Tier; compare Aster and Boreal on price and benefits"
        retrieved, qc, _trace = retrieve_fixture([r["document"] for r in rows + [excluded]], pairs, query)
        used, context = engine.compress_and_rerank_chunks(retrieved, query, 3500, qc.mode, qc)
        self.assertEqual({r["document"].id for r in used}, {1, 2})
        self.assertNotIn("Trial Tier", context)
        self.assertIn(self.first_detail, context)
        self.assertIn(self.second_detail, context)

    def test_verifier_receives_both_bodies_refuting_false_single_option_claim(self):
        # Verify the actual verifier's input, not a mocked model's judgement.
        # Its invocation policy is intentionally outside this assembly repair.
        _qc, _used, context = self.assemble(self.rows())
        draft = "Aster is the only qualifying option, priced at $12."
        with patch.object(engine, "generate", return_value=draft) as generate:
            engine.verify_answer(None, self.query, draft, context, "Use supplied facts only.", True)
        prompt = generate.call_args.kwargs["prompt"]
        self.assertIn(self.first_detail, prompt)
        self.assertIn(self.second_detail, prompt)
        self.assertIn(draft, prompt)
        self.assertIn("Did it accidentally ignore useful business information?", prompt)

    def test_existing_explicit_comparison_gate_rejects_false_single_option(self):
        rows = self.rows()
        qc = contract("Compare Aster and Boreal on price and benefits", [r["document"] for r in rows])
        draft = "Aster is the only qualifying option. It supports team collaboration and costs $12."
        missing = rag._extended_coverage_missing(
            draft, qc, rag._retrieval_field_coverage(rows, qc.requested_fields),
            rag._answer_field_coverage(draft, qc.requested_fields), [], rows,
        )
        self.assertIn("compared entities", missing)

    def test_description_heading_boundaries_are_domain_independent(self):
        for heading in ("Product Description", "Service Description", "Overview"):
            with self.subTest(heading=heading):
                _qc, _used, context = self.assemble(self.rows(heading=heading))
                self.assertIn(f"entity_detail: {self.first_detail}", context)
                self.assertIn(f"entity_detail: {self.second_detail}", context)

    def test_existing_heading_without_checkout_chrome_keeps_body(self):
        row = item(1, 1, "Aster", "Overview\n\n" + self.first_detail)
        self.assertEqual(engine._required_field_parts([row], "entity_detail"), [self.first_detail])

    def test_polish_does_not_remove_either_supported_entity(self):
        answer = "Aster costs $12; Boreal costs $18. Both include offline access and support team collaboration."
        self.assertEqual(engine.polish_answer(None, self.query, answer, "", True), answer)


if __name__ == "__main__":
    unittest.main()
