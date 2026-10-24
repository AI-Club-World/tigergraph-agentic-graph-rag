"""Source reliability (ROUND2-DESIGN.md §4.3).

The adapter's prior when the dataset defines one; otherwise estimated from
agreement across the dataset's own claims (a TruthFinder-style fixed
point): a source is as reliable as the average support its values get, and
a value is as supported as the sources asserting it are reliable.
Deterministic. Never derived from questions or gold answers.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from ogr.datasets.base import ClaimRecord, SourceRecord
from ogr.reasoning.relations import group_claims, value_key

__all__ = ["CLASS_PRIORS", "DEFAULT_RELIABILITY", "estimate_reliability", "prior_for"]

DEFAULT_RELIABILITY = 0.6
# [ASSUMPTION] A prior per source class, for datasets that name the kind of
# source but give no reliability. General, not fitted; replace with the real
# dataset's own when it has one.
CLASS_PRIORS = {
    "official": 0.9, "encyclopedia": 0.8, "news": 0.75, "blog": 0.4, "forum": 0.3, "social": 0.3,
}
ITERATIONS = 10
# With a prior, the estimate moves it by at most this share.
PRIOR_WEIGHT = 0.5


def prior_for(doc: SourceRecord) -> float | None:
    """The dataset's own prior, else the class prior, else None (estimated)."""
    if doc.reliability_prior is not None:
        return doc.reliability_prior
    return CLASS_PRIORS.get((doc.source_class or "").lower())


def estimate_reliability(
    claims: Iterable[ClaimRecord],
    priors: Mapping[str, float | None] | None = None,
    iterations: int = ITERATIONS,
) -> dict[str, float]:
    """Reliability per source_id in (0, 1)."""
    priors = {k: v for k, v in (priors or {}).items() if v is not None}
    groups = [g for g in group_claims(claims).values()]
    sources = sorted({c.source_id for g in groups for c in g if c.source_id})
    rel = {s: float(priors.get(s, DEFAULT_RELIABILITY)) for s in sources}
    # Only groups where sources can disagree say anything about reliability.
    contested = [g for g in groups if len({value_key(c) for c in g}) > 1 or len({c.source_id for c in g}) > 1]
    for _ in range(iterations):
        support: dict[str, list[float]] = {s: [] for s in sources}
        for group in contested:
            by_value: dict[object, set[str]] = {}
            for c in group:
                if c.source_id:
                    by_value.setdefault(value_key(c), set()).add(c.source_id)
            strength = {}
            for key, srcs in by_value.items():
                miss = 1.0
                for s in sorted(srcs):
                    miss *= 1.0 - rel[s]
                strength[key] = 1.0 - miss
            total = sum(strength.values()) or 1.0
            for key, srcs in by_value.items():
                for s in srcs:
                    support[s].append(strength[key] / total)
        updated = {}
        for s in sources:
            est = sum(support[s]) / len(support[s]) if support[s] else rel[s]
            prior = priors.get(s)
            value = PRIOR_WEIGHT * prior + (1 - PRIOR_WEIGHT) * est if prior is not None else est
            updated[s] = min(0.99, max(0.01, value))
        if all(abs(updated[s] - rel[s]) < 1e-6 for s in sources):
            rel = updated
            break
        rel = updated
    return {s: round(v, 4) for s, v in rel.items()}
