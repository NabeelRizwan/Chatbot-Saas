"""Evaluate saved outputs without generating answers or calling a judge."""

from __future__ import annotations

import math
import statistics

from .schema import Case, Dataset, Output, Review, ReviewSet, Run, case_digest, output_digest
from .scoring import reference_fbeta


LIMITATIONS = [
    "Passing means the supplied reference checks passed, not universal correctness.",
    "Semantic labels are supplied by explicitly trusted reviewers; this tool does not verify their truth.",
    "Literal fixture checks cannot determine meaning, negation, omissions or factual correctness.",
    "Source coverage matches reference source IDs; it does not establish that a citation supports a claim.",
    "Latency is reported separately from quality; missing measurements are never treated as zero.",
]


def _source_coverage(case: Case, ids: list[str] | None) -> dict:
    mapped = [fact for fact in case.facts if fact.source_ids]
    matched = sum(bool(set(fact.source_ids) & set(ids)) for fact in mapped) if ids is not None else None
    unmapped = len(case.facts) - len(mapped)
    return {
        "matched_facts": matched, "mapped_facts": len(mapped), "unmapped_facts": unmapped,
        "observed": ids is not None,
        "coverage": matched / len(mapped) if mapped and not unmapped and matched is not None else None,
    }


def _evaluate_case(case: Case, output: Output | None, review: Review | None,
                   trusted_reviewers: set[str]) -> dict:
    result = {
        "case_id": case.id, "dataset": case.dataset, "split": case.split,
        "case_sha256": case_digest(case), "question": case.question,
        "status": "inconclusive", "semantic_status": "inconclusive", "reasons": [],
        "fact_recall": None, "reference_fact_f1": None, "contradictions": None,
        "exclusion_violations": None, "counts": None, "reviewer": None,
        "review_kind": None, "fixture_checks": [], "latency": {},
        "retrieved_reference_source_coverage": None,
        "cited_reference_source_coverage": None,
    }
    reasons = result["reasons"]
    if output is None:
        reasons.append("missing_output")
        return result
    result.update(answer=output.answer, output_sha256=output_digest(output),
                  latency=output.latency.model_dump(mode="json"))
    result["retrieved_reference_source_coverage"] = _source_coverage(case, output.retrieved_source_ids)
    citation = _source_coverage(case, output.cited_source_ids)
    result["cited_reference_source_coverage"] = citation
    result["cited_ids_outside_reference"] = (sorted(
        set(output.cited_source_ids) - {source.id for source in case.sources})
        if output.cited_source_ids is not None else None)
    output_failure = output.status != "ok" or not output.answer.strip()
    fixture_failure = False
    if output.status != "ok":
        reasons.append(f"output_{output.status}")
    if not output.answer.strip():
        reasons.append("empty_answer")
    for operation, values in (("contains", case.fixtures.contains), ("excludes", case.fixtures.excludes)):
        for text in values:
            passed = text in output.answer if operation == "contains" else text not in output.answer
            result["fixture_checks"].append({"operation": operation, "text": text, "passed": passed})
            if not passed:
                fixture_failure = True
                reasons.append("literal_fixture_failed")

    valid_reference = bool(case.reference.strip() and case.facts and all(f.text.strip() for f in case.facts))
    if not valid_reference:
        reasons.append("missing_reference_or_required_facts")
    valid_review = valid_reference and review is not None
    if review is None:
        reasons.append("missing_review")
    else:
        result.update(reviewer=review.reviewer, review_kind=review.kind)
        checks = {
            "review_case_mismatch": review.case_id != case.id or review.case_sha256 != case_digest(case),
            "review_output_mismatch": review.output_sha256 != output_digest(output),
            "untrusted_reviewer": review.reviewer not in trusted_reviewers,
            "fixture_review_is_not_semantic": review.kind == "fixture",
            "judge_error": review.status != "complete" or bool(review.error),
            "incomplete_claim_review": not review.all_claims_reviewed,
            "incomplete_fact_labels": {f.fact_id for f in review.facts} != {f.id for f in case.facts},
            "incomplete_exclusion_labels": {e.exclusion_id for e in review.exclusions} != {e.id for e in case.exclusions},
            "uncertain_judgement": any(item.verdict == "uncertain" for item in
                                       review.facts + review.exclusions + review.extra_claims),
        }
        for reason, failed in checks.items():
            if failed:
                valid_review = False
                reasons.append(reason)
    if valid_review and not output_failure:
        tp = sum(f.verdict == "covered" for f in review.facts)
        fn = len(case.facts) - tp
        contradictions = sum(f.verdict == "contradicted" for f in review.facts)
        contradictions += sum(c.verdict == "contradicted" for c in review.extra_claims)
        fp = sum(f.verdict == "contradicted" for f in review.facts)
        fp += sum(c.verdict in {"unsupported", "contradicted"} for c in review.extra_claims)
        violations = sum(e.verdict == "violated" for e in review.exclusions)
        complete = fn == 0 and fp == 0 and violations == 0
        result.update(
            semantic_status="pass" if complete else "fail", fact_recall=tp / len(case.facts),
            reference_fact_f1=reference_fbeta(tp, fp, fn), contradictions=contradictions,
            exclusion_violations=violations, counts={"tp": tp, "fp": fp, "fn": fn},
            fact_judgements=[f.model_dump() for f in review.facts],
            exclusion_judgements=[e.model_dump() for e in review.exclusions],
            extra_claims=[c.model_dump() for c in review.extra_claims],
        )
        if fn:
            reasons.append("required_facts_missing_or_contradicted")
        if fp:
            reasons.append("unsupported_or_contradicted_claims")
        if violations:
            reasons.append("exclusion_violated")
    elif output_failure:
        # Do not accept even a supposedly perfect judge result for a failed/empty output.
        result["semantic_status"] = "fail"

    citation_unknown = case.require_citations and citation["coverage"] is None
    citation_failed = case.require_citations and citation["coverage"] is not None and citation["coverage"] < 1
    if citation_unknown:
        reasons.append("required_source_mapping_missing")
    if citation_failed:
        reasons.append("required_source_ids_missing")
    if output_failure or fixture_failure or result["semantic_status"] == "fail" or citation_failed:
        result["status"] = "fail"
    elif result["semantic_status"] == "pass" and not citation_unknown:
        result["status"] = "pass"
    result["reasons"] = list(dict.fromkeys(reasons))
    return result


