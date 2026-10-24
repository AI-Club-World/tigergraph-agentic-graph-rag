"""Confidence calibration metrics and fitting (ROUND2-DESIGN.md §4.4).

Deterministic and dependency-free. A confidence is reported as calibrated
only when these are computed on held-out questions (the harness test split),
never on the split its parameters were fitted on.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

__all__ = ["apply_platt", "brier", "expected_calibration_error", "fit_platt", "reliability_table"]


def _check(confidences: Sequence[float], correct: Sequence[float]) -> None:
    if len(confidences) != len(correct):
        raise ValueError("confidences and correct differ in length")


def brier(confidences: Sequence[float], correct: Sequence[float]) -> float | None:
    """Mean squared error between confidence and outcome (0 is perfect)."""
    _check(confidences, correct)
    if not confidences:
        return None
    return sum((p - y) ** 2 for p, y in zip(confidences, correct, strict=True)) / len(confidences)


def reliability_table(confidences: Sequence[float], correct: Sequence[float], bins: int = 10) -> list[dict]:
    """Per equal-width bin: count, mean confidence, accuracy."""
    _check(confidences, correct)
    table = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, p in enumerate(confidences) if (lo <= p < hi) or (b == bins - 1 and p == 1.0)]
        if idx:
            table.append({
                "bin": f"{lo:.1f}-{hi:.1f}", "n": len(idx),
                "confidence": sum(confidences[i] for i in idx) / len(idx),
                "accuracy": sum(correct[i] for i in idx) / len(idx),
            })
    return table


def expected_calibration_error(
    confidences: Sequence[float], correct: Sequence[float], bins: int = 10
) -> float | None:
    """Count-weighted mean |accuracy - confidence| over equal-width bins."""
    if not confidences:
        return None
    n = len(confidences)
    return sum(row["n"] / n * abs(row["accuracy"] - row["confidence"])
               for row in reliability_table(confidences, correct, bins))


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def _logit(p: float) -> float:
    p = min(1 - 1e-6, max(1e-6, p))
    return math.log(p / (1 - p))


def apply_platt(p: float, a: float, b: float) -> float:
    """A raw confidence mapped through fitted Platt parameters."""
    return _sigmoid(a * _logit(p) + b)


# Ridge pull towards the identity map (a=1, b=0): with few distinct
# confidences the unregularised optimum runs off to infinity.
RIDGE = 1e-2


def _loss(a: float, b: float, xs: Sequence[float], ys: Sequence[float]) -> float:
    total = 0.0
    for x, y in zip(xs, ys, strict=True):
        q = min(1 - 1e-12, max(1e-12, _sigmoid(a * x + b)))
        total -= y * math.log(q) + (1 - y) * math.log(1 - q)
    return total + RIDGE * ((a - 1) ** 2 + b ** 2)


def fit_platt(
    confidences: Sequence[float], correct: Sequence[float], iterations: int = 100
) -> tuple[float, float]:
    """(a, b) minimising log loss of sigmoid(a * logit(p) + b), by damped
    Newton steps with a small ridge towards the identity. Returns the
    identity (1, 0) when there is nothing to fit."""
    _check(confidences, correct)
    if not confidences or len(set(correct)) < 2:
        return 1.0, 0.0
    xs = [_logit(p) for p in confidences]
    ys = [float(y) for y in correct]
    a, b = 1.0, 0.0
    loss = _loss(a, b, xs, ys)
    for _ in range(iterations):
        ga, gb = 2 * RIDGE * (a - 1), 2 * RIDGE * b
        haa = hbb = 2 * RIDGE
        hab = 0.0
        for x, y in zip(xs, ys, strict=True):
            q = _sigmoid(a * x + b)
            ga += (q - y) * x
            gb += q - y
            s = q * (1 - q)
            haa += s * x * x
            hab += s * x
            hbb += s
        det = haa * hbb - hab * hab
        if det <= 1e-12:
            break
        da = (hbb * ga - hab * gb) / det
        db = (haa * gb - hab * ga) / det
        step = 1.0
        while step > 1e-4:
            na, nb = a - step * da, b - step * db
            new_loss = _loss(na, nb, xs, ys)
            if new_loss <= loss:
                break
            step /= 2
        else:
            break
        converged = abs(loss - new_loss) < 1e-10
        a, b, loss = na, nb, new_loss
        if converged:
            break
    return a, b
