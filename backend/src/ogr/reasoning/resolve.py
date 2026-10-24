"""Conflict resolution and answer confidence (ROUND2-DESIGN.md §4).

Given the claims for one (subject, predicate), a temporal scope and source
reliabilities, pick one value, deterministically, with:
  - the score terms of every candidate value (recency, reliability,
    corroboration, extraction confidence, hedging), so the choice can be
    inspected;
  - the losing values and the superseded claims kept as conflicting
    evidence;
  - a confidence: the chosen value's share of the score mass, times how
    well it is supported in absolute terms (one hedged blog post is not
    certain just because nothing contradicts it), then calibrated.

Answer policy (decided): always commit to one best value; never abstain.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from ogr.datasets.base import ClaimRecord
from ogr.eval.calibration import apply_platt
from ogr.pipelines.temporal import TemporalScope
from ogr.reasoning.relations import build_relations, value_key
from ogr.reasoning.reliability import DEFAULT_RELIABILITY

__all__ = ["Candidate", "Resolution", "Weights", "in_scope", "resolve"]


@dataclass(frozen=True)
class Weights:
    """Defaults before fitting. Fitted on the harness dev split only, then
    frozen before the test split runs (harness/fit.py)."""
    reliability: float = 1.0
    corroboration: float = 0.5
    recency: float = 0.5
    extraction: float = 0.3
    hedging: float = 0.5
    tau_days: float = 730.0
    temperature: float = 0.5
    hedge_factor: float = 0.6
    # Platt scaling of the raw confidence: sigmoid(a * logit(p) + b).
    platt_a: float = 1.0
    platt_b: float = 0.0


@dataclass
class Candidate:
    value: str
    claims: list[ClaimRecord]
    sources: list[str]
    terms: dict[str, float]
    score: float = 0.0
    probability: float = 0.0
    support: float = 0.0

    def to_dict(self) -> dict:
        return {
            "value": self.value, "score": round(self.score, 4), "probability": round(self.probability, 4),
            "support": round(self.support, 4), "terms": {k: round(v, 4) for k, v in self.terms.items()},
            "sources": self.sources,
            "observed_at": sorted({c.observed_at for c in self.claims if c.observed_at}),
            "doc_ids": sorted({c.doc_id for c in self.claims}),
        }


@dataclass
class Resolution:
    subject_id: str
    predicate: str
    scope: TemporalScope
    chosen: Candidate | None
    alternatives: list[Candidate] = field(default_factory=list)
    superseded: list[ClaimRecord] = field(default_factory=list)
    out_of_scope: list[ClaimRecord] = field(default_factory=list)
    raw_confidence: float = 0.0
    confidence: float = 0.0
    notes: str = ""

    @property
    def conflicted(self) -> bool:
        return bool(self.alternatives or self.superseded)

    def to_dict(self) -> dict:
        return {
            "subject": self.subject_id, "predicate": self.predicate, "scope": self.scope.to_dict(),
            "chosen": self.chosen.to_dict() if self.chosen else None,
            "alternatives": [a.to_dict() for a in self.alternatives],
            "superseded": [
                {"value": c.value_text, "source": c.source_id,
                 "observed_at": c.observed_at, "doc_id": c.doc_id}
                for c in self.superseded
            ],
            "confidence": round(self.confidence, 4), "raw_confidence": round(self.raw_confidence, 4),
            "notes": self.notes,
        }


def _valid_at(c: ClaimRecord, t: str) -> bool:
    return (c.valid_from or "") <= t <= (c.valid_to or "9999-12-31")


def in_scope(c: ClaimRecord, scope: TemporalScope) -> bool:
    """Whether a claim was known, and valid, within the scope. An unknown
    observed time counts as known throughout (an undated page)."""
    if scope.mode == "as_of" and scope.t1:
        return (c.observed_at is None or c.observed_at <= scope.t1) and _valid_at(c, scope.t1)
    if scope.mode == "before" and scope.t1:
        return (c.observed_at is None or c.observed_at < scope.t1) and (c.valid_from or "") < scope.t1
    if scope.mode == "after" and scope.t1:
        return (c.valid_to or "9999-12-31") >= scope.t1
    if scope.mode == "between" and scope.t1 and scope.t2:
        return (c.observed_at is None or c.observed_at <= scope.t2) and (
            (c.valid_from or "") <= scope.t2 and (c.valid_to or "9999-12-31") >= scope.t1
        )
    return True


def resolve(
    claims: Iterable[ClaimRecord],
    scope: TemporalScope | None = None,
    reliability: Mapping[str, float] | None = None,
    weights: Weights | None = None,
) -> Resolution:
    w = weights or Weights()
    scope = scope or TemporalScope()
    reliability = reliability or {}
    claims = sorted(claims, key=lambda c: c.claim_id)
    subject = claims[0].subject_id if claims else ""
    predicate = claims[0].predicate if claims else ""

    scoped = [c for c in claims if in_scope(c, scope)]
    out = [c for c in claims if c not in scoped]
    relations = build_relations(scoped)
    newer_of = {r.dst for r in relations if r.kind == "SUPERSEDES"}
    revisers = {r.src for r in relations if r.kind == "SUPERSEDES"}
    if scope.mode == "original":
        # The first statements: drop the claims that revise an earlier one.
        superseded = [c for c in scoped if c.claim_id in revisers]
    else:
        superseded = [c for c in scoped if c.claim_id in newer_of]
    live = [c for c in scoped if c not in superseded] or scoped

    by_value: dict[object, list[ClaimRecord]] = {}
    for c in live:
        by_value.setdefault(value_key(c), []).append(c)
    if not by_value:
        return Resolution(subject, predicate, scope, None, out_of_scope=out, notes="no claim in scope")

    dated = [c.observed_at for c in live if c.observed_at]
    newest = max(dated) if dated else None

    def age_days(c: ClaimRecord) -> float:
        if not (newest and c.observed_at):
            return w.tau_days  # undated: as if one tau old
        y1, m1, d1 = (int(x) for x in newest.split("-"))
        y2, m2, d2 = (int(x) for x in c.observed_at.split("-"))
        return max(0.0, (y1 - y2) * 365.25 + (m1 - m2) * 30.44 + (d1 - d2))

    candidates: list[Candidate] = []
    for group in by_value.values():
        sources = sorted({c.source_id for c in group if c.source_id})
        rel = [reliability.get(s, DEFAULT_RELIABILITY) for s in sources] or [DEFAULT_RELIABILITY]
        terms = {
            "reliability": sum(rel) / len(rel),
            "corroboration": math.log1p(len(sources) or 1),
            "recency": max(math.exp(-age_days(c) / w.tau_days) for c in group),
            "extraction": sum(c.extraction_conf for c in group) / len(group),
            "hedged_share": sum(1 for c in group if c.hedged) / len(group),
        }
        score = (
            w.reliability * terms["reliability"] + w.corroboration * terms["corroboration"]
            + w.recency * terms["recency"] + w.extraction * terms["extraction"]
            - w.hedging * terms["hedged_share"]
        )
        # Absolute support: noisy-or over independent sources of each one's
        # best claim confidence (extraction x hedging x reliability).
        miss = 1.0
        for s in sources or [""]:
            own = [c for c in group if c.source_id == s] or group
            best = max(c.extraction_conf * (w.hedge_factor if c.hedged else 1.0) for c in own)
            miss *= 1.0 - best * reliability.get(s, DEFAULT_RELIABILITY)
        representative = max(group, key=lambda c: (c.observed_at or "", c.claim_id))
        candidates.append(
            Candidate(representative.value_text, group, sources, terms, score, support=1 - miss)
        )

    top = max(c.score for c in candidates)
    exp = [math.exp((c.score - top) / max(w.temperature, 1e-6)) for c in candidates]
    for c, e in zip(candidates, exp, strict=True):
        c.probability = e / sum(exp)
    candidates.sort(key=lambda c: (
        -c.score,
        -max((int(x.observed_at.replace("-", "")) for x in c.claims if x.observed_at), default=0),
        -c.terms["reliability"],
        c.value,
    ))
    chosen, alternatives = candidates[0], candidates[1:]
    raw = chosen.probability * chosen.support
    confidence = apply_platt(raw, w.platt_a, w.platt_b)
    notes = (
        f"{len(candidates)} value(s) in scope {scope.mode}; chosen '{chosen.value}' "
        f"(score {chosen.score:.2f}, p {chosen.probability:.2f}, support {chosen.support:.2f})"
        + (f"; {len(superseded)} superseded" if superseded else "")
        + (f"; {len(out)} out of scope" if out else "")
    )
    return Resolution(
        subject, predicate, scope, chosen, alternatives, superseded, out,
        raw_confidence=raw, confidence=confidence, notes=notes,
    )