def _distribution(values: list[float]) -> dict:
    if not values:
        return {"count": 0, "mean": None, "median": None, "p95": None}
    ordered = sorted(values)
    return {"count": len(values), "mean": statistics.mean(values),
            "median": statistics.median(values), "p95": ordered[math.ceil(len(values) * .95) - 1]}


def _summary(cases: list[dict]) -> dict:
    counts = {status: sum(case["status"] == status for case in cases)
              for status in ("pass", "fail", "inconclusive")}
    return {
        "total": len(cases), **counts,
        "pass_fraction_all_cases": counts["pass"] / len(cases) if cases else None,
        "scored_fact_cases": sum(case["fact_recall"] is not None for case in cases),
        "latency_ms": {stage: _distribution([case["latency"][stage] for case in cases
                       if case["latency"].get(stage) is not None])
                       for stage in ("retrieval_ms", "first_token_ms", "total_ms", "provider_ms")},
    }


def evaluate_run(dataset: Dataset, run: Run, reviews: ReviewSet | None = None,
                 *, trusted_reviewers: set[str] | None = None) -> dict:
    """Missing outputs remain in the denominator; unknown case IDs are input errors."""
    outputs = {output.case_id: output for output in run.outputs}
    reviews_by_id = {review.case_id: review for review in (reviews or ReviewSet()).reviews}
    known = {case.id for case in dataset.cases}
    if (set(outputs) | set(reviews_by_id)) - known:
        raise ValueError("run/reviews contain case IDs outside the supplied dataset")
    results = [_evaluate_case(case, outputs.get(case.id), reviews_by_id.get(case.id),
                              trusted_reviewers or set()) for case in dataset.cases]
    groups = [{"dataset": name, "split": split,
               **_summary([row for row in results if row["dataset"] == name and row["split"] == split])}
              for name, split in sorted({(row["dataset"], row["split"]) for row in results})]
    return {"schema_version": 1, "metric_version": "reference-facts-v1", "run": run.name,
            "pipeline_revision": run.pipeline_revision, "metadata": run.metadata,
            "summary": _summary(results), "groups": groups, "cases": results,
            "limitations": LIMITATIONS}


