"""Offline reference-based evaluation; never imported by the answer hot path."""

from .evaluate import compare_runs, evaluate_run, review_template
from .schema import Dataset, Review, ReviewSet, Run, case_digest, output_digest

__all__ = [
    "Dataset", "Review", "ReviewSet", "Run", "case_digest", "output_digest",
    "compare_runs", "evaluate_run", "review_template",
]
