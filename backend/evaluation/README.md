# Offline answer evaluation

This package scores saved answers against fixed, explicitly reviewed references. It runs outside the chatbot: no provider calls, application imports, network calls, model loading or extra runtime dependencies. It uses the Pydantic dependency already installed by the backend.

It does **not** generate semantic judgements. A human, an assisted review, or a separately run judge must annotate the saved answer. Only reviewers explicitly trusted for that invocation are accepted. Trust is an operator decision, not an authentication mechanism. An incorrect trusted annotation can still produce an incorrect score.

## Inputs

Keep private customer datasets and run reports outside the repository. Use globally unique case IDs and record the immutable pipeline revision and relevant test settings in each run. Write references before comparing candidates, keep held-out cases separate from development cases, and do not change expected facts to improve a candidate's score.

A dataset can include any number of websites and splits (`development`, `heldout`, `evaluation`). A required fact should be one atomic, question-relevant requirement. When a source conflicts, include each direction and the obligation to disclose the conflict as separate facts. Exclusions describe prohibited recommendations or other explicit restrictions.

```json
{
  "schema_version": 1,
  "name": "store-acceptance-v1",
  "cases": [{
    "id": "store:care-1",
    "dataset": "store",
    "split": "heldout",
    "question": "How do I clean this item?",
    "reference": "Use a dry cloth. Do not immerse in water.",
    "facts": [
      {"id": "cloth", "text": "Use a dry cloth", "source_ids": ["care"]},
      {"id": "water", "text": "Do not immerse in water", "source_ids": ["care"]}
    ],
    "exclusions": [{"id": "solvent", "text": "Do not recommend solvents"}],
    "sources": [{"id": "care", "excerpt": "Use a dry cloth. Do not immerse in water or use solvents."}],
    "require_citations": true
  }]
}
```

Each run contains the exact saved answer and measured times. Use `null` or omit timings that were not measured; never estimate missing values as zero. `first_token_ms` and `total_ms` are independent observations, not inferred by adding stages. Record test concurrency, provider/model, cache state and timing definitions in run `metadata` so comparisons are interpretable.

```json
{
  "schema_version": 1,
  "name": "candidate",
  "pipeline_revision": "immutable-commit-or-snapshot-id",
  "metadata": {"provider": "saved-test-output", "concurrency": "1"},
  "outputs": [{
    "case_id": "store:care-1",
    "answer": "Use a dry cloth. Do not immerse in water.",
    "status": "ok",
    "cited_source_ids": ["care"],
    "retrieved_source_ids": ["care"],
    "latency": {"retrieval_ms": 500, "first_token_ms": 1500, "total_ms": 3300}
  }]
}
```

Run statuses are `ok`, `error` or `timeout`. Missing outputs stay in the denominator. Duplicated IDs, unknown fields, invalid verdicts and unknown case IDs are rejected instead of silently ignored.

## Review and run

From `backend`, using the backend Python environment:

```text
python -m evaluation review-template --dataset dataset.json --run candidate.json --reviewer reviewer-1 --review-kind human --output candidate-review.json
```

The template binds the review to SHA256 hashes of the full case and exact answer/status/source IDs. Timing may be attached later without invalidating a content review. Review every expected fact as `covered`, `missing`, `contradicted` or `uncertain`; every exclusion as `respected`, `violated` or `uncertain`. Include additional material claims in `extra_claims` with `supported`, `unsupported`, `contradicted` or `uncertain` and a reason. Set `all_claims_reviewed` only after reading the whole answer. A judge that fails should be recorded with `status: "error"`; do not replace failure with an empty successful review.

```text
python -m evaluation evaluate --dataset dataset.json --run candidate.json --reviews candidate-review.json --trusted-reviewer reviewer-1 --output candidate-report.json
python -m evaluation compare --dataset dataset.json --baseline baseline.json --baseline-reviews baseline-review.json --run candidate.json --reviews candidate-review.json --trusted-reviewer reviewer-1 --output comparison.json
```

All output paths must be new: the CLI refuses to overwrite saved evidence. Exit codes are 0 for passing evaluated cases (or successful template creation), 1 for failed/inconclusive cases or an incomplete/regressed comparison, and 2 for invalid inputs or file errors. The CLI never launches a judge or supplies credentials. JSON reports include exact answers, per-case reasons, dataset/split summaries, paired score changes and latency deltas. `condition_differences` lists differing run metadata, such as models or concurrency; do not attribute those comparisons solely to the code change.

## What the scores mean

- `fact_recall`: covered mandatory facts divided by all mandatory facts, from the supplied complete review.
- `reference_fact_f1`: the Ragas F-beta formula at beta=1 applied to annotated counts. Covered required facts are TP. Missing or contradicted required facts are FN. Contradicted required facts and unsupported/contradicted extra claims are FP. Supported extra claims do not inflate mandatory-fact recall. This is an adaptation, **not** the complete Ragas `AnswerCorrectness` metric; no embeddings similarity or LLM classifier is used.
- `contradictions` and `exclusion_violations`: separately visible counts. An answer cannot pass merely because its F1 is high while it violates a restriction.
- Retrieved/cited reference source coverage: required facts whose allowed reference source IDs appear in the saved retrieval/citation IDs. Use `null` or omit source ID arrays when the capture is unavailable or unverified; an explicit empty array means observation confirmed no sources. Unknown observations and any unmapped required fact make overall source coverage unknown. This checks source identity coverage, **not** semantic citation support or whether the exact retrieved passage contained the fact. `require_citations` makes complete reference source ID coverage an additional acceptance requirement; it does not claim citation correctness.
- Latency: mean, median and nearest-rank p95 with sample counts for each independently measured stage. A slower answer can still pass quality checks; latency has no weight in factual quality.

An overall pass requires a nonempty successful answer, a nonempty reference and required facts, a complete trusted answer-bound review, every required fact covered, no unsupported/contradicted claims, no violated exclusions, and all enabled fixture/source-coverage requirements met. Uncertain/missing/failed/untrusted reviews are inconclusive. Empty/failed answers fail even if a reviewer labels them perfect. Comparison outcomes reflect pass/fail transitions; inspect paired score deltas when both versions fail. A faster candidate with missing facts is not an improvement in answer quality.

Optional case `fixtures.contains` and `fixtures.excludes` are case-sensitive literal regression assertions. Passing them never makes a semantic pass: the words “immerse in water” occur in both correct and incorrectly negated advice. Reviews of kind `fixture` are never accepted as semantic scoring, even if that reviewer is trusted.

A pass means the supplied reference checks passed. It cannot establish universal correctness, prove an automatic judge is reliable, detect every unannotated omission, or compare unlike historical test conditions. Keep original evidence and review reasons, and periodically double-review held-out examples.

## Validation and attribution

```text
python -m unittest test_offline_evaluation -v
```

The tests cover complete/incomplete answers, negation, conflicting directions, exclusions, unsupported claims, missing references, malformed/failed judges, stale reviews, separate source coverage, missing timings, paired held-out comparisons, and fail-closed CLI behavior. The adapted Ragas scoring function is attributed in `backend/third_party/evaluation`; Ragas at the pinned revision uses Apache-2.0, not MIT.
