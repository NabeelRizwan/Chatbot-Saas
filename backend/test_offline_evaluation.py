"""Saved-answer evaluation tests; no app, database, provider or network imports."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from evaluation import Dataset, ReviewSet, Run, compare_runs, evaluate_run, review_template
from evaluation.__main__ import main
from evaluation.schema import Latency, output_digest
from evaluation.scoring import reference_fbeta


def fixture():
    dataset = Dataset.model_validate({"name": "two-store-reference", "cases": [{
        "id": "shop-a:care", "dataset": "shop-a", "split": "heldout",
        "question": "How do I clean this item? Is water safe?",
        "reference": "Use a dry cloth. Do not immerse in water.",
        "facts": [{"id": "cloth", "text": "Use a dry cloth", "source_ids": ["care"]},
                  {"id": "water", "text": "Do not immerse in water", "source_ids": ["care"]}],
        "exclusions": [{"id": "solvent", "text": "Do not recommend solvents"}],
        "sources": [{"id": "care", "excerpt": "Use a dry cloth. Do not immerse in water or use solvents."}],
        "require_citations": True,
    }]})
    run = Run.model_validate({"name": "candidate", "pipeline_revision": "test-revision", "outputs": [{
        "case_id": "shop-a:care", "answer": "Use a dry cloth. Do not immerse in water.",
        "cited_source_ids": ["care"], "retrieved_source_ids": ["care"],
        "latency": {"retrieval_ms": 500, "total_ms": 3300, "first_token_ms": 1500},
    }]})
    return dataset, run


def approved(dataset, run, fact_verdicts=None, exclusion="respected", extra=None):
    template = review_template(dataset, run, "reviewer-1", "assisted_review").model_dump()
    for review in template["reviews"]:
        review["all_claims_reviewed"] = True
        for item in review["facts"]:
            item.update(verdict=(fact_verdicts or {}).get(item["fact_id"], "covered"),
                        reason="Reviewed exact saved answer against reference")
        for item in review["exclusions"]:
            item.update(verdict=exclusion, reason="Reviewed the explicit restriction")
        review["extra_claims"] = extra or []
    return ReviewSet.model_validate(template)


def score(dataset, run, reviews=None):
    return evaluate_run(dataset, run, reviews, trusted_reviewers={"reviewer-1"})


class OfflineEvaluationTests(unittest.TestCase):
    def test_complete_answer_passes_annotated_checks(self):
        data, run = fixture()
        report = score(data, run, approved(data, run))
        self.assertEqual(report["summary"]["pass"], 1)
        self.assertEqual(report["cases"][0]["fact_recall"], 1)
        self.assertEqual(report["cases"][0]["reference_fact_f1"], 1)
        self.assertEqual(report["cases"][0]["cited_reference_source_coverage"]["coverage"], 1)

    def test_missing_fact_is_not_complete_even_with_fast_answer(self):
        data, run = fixture()
        run.outputs[0].answer = "Use a dry cloth."
        run.outputs[0].latency.total_ms = 100
        result = score(data, run, approved(data, run, {"water": "missing"}))["cases"][0]
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["fact_recall"], .5)
        self.assertAlmostEqual(result["reference_fact_f1"], 2 / 3)

    def test_wrong_negation_requires_semantic_review_not_keyword_overlap(self):
        data, run = fixture()
        data.cases[0].fixtures.contains = ["immerse in water"]
        run.outputs[0].answer = "Use a dry cloth. Immerse in water.".replace("Immerse", "immerse")
        result = score(data, run, approved(data, run, {"water": "contradicted"}))["cases"][0]
        self.assertTrue(result["fixture_checks"][0]["passed"])
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["contradictions"], 1)
        self.assertEqual(result["counts"], {"tp": 1, "fp": 1, "fn": 1})

    def test_conflicting_reference_directions_both_required(self):
        data, run = fixture()
        case = data.cases[0]
        case.reference = "The label says one scoop; the FAQ says two. These directions conflict."
        case.facts[0].text = "The label says one scoop"
        case.facts[1].text = "The FAQ says two scoops; disclose the conflict"
        run.outputs[0].answer = "The label says one scoop."
        report = score(data, run, approved(data, run, {"water": "missing"}))
        self.assertEqual(report["summary"]["fail"], 1)
        run.outputs[0].answer = case.reference
        self.assertEqual(score(data, run, approved(data, run))["summary"]["pass"], 1)

    def test_exclusion_violation_overrides_full_fact_recall(self):
        data, run = fixture()
        run.outputs[0].answer += " Try a solvent too."
        result = score(data, run, approved(data, run, exclusion="violated"))["cases"][0]
        self.assertEqual(result["fact_recall"], 1)
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["exclusion_violations"], 1)

    def test_unsupported_extra_claim_prevents_pass(self):
        data, run = fixture()
        run.outputs[0].answer += " It cures allergies."
        reviews = approved(data, run, extra=[{"text": "It cures allergies", "verdict": "unsupported",
                                             "reason": "No supporting reference"}])
        self.assertEqual(score(data, run, reviews)["summary"]["fail"], 1)

    def test_empty_answer_never_perfect_even_with_approved_judge(self):
        data, run = fixture()
        run.outputs[0].answer = "   "
        result = score(data, run, approved(data, run))["cases"][0]
        self.assertEqual(result["status"], "fail")
        self.assertIsNone(result["reference_fact_f1"])

    def test_literal_assertion_failure_does_not_claim_semantic_failure(self):
        data, run = fixture()
        data.cases[0].fixtures.contains = ["A different exact wording"]
        result = score(data, run, approved(data, run))["cases"][0]
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["semantic_status"], "pass")
        self.assertEqual(result["fact_recall"], 1)

    def test_timeout_with_partial_answer_cannot_pass(self):
        data, run = fixture()
        run.outputs[0].status = "timeout"
        result = score(data, run, approved(data, run))["cases"][0]
        self.assertEqual(result["status"], "fail")
        self.assertIn("output_timeout", result["reasons"])

    def test_missing_reference_or_facts_is_inconclusive(self):
        for missing in ("reference", "facts"):
            with self.subTest(missing=missing):
                data, run = fixture()
                setattr(data.cases[0], missing, "" if missing == "reference" else [])
                data.cases[0].require_citations = False
                result = score(data, run, approved(data, run))["cases"][0]
                self.assertEqual(result["status"], "inconclusive")
                self.assertIsNone(result["reference_fact_f1"])

    def test_missing_judge_failed_judge_and_unknown_labels_are_inconclusive(self):
        data, run = fixture()
        self.assertEqual(score(data, run)["summary"]["inconclusive"], 1)
        for mutation in ("error", "facts", "all_claims_reviewed"):
            reviews = approved(data, run)
            setattr(reviews.reviews[0], mutation, "judge timed out" if mutation == "error"
                    else [] if mutation == "facts" else False)
            self.assertEqual(score(data, run, reviews)["summary"]["inconclusive"], 1)
        uncertain = approved(data, run, {"water": "uncertain"})
        self.assertEqual(score(data, run, uncertain)["summary"]["inconclusive"], 1)

    def test_invalid_and_duplicate_judge_labels_rejected(self):
        data, run = fixture()
        payload = approved(data, run).model_dump()
        payload["reviews"][0]["facts"][0]["verdict"] = "perfect"
        with self.assertRaises(ValidationError):
            ReviewSet.model_validate(payload)
        payload = approved(data, run).model_dump()
        payload["reviews"][0]["facts"].append(payload["reviews"][0]["facts"][0])
        with self.assertRaises(ValidationError):
            ReviewSet.model_validate(payload)

    def test_review_requires_explicit_trust_and_fixture_is_not_semantic(self):
        data, run = fixture()
        reviews = approved(data, run)
        self.assertEqual(evaluate_run(data, run, reviews)["summary"]["inconclusive"], 1)
        reviews.reviews[0].kind = "fixture"
        self.assertEqual(score(data, run, reviews)["summary"]["inconclusive"], 1)

    def test_review_cannot_be_reused_for_different_answer_or_reference(self):
        for change in ("answer", "reference", "sources"):
            data, run = fixture()
            reviews = approved(data, run)
            if change == "answer":
                run.outputs[0].answer += " changed"
            elif change == "reference":
                data.cases[0].reference += " changed"
            else:
                run.outputs[0].retrieved_source_ids.append("new-source")
            self.assertEqual(score(data, run, reviews)["summary"]["inconclusive"], 1)

    def test_citations_and_retrieval_coverage_are_separate(self):
        data, run = fixture()
        run.outputs[0].cited_source_ids = []
        result = score(data, run, approved(data, run))["cases"][0]
        self.assertEqual(result["semantic_status"], "pass")
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["retrieved_reference_source_coverage"]["coverage"], 1)
        self.assertEqual(result["cited_reference_source_coverage"]["coverage"], 0)

    def test_missing_source_mapping_does_not_look_complete(self):
        data, run = fixture()
        data.cases[0].facts[0].source_ids = []
        result = score(data, run, approved(data, run))["cases"][0]
        self.assertEqual(result["status"], "inconclusive")
        self.assertIsNone(result["cited_reference_source_coverage"]["coverage"])

    def test_unobserved_sources_are_unknown_not_empty(self):
        data, run = fixture()
        run.outputs[0].cited_source_ids = None
        run.outputs[0].retrieved_source_ids = None
        result = score(data, run, approved(data, run))["cases"][0]
        self.assertEqual(result["status"], "inconclusive")
        self.assertIsNone(result["cited_reference_source_coverage"]["coverage"])
        self.assertFalse(result["retrieved_reference_source_coverage"]["observed"])
        data.cases[0].require_citations = False
        self.assertEqual(score(data, run, approved(data, run))["summary"]["pass"], 1)

    def test_latency_missing_is_not_zero_and_is_not_quality(self):
        data, run = fixture()
        reviews = approved(data, run)
        digest = output_digest(run.outputs[0])
        run.outputs[0].latency.total_ms = 99000
        report = score(data, run, reviews)
        self.assertEqual(output_digest(run.outputs[0]), digest)
        self.assertEqual(report["summary"]["pass"], 1)
        self.assertEqual(report["summary"]["latency_ms"]["total_ms"]["mean"], 99000)
        self.assertIsNone(report["summary"]["latency_ms"]["provider_ms"]["mean"])
        for value in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValidationError):
                Latency(total_ms=value)

    def test_missing_output_stays_in_denominator_and_unknown_case_rejected(self):
        data, run = fixture()
        run.outputs = []
        report = score(data, run)
        self.assertEqual(report["summary"]["total"], 1)
        self.assertEqual(report["summary"]["pass_fraction_all_cases"], 0)
        data, run = fixture()
        run.outputs[0].case_id = "not-in-dataset"
        with self.assertRaises(ValueError):
            score(data, run)

    def test_multidataset_heldout_comparison_with_paired_timings(self):
        data, baseline = fixture()
        second = data.cases[0].model_copy(deep=True)
        second.id, second.dataset, second.split = "shop-b:care", "shop-b", "development"
        data.cases.append(second)
        second_output = baseline.outputs[0].model_copy(deep=True)
        second_output.case_id = second.id
        baseline.outputs.append(second_output)
        candidate = baseline.model_copy(deep=True)
        baseline.metadata["concurrency"] = "1"
        candidate.metadata["concurrency"] = "10"
        candidate.outputs[0].answer = "Use a dry cloth."
        candidate.outputs[0].latency.total_ms = 3200
        new_reviews = approved(data, candidate)
        new_reviews.reviews[0].facts[1].verdict = "missing"
        report = compare_runs(data, baseline, candidate, approved(data, baseline), new_reviews,
                              trusted_reviewers={"reviewer-1"})
        self.assertEqual(report["comparison"]["regression"], 1)
        self.assertEqual(report["comparison"]["unchanged_pass"], 1)
        self.assertEqual(len(report["groups"]), 2)
        self.assertEqual(report["condition_differences"]["concurrency"], {"baseline": "1", "candidate": "10"})
        self.assertEqual(report["paired_cases"][0]["latency_delta_ms_candidate_minus_baseline"]["total_ms"], -100)

    def test_ragas_count_adapter_rejects_empty_reference_and_invalid_counts(self):
        self.assertIsNone(reference_fbeta(0, 0, 0))
        self.assertIsNone(reference_fbeta(0, 2, 0))
        self.assertEqual(reference_fbeta(0, 0, 2), 0)
        self.assertEqual(reference_fbeta(1, 1, 1), .5)
        for counts in ((-1, 0, 1), (True, 0, 1), (1.5, 0, 1)):
            with self.assertRaises(ValueError):
                reference_fbeta(*counts)

    def test_cli_writes_report_never_overwrites_and_fails_closed(self):
        data, run = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data.json").write_text(data.model_dump_json(), encoding="utf-8")
            (root / "run.json").write_text(run.model_dump_json(), encoding="utf-8")
            args = ["evaluate", "--dataset", str(root / "data.json"), "--run", str(root / "run.json"),
                    "--output", str(root / "report.json")]
            self.assertEqual(main(args), 1)  # No judge, so inconclusive rather than green.
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(args), 2)  # Existing evidence cannot be overwritten.
            report = json.loads((root / "report.json").read_text())
            self.assertEqual(report["summary"]["inconclusive"], 1)

    def test_cli_comparison_with_unreviewed_baseline_stays_inconclusive(self):
        data, run = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, model in (("data", data), ("run", run), ("reviews", approved(data, run))):
                (root / f"{name}.json").write_text(model.model_dump_json(), encoding="utf-8")
            args = ["compare", "--dataset", str(root / "data.json"), "--run", str(root / "run.json"),
                    "--baseline", str(root / "run.json"), "--reviews", str(root / "reviews.json"),
                    "--trusted-reviewer", "reviewer-1", "--output", str(root / "report.json")]
            self.assertEqual(main(args), 1)
            report = json.loads((root / "report.json").read_text())
            self.assertEqual(report["candidate"]["summary"]["pass"], 1)
            self.assertEqual(report["comparison"]["inconclusive"], 1)


if __name__ == "__main__":
    unittest.main()
