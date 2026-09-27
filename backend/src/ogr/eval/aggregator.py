"""Result Aggregator — merges three pipeline records into one query record.

Source spec: TECHNICAL-SPEC §6.1 · ARCHITECTURE-SPEC AD-1
Plan: implementation-plan-UI.md Group 2 (EVAL-03)
Requirement: FR-8, FR-9, NFR-5 · Gate: G2

NFR-5 / AD-1: one aggregator implementation, used by the interactive API and
the batch runner alike. Two implementations is how the number in the demo and
the number in the submission stop agreeing.

FR-8: the verdict carries the token multipliers (Agentic / RAG and Agentic /
GraphRAG) and the EM-based accuracy deltas.

FR-9: where no ground truth exists the accuracy deltas are the literal "n/a" —
displayed as N/A rather than omitted, so a missing number is never mistaken
for a zero.

The cost-honesty criterion depends on this block being computed the same way
everywhere: the benchmark is supposed to surface question types where the
agentic path is *not* worth its multiplier, and a verdict that only ever
flatters the agent has not been computed honestly.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from ogr.common.contracts import PipelineRecord, QueryLevelRecord, Verdict
from ogr.eval.scorer import exact_match

__all__ = ["build_verdict", "aggregate_query"]

_AGENTIC = "agentic_graphrag"
_RAG = "rag"
_GRAPHRAG = "graphrag"


def _multiplier(numerator: int, denominator: int) -> float | None:
    """Token ratio, rounded to 2dp; None when it is undefined (a zero
    denominator — the baseline spent nothing, e.g. it errored)."""
    if denominator <= 0:
        return None
    return round(numerator / denominator, 2)


def _summary(
    verdict: Verdict,
    agentic_correct: float | None,
    rag_correct: float | None,
) -> str:
    """One plain sentence a judge can read without the table."""
    ratio = verdict.token_multiplier_vs_rag
    if verdict.accuracy_delta_vs_rag == "n/a" or agentic_correct is None or rag_correct is None:
        cost = "RAG spent no tokens: no cost ratio."
        if ratio is not None:
            cost = f"Agentic cost {ratio}x RAG tokens."
        return f"No ground truth for this query, so the accuracy delta is N/A. {cost}"
    at = f" at {ratio}x its tokens" if ratio is not None else " (RAG spent no tokens: no cost ratio)"
    delta = verdict.accuracy_delta_vs_rag
    if delta > 0:
        return f"Agentic was correct where RAG was not,{at}."
    if delta < 0:
        return f"Agentic lost to RAG on this query{at}."
    return f"No accuracy gain over RAG{at}."


def build_verdict(
    records: Mapping[str, PipelineRecord],
    gold_variants: Sequence[str] | None = None,
) -> Verdict:
    """Compute the verdict block from the three records.

    Args:
        records: {pipeline_id: PipelineRecord}. Missing pipelines are treated
            as zero-token, which keeps a partial run renderable (NFR-2).
        gold_variants: gold answers. Empty or None means no ground truth, and
            both accuracy deltas become "n/a" (FR-9).
    """
    def tokens(pipeline: str) -> int:
        record = records.get(pipeline)
        return record.tokens.total if record else 0

    verdict = Verdict(
        token_multiplier_vs_rag=_multiplier(tokens(_AGENTIC), tokens(_RAG)),
        token_multiplier_vs_graphrag=_multiplier(tokens(_AGENTIC), tokens(_GRAPHRAG)),
    )

    agentic_em = rag_em = None
    if gold_variants:
        def em(pipeline: str) -> float:
            record = records.get(pipeline)
            return exact_match(record.answer, gold_variants) if record else 0.0

        agentic_em, rag_em = em(_AGENTIC), em(_RAG)
        verdict.accuracy_delta_vs_rag = round(agentic_em - rag_em, 2)
        verdict.accuracy_delta_vs_graphrag = round(agentic_em - em(_GRAPHRAG), 2)

    verdict.summary_line = _summary(verdict, agentic_em, rag_em)
    return verdict


def aggregate_query(
    query_id: str,
    query_text: str,
    records: Mapping[str, PipelineRecord],
    gold_variants: Sequence[str] | None = None,
    qtype: str | None = None,
    timestamp: str | None = None,
) -> QueryLevelRecord:
    """Merge the dispatcher's output into one QueryLevelRecord with its verdict.

    `qtype` is carried for reporting only — it is an eval-set label and is
    never read in the answer path (NFR-7).
    """
    return QueryLevelRecord(
        query_id=query_id,
        query_text=query_text,
        qtype=qtype,
        timestamp=timestamp or datetime.now(UTC).isoformat(timespec="seconds"),
        pipelines=dict(records),
        verdict=build_verdict(records, gold_variants),
    )
