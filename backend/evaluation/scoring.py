"""Small, offline adaptation of Ragas reference-classification scoring.

Derived from AnswerCorrectness._compute_f1_score in explodinggradients/ragas,
commit 298b68274234c060deacab3cf5fb52aa3a20e885 (Apache-2.0).
See backend/third_party/evaluation for the license and modification notice.
"""

import math


def reference_fbeta(tp: int, fp: int, fn: int, beta: float = 1.0) -> float | None:
    """Score annotated counts; an empty reference is undefined, never perfect.

    TP = covered required facts; FN = missing/contradicted required facts;
    FP = contradicted required facts plus unsupported/contradicted extra claims.
    This deliberately is not the complete Ragas AnswerCorrectness metric.
    """
    if any(type(count) is not int or count < 0 for count in (tp, fp, fn)):
        raise ValueError("classification counts must be nonnegative integers")
    if isinstance(beta, bool) or not math.isfinite(beta) or beta <= 0:
        raise ValueError("beta must be finite and positive")
    if tp + fn == 0:
        return None
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn)
    if precision + recall == 0:
        return 0.0
    beta_squared = beta**2
    return ((1 + beta_squared) * (precision * recall)
            / (beta_squared * precision + recall))
