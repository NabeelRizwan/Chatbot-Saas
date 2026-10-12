"""CLI for evaluating existing files. No network, credentials or running app needed."""

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .evaluate import compare_runs, evaluate_run, review_template
from .schema import Dataset, ReviewSet, Run


def _load(model, path):
    return model.model_validate_json(Path(path).read_text(encoding="utf-8-sig"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["evaluate", "compare", "review-template"])
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--run", required=True, help="Candidate/single run JSON")
    parser.add_argument("--reviews")
    parser.add_argument("--baseline")
    parser.add_argument("--baseline-reviews")
    parser.add_argument("--trusted-reviewer", action="append", default=[])
    parser.add_argument("--reviewer", help="Reviewer identifier for a review template")
    parser.add_argument("--review-kind", choices=["human", "assisted_review", "external_judge", "fixture"], default="human")
    parser.add_argument("--output", required=True, help="New output path (existing files are never overwritten)")
    args = parser.parse_args(argv)
    try:
        dataset, run = _load(Dataset, args.dataset), _load(Run, args.run)
        reviews = _load(ReviewSet, args.reviews) if args.reviews else None
        trusted = set(args.trusted_reviewer)
        if args.command == "review-template":
            if not args.reviewer:
                raise ValueError("review-template requires --reviewer")
            report = review_template(dataset, run, args.reviewer, args.review_kind).model_dump(mode="json")
        elif args.command == "compare":
            if not args.baseline:
                raise ValueError("compare requires --baseline")
            report = compare_runs(dataset, _load(Run, args.baseline), run,
                                  _load(ReviewSet, args.baseline_reviews) if args.baseline_reviews else None,
                                  reviews, trusted_reviewers=trusted)
        else:
            report = evaluate_run(dataset, run, reviews, trusted_reviewers=trusted)
        with Path(args.output).open("x", encoding="utf-8") as output:
            json.dump(report, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.write("\n")
        if args.command == "review-template":
            return 0
        summary = report["candidate"]["summary"] if args.command == "compare" else report["summary"]
        comparison_incomplete = args.command == "compare" and (
            report["comparison"]["regression"] > 0 or report["comparison"]["inconclusive"] > 0)
        return 1 if summary["fail"] or summary["inconclusive"] or comparison_incomplete else 0
    except (ValueError, ValidationError, OSError) as exc:
        print(f"Evaluation input/output error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
