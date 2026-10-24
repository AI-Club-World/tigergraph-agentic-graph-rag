"""Offline, component-level evaluation of the reasoning layer on the harness.

What it measures: given the right subject and predicate (taken from the
harness metadata: an *oracle parse*), does temporal scoping plus conflict
resolution pick the true value, and is its confidence calibrated? No LLM,
no TigerGraph, no retrieval.

What it does not measure: pipeline accuracy. The intent parse, entity
linking, graph retrieval and answer generation are all bypassed, and RAG
is not run, so these numbers are not comparable to RAG and are not the
Round-2 result. They bound what the claim tools can contribute and are the
place where weights are fitted (dev) and checked (test) without spending
tokens.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from ogr.datasets.base import ClaimRecord, read_jsonl
from ogr.datasets.block_records import BlockRecordAdapter
from ogr.datasets.olympic import OlympicAdapter
from ogr.eval.calibration import brier, expected_calibration_error, fit_platt
from ogr.eval.scorer import exact_match
from ogr.pipelines.temporal import detect_temporal_scope
from ogr.reasoning.reliability import estimate_reliability, prior_for
from ogr.reasoning.resolve import Resolution, Weights, resolve

__all__ = ["PREDICATE_OF_INTENT", "ClaimIndex", "build_index", "evaluate", "fit_weights", "run_offline"]

PREDICATE_OF_INTENT = {
    "gold_latest": "gold", "gold_original": "gold", "gold_as_of": "gold",
    "attendance": "attendance", "competitors": "competitors",
}


@dataclass
class ClaimIndex:
    claims: dict[tuple[str, str], list[ClaimRecord]]
    reliability: dict[str, float]

    def about(self, subject: str, predicate: str) -> list[ClaimRecord]:
        return self.claims.get((subject, predicate), [])


def build_index(
    round1_corpus: str | Path, harness_corpus: str | Path, dataset_id: str = "r2-injected"
) -> ClaimIndex:
    """Claims from both datasets, and source reliability estimated over all
    of them (priors where a record gives one)."""
    claims: list[ClaimRecord] = []
    priors: dict[str, float | None] = {}
    adapters = ((OlympicAdapter("corpus"), round1_corpus), (BlockRecordAdapter(dataset_id), harness_corpus))
    for adapter, path in adapters:
        for doc in adapter.documents(Path(path)):
            prior = prior_for(doc)
            if prior is not None:
                priors[doc.source_id] = prior
            claims.extend(adapter.claims(doc))
    index: dict[tuple[str, str], list[ClaimRecord]] = {}
    for c in claims:
        index.setdefault((c.subject_id, c.predicate), []).append(c)
    return ClaimIndex(index, estimate_reliability(claims, priors))


def answer(index: ClaimIndex, question: dict[str, Any], weights: Weights) -> Resolution:
    meta = question["harness"]
    return resolve(
        index.about(meta["event_id"], PREDICATE_OF_INTENT[meta["intent"]]),
        detect_temporal_scope(question["question"]),
        index.reliability,
        weights,
    )


def _outcomes(
    index: ClaimIndex, questions: Sequence[dict], weights: Weights
) -> list[tuple[str, float, float, float, bool]]:
    """(qtype, correct, confidence, raw confidence, answerable) per question."""
    rows = []
    for q in questions:
        r = answer(index, q, weights)
        value = r.chosen.value if r.chosen else ""
        answerable = q["harness"].get("answerable", True)
        rows.append((q["qtype"], exact_match(value, q["answer"]), r.confidence, r.raw_confidence, answerable))
    return rows


def evaluate(index: ClaimIndex, questions: Iterable[dict], weights: Weights | None = None) -> dict[str, Any]:
    """Accuracy, ECE, Brier and mean confidence, per subset and overall."""
    weights = weights or Weights()
    rows = _outcomes(index, list(questions), weights)

    def summary(selected: list[tuple[str, float, float, float, bool]]) -> dict[str, Any]:
        correct = [r[1] for r in selected]
        conf = [r[2] for r in selected]
        answerable = [r[1] for r in selected if r[4]]
        return {
            "n": len(selected),
            "accuracy": sum(correct) / len(selected) if selected else None,
            "n_answerable": len(answerable),
            "answerable_accuracy": sum(answerable) / len(answerable) if answerable else None,
            "mean_confidence": sum(conf) / len(conf) if conf else None,
            "ece": expected_calibration_error(conf, correct),
            "brier": brier(conf, correct),
        }

    by_subset = {s: summary([r for r in rows if r[0] == s]) for s in sorted({r[0] for r in rows})}
    return {"overall": summary(rows), "by_subset": by_subset}


GRID = {
    "reliability": (0.5, 1.0, 2.0),
    "corroboration": (0.0, 0.5, 1.0),
    "recency": (0.0, 0.5, 1.0),
    "hedging": (0.0, 0.5, 1.0),
    "temperature": (0.25, 0.5, 1.0),
    "hedge_factor": (0.4, 0.6, 0.8),
}


def fit_weights(
    index: ClaimIndex, dev: Sequence[dict], grid: dict[str, Sequence[float]] | None = None
) -> Weights:
    """Grid search on the dev split: highest accuracy, then lowest Brier of
    the raw confidence; then Platt scaling fitted on dev. Never sees test."""
    grid = grid or GRID
    keys = sorted(grid)
    best: tuple[float, float, Weights] | None = None
    for values in itertools.product(*(grid[k] for k in keys)):
        weights = replace(Weights(), **dict(zip(keys, values, strict=True)))
        rows = _outcomes(index, dev, weights)
        accuracy = sum(r[1] for r in rows) / len(rows) if rows else 0.0
        loss = brier([r[3] for r in rows], [r[1] for r in rows]) or 0.0
        if best is None or (accuracy, -loss) > (best[0], -best[1]):
            best = (accuracy, loss, weights)
    weights = best[2] if best else Weights()
    rows = _outcomes(index, dev, weights)
    a, b = fit_platt([r[3] for r in rows], [r[1] for r in rows])
    return replace(weights, platt_a=a, platt_b=b)


def load_questions(path: str | Path) -> list[dict[str, Any]]:
    return list(read_jsonl(Path(path)))


def _table(results: dict[str, Any]) -> list[str]:
    def cell(v: float | None) -> str:
        return "–" if v is None else f"{v:.3f}"

    lines = [
        "| Subset | n | Accuracy | Answerable (n) | Accuracy on answerable | Mean confidence | ECE | Brier |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, row in [*results["by_subset"].items(), ("all", results["overall"])]:
        lines.append(
            f"| {name} | {row['n']} | {cell(row['accuracy'])} | {row['n_answerable']} "
            f"| {cell(row['answerable_accuracy'])} | {cell(row['mean_confidence'])} "
            f"| {cell(row['ece'])} | {cell(row['brier'])} |"
        )
    return lines


def run_offline(round1_corpus: str | Path, paths: dict[str, Path], out: Any) -> tuple[str, Weights]:
    """Fit on dev, evaluate on test (defaults and fitted): the Markdown
    report and the fitted weights."""
    index = build_index(round1_corpus, paths["corpus"], out.manifest["config"]["dataset_id"])
    dev = [q for q in out.questions if q["split"] == "dev"]
    test = [q for q in out.questions if q["split"] == "test"]
    fitted = fit_weights(index, dev)
    lines = [
        "# Round-2 harness — offline reasoning-layer evaluation",
        "",
        "**Scope.** Oracle subject and predicate (from the harness metadata), temporal scope from the "
        "question text, deterministic conflict resolution and confidence. No intent parse, no retrieval, "
        "no LLM, no RAG baseline: this is a component check, **not** a pipeline result and not comparable "
        "to RAG.",
        "",
        f"Generator v{out.manifest['generator_version']}, config: `{json.dumps(out.manifest['config'])}`. "
        f"Dev {len(dev)} / test {len(test)} questions (split by event).",
        "",
        "## Test split, default weights",
        "",
        *_table(evaluate(index, test, Weights())),
        "",
        "## Test split, weights and Platt scaling fitted on dev only",
        "",
        *_table(evaluate(index, test, fitted)),
        "",
        f"Fitted: `{fitted}`",
        "",
    ]
    return "\n".join(lines), fitted