def review_template(dataset: Dataset, run: Run, reviewer: str,
                    kind: str = "human") -> ReviewSet:
    outputs = {output.case_id: output for output in run.outputs}
    if set(outputs) - {case.id for case in dataset.cases}:
        raise ValueError("run contains case IDs outside the supplied dataset")
    return ReviewSet(reviews=[Review(
        case_id=case.id, case_sha256=case_digest(case), output_sha256=output_digest(outputs[case.id]),
        reviewer=reviewer, kind=kind, status="complete", all_claims_reviewed=False,
        facts=[{"fact_id": fact.id, "verdict": "uncertain", "reason": "Awaiting review"} for fact in case.facts],
        exclusions=[{"exclusion_id": item.id, "verdict": "uncertain", "reason": "Awaiting review"}
                    for item in case.exclusions],
    ) for case in dataset.cases if case.id in outputs])


def compare_runs(dataset: Dataset, baseline: Run, candidate: Run,
                 baseline_reviews: ReviewSet | None = None, candidate_reviews: ReviewSet | None = None,
                 *, trusted_reviewers: set[str] | None = None) -> dict:
    old = evaluate_run(dataset, baseline, baseline_reviews, trusted_reviewers=trusted_reviewers)
    new = evaluate_run(dataset, candidate, candidate_reviews, trusted_reviewers=trusted_reviewers)
    rows = []
    for before, after in zip(old["cases"], new["cases"]):
        old_status, new_status = before["status"], after["status"]
        if "inconclusive" in (old_status, new_status):
            outcome = "inconclusive"
        elif old_status == "pass" and new_status == "fail":
            outcome = "regression"
        elif old_status == "fail" and new_status == "pass":
            outcome = "improvement"
        else:
            outcome = "unchanged_pass" if new_status == "pass" else "unchanged_fail"
        deltas = {stage: after["latency"][stage] - before["latency"][stage]
                  if after["latency"].get(stage) is not None and before["latency"].get(stage) is not None else None
                  for stage in ("retrieval_ms", "first_token_ms", "total_ms", "provider_ms")}
        rows.append({"case_id": before["case_id"], "dataset": before["dataset"], "split": before["split"],
                     "baseline_status": old_status, "candidate_status": new_status, "outcome": outcome,
                     "score_delta_candidate_minus_baseline": {
                         metric: after[metric] - before[metric]
                         if after[metric] is not None and before[metric] is not None else None
                         for metric in ("fact_recall", "reference_fact_f1", "contradictions", "exclusion_violations")},
                     "latency_delta_ms_candidate_minus_baseline": deltas})
    def comparison_summary(selected):
        return {"total": len(selected), **{outcome: sum(row["outcome"] == outcome for row in selected)
                for outcome in ("regression", "improvement", "unchanged_pass", "unchanged_fail", "inconclusive")}}
    return {"schema_version": 1, "baseline": old, "candidate": new, "paired_cases": rows,
            "comparison": comparison_summary(rows),
            "condition_differences": {
                key: {"baseline": baseline.metadata.get(key), "candidate": candidate.metadata.get(key)}
                for key in sorted(set(baseline.metadata) | set(candidate.metadata))
                if baseline.metadata.get(key) != candidate.metadata.get(key)},
            "groups": [{"dataset": name, "split": split, **comparison_summary(
                [row for row in rows if row["dataset"] == name and row["split"] == split])}
                for name, split in sorted({(row["dataset"], row["split"]) for row in rows})],
            "limitations": LIMITATIONS}
