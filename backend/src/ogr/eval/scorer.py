"""Deterministic scorer — EM, token F1, and retrieval precision/recall/F1.

Source spec: TECHNICAL-SPEC §9 · Plan: implementation-plan-UI.md Group 1 (EVAL-02)
Requirement: FR-14, NFR-6 · Gate: G3

**No LLM sits in this path.** NFR-6 requires the same inputs to produce the
same numbers on every run, and AD-4 argues that a reference-free LLM judge is
the tool for the *absence* of ground truth, not a weaker substitute when
verified gold answers already exist. Nothing here calls a model or the network.

Scoring targets `PipelineRecord.answer` — the short span from the CORE-02
answer contract — never `explanation`. Without that split, a correct answer
phrased as a sentence scores EM = 0 for all three pipelines and the whole
comparison reads flat (PLAT-06).

Retrieval metrics compare the returned document set against `gold_doc_ids`.
`@k` is deliberately absent: it is undefined for P2 and P3, which retrieve by
traversal rather than top-k (§9, corrected in v0.3).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Any

from ogr.common.contracts import PipelineScores
from ogr.common.names import normalize_answer, normalized_name_set, tokenize

__all__ = [
    "exact_match",
    "token_f1",
    "retrieval_metrics",
    "score_answer",
    "score_record",
    "aggregate",
    "aggregate_by_qtype",
]


def exact_match(prediction: str, gold_variants: Sequence[str]) -> float:
    """1.0 if the prediction matches any gold variant, else 0.0.

    Comparison is over the normalized *name set*, so a concatenated
    multi-person answer scores as set overlap (§9) while an ordinary answer
    reduces to a one-element set and behaves like plain exact match.
    """
    if not gold_variants:
        return 0.0
    predicted = normalized_name_set(prediction)
    if not predicted:
        return 0.0
    for gold in gold_variants:
        gold_set = normalized_name_set(gold)
        if predicted == gold_set:
            return 1.0
        if _is_count(gold_set) and _numbers(prediction) == gold_set:
            # A count answered with its unit ("5 events", "five") — the one
            # number stated is the answer; two different numbers are not.
            return 1.0
    return 0.0


def _is_count(names: frozenset[str]) -> bool:
    return len(names) == 1 and next(iter(names)).isdigit()


def _numbers(text: str) -> frozenset[str]:
    return frozenset(token for token in normalize_answer(text).split() if token.isdigit())


def _f1(predicted_tokens: list[str], gold_tokens: list[str]) -> float:
    if not predicted_tokens or not gold_tokens:
        # Two empty strings agree; one empty and one not do not.
        return float(predicted_tokens == gold_tokens)
    overlap = Counter(predicted_tokens) & Counter(gold_tokens)
    shared = sum(overlap.values())
    if shared == 0:
        return 0.0
    precision = shared / len(predicted_tokens)
    recall = shared / len(gold_tokens)
    return 2 * precision * recall / (precision + recall)


def token_f1(prediction: str, gold_variants: Sequence[str]) -> float:
    """Token-overlap F1 under the same normalization, max over gold variants."""
    if not gold_variants:
        return 0.0
    predicted_tokens = tokenize(prediction)
    return max(_f1(predicted_tokens, tokenize(gold)) for gold in gold_variants)


def retrieval_metrics(
    retrieved_doc_ids: Iterable[str],
    gold_doc_ids: Iterable[str],
) -> tuple[float, float, float]:
    """Precision, recall and F1 of the returned document set against gold.

    Both sides are deduplicated: `gold_doc_ids` is a set of documents, and a
    pipeline citing the same parent document twice has not retrieved it twice.
    """
    retrieved = {doc_id for doc_id in retrieved_doc_ids if doc_id}
    gold = {doc_id for doc_id in gold_doc_ids if doc_id}

    if not gold:
        return 0.0, 0.0, 0.0
    if not retrieved:
        return 0.0, 0.0, 0.0

    hits = len(retrieved & gold)
    precision = hits / len(retrieved)
    recall = hits / len(gold)
    f1 = 0.0 if (precision + recall) == 0 else 2 * precision * recall / (precision + recall)
    return precision, recall, f1


def score_answer(
    prediction: str,
    gold_variants: Sequence[str],
    retrieved_doc_ids: Iterable[str] = (),
    gold_doc_ids: Iterable[str] = (),
) -> PipelineScores:
    """Score one answer plus its retrieved document set."""
    precision, recall, _ = retrieval_metrics(retrieved_doc_ids, gold_doc_ids)
    return PipelineScores(
        em=exact_match(prediction, gold_variants),
        f1=token_f1(prediction, gold_variants),
        precision=precision,
        recall=recall,
        # Completeness IS recall — reported under both names because the
        # guidebook asks for the column (DP-2 Option A).
        completeness=recall,
    )


def score_record(
    record: Any,  # PipelineRecord
    gold_variants: Sequence[str],
    gold_doc_ids: Iterable[str] = (),
) -> PipelineScores:
    """Score a PipelineRecord: EM/F1 on `answer`, retrieval on citation source_ids."""
    retrieved = [citation.source_id for citation in getattr(record, "citations", [])]
    return score_answer(
        prediction=getattr(record, "answer", "") or "",
        gold_variants=gold_variants,
        retrieved_doc_ids=retrieved,
        gold_doc_ids=gold_doc_ids,
    )


def aggregate(scores: Sequence[PipelineScores]) -> PipelineScores:
    """Mean of each metric. An empty input scores zero, not an error."""
    if not scores:
        return PipelineScores()
    count = len(scores)
    return PipelineScores(
        em=sum(s.em for s in scores) / count,
        f1=sum(s.f1 for s in scores) / count,
        precision=sum(s.precision for s in scores) / count,
        recall=sum(s.recall for s in scores) / count,
        completeness=sum(s.completeness for s in scores) / count,
    )


def aggregate_by_qtype(
    scored: Iterable[tuple[str | None, PipelineScores]],
) -> dict[str, PipelineScores]:
    """Group (qtype, scores) pairs into the per-qtype breakdown.

    §9 calls the per-qtype split "the headline artifact". `qtype` is an
    eval-set label used for *reporting only* — it is never read in the answer
    path, which would be training on the test set (NFR-7).
    """
    buckets: dict[str, list[PipelineScores]] = {}
    for qtype, scores in scored:
        buckets.setdefault(qtype or "unknown", []).append(scores)
    return {qtype: aggregate(group) for qtype, group in buckets.items()}
