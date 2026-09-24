"""P2 — GraphRAG Pipeline.

Source spec: TECHNICAL-SPEC §8.2 · ARCHITECTURE-SPEC §2 · APPLICATION-SPEC FR-2/4/10
Plan: implementation-plan-GRAPH.md Group 4 (GRAPH-08) · PLAT-07

P2 is the middle arm of the ablation:
    P1 removes the graph · P2 removes the loop · P3 has both.

That only holds if P2 differs from P3 by exactly one variable, so P2 reuses
**P3's intent parser** and then runs **exactly one query** — no evidence check,
no fallback, no loop. Any extra machinery here reintroduces a second variable
and the measured P3-minus-P2 gap stops being attributable to the agentic loop.

PLAT-07: the originally specified "fixed question-type -> Q1/Q4/Q5 table" is
not implementable. `qtype` is an eval-set label and NFR-7 forbids
question-template regex in the answer path, so that routing would have to
either read the test label or pattern-match the question. Both are prohibited.

Generation uses the CORE-02 shared answer contract through the same
`invoke_llm_with_answer_contract` that P1 and P3 call, so the prompt is
byte-identical apart from retrieved context — a prompt difference between
pipelines would be a confound in the measured accuracy gap.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ogr.common.config import RunConfig, get_default_config
from ogr.common.contracts import Citation, PipelineRecord, TokenUsage, format_evidence_context
from ogr.common.llm import (
    get_chat_model,
    invoke_llm_with_answer_contract,
    resolve_tool_calling_support,
)
from ogr.graph.client import TigerGraphClient
from ogr.pipelines.p3_agentic.agents.agent_result import AgentResult
from ogr.pipelines.p3_agentic.agents.aggregation import run_aggregation
from ogr.pipelines.p3_agentic.agents.entity_linking import EntityLinker, ResolvedAnchors, narrow_to_games
from ogr.pipelines.p3_agentic.agents.graph_traversal import run_graph_traversal
from ogr.pipelines.p3_agentic.intent import IntentParser, IntentSchema
from ogr.pipelines.p3_agentic.router import route

logger = logging.getLogger(__name__)

__all__ = ["run_p2_graphrag", "select_single_query", "format_evidence_into_context"]


def select_single_query(intent: IntentSchema) -> str:
    """Map the parsed operation to the one query P2 will run.

    Uses the same necessity-routing decision P3 makes, then collapses it to a
    single call: where P3 would loop, P2 runs the first step and stops. That
    difference *is* the experiment.
    """
    decision = route(intent)
    if decision == "lookup_direct":
        return "lookup"
    if decision == "scoped_aggregate":
        return "aggregate"
    return "traverse"


def _run_lookup(client: TigerGraphClient, intent: IntentSchema, anchors: ResolvedAnchors) -> AgentResult:
    started = time.perf_counter()
    params = {
        "title": anchors.title or "",
        "event_id": anchors.event_id or "",
        "target_field": intent.target_field or "",
    }
    raw = narrow_to_games(client._run_query("q1_lookup", params) or [], anchors.games)
    return AgentResult(
        evidence=raw,
        chunks_returned=len(raw),
        citations_count=len(raw),
        latency_ms=(time.perf_counter() - started) * 1000.0,
        notes="Q1 lookup (single query, no loop)",
    )


def format_evidence_into_context(evidence: list[dict[str, Any]]) -> str:
    """Render graph evidence as the context block for the shared prompt."""
    return format_evidence_context(evidence)


def _citations_from(evidence: list[dict[str, Any]]) -> list[Citation]:
    """Entity/relationship citations carrying source_id and chunk_id (PLAN-004 DP-1)."""
    citations: list[Citation] = []
    for item in evidence:
        source_id = item.get("doc_id") or item.get("event_id") or ""
        if not source_id:
            continue
        chunk_id = item.get("chunk_id")
        citations.append(
            Citation(
                source_id=source_id,
                chunk_id=chunk_id,
                ref_type="chunk" if chunk_id else "entity",
            )
        )
    return citations


def run_p2_graphrag(
    query: str,
    client: TigerGraphClient | None = None,
    config: RunConfig | None = None,
    model: Any | None = None,
    entity_linker: EntityLinker | None = None,
) -> PipelineRecord:
    """Execute the P2 GraphRAG pipeline: parse intent, run ONE query, generate.

    Returns a PipelineRecord. `trace`, `strategy_changed` and `stop_reason` stay
    null: P2 has no loop, so it has nothing to trace and no stopping decision
    to report. Those fields belong to P3 alone.
    """
    started = time.perf_counter()
    cfg = config or get_default_config()
    tg_client = client or TigerGraphClient(cfg)
    chat_model = model or get_chat_model(cfg)

    if entity_linker is None:
        entity_linker = EntityLinker(
            games_vocab=tg_client.get_vocabulary("Games") or None,
            sports_vocab=tg_client.get_vocabulary("Sport") or None,
            venues_vocab=tg_client.get_vocabulary("Venue") or None,
        )

    # Step 1 — the SAME intent parser P3 uses (PLAT-07).
    parser = IntentParser(
        chat_model,
        supports_tool_calling=resolve_tool_calling_support(
            chat_model, getattr(cfg, "llm_supports_tool_calling", "auto")
        ),
    )
    intent = parser.parse(query)
    parse_tokens = parser.last_tokens
    anchors = entity_linker.resolve(intent)

    # Step 2 — exactly ONE query. No evidence check, no fallback, no loop.
    selected = select_single_query(intent)
    if selected == "lookup":
        result = _run_lookup(tg_client, intent, anchors)
    elif selected == "aggregate":
        result = run_aggregation(tg_client, intent, anchors)
    else:
        result = run_graph_traversal(tg_client, anchors)

    evidence = result.evidence

    # DP-4: an unresolved venue is surfaced, not guessed. P2 has no fallback to
    # recover with, so the disambiguation candidates go into the context and
    # the model answers from what is actually known.
    context = format_evidence_into_context(evidence)
    if anchors.disambiguation_candidates:
        candidates = "; ".join(
            f"{field}: {', '.join(values)}"
            for field, values in anchors.disambiguation_candidates.items()
        )
        context = f"{context}\n\nAmbiguous anchor, candidates were: {candidates}"

    # Step 3 — single generation call, shared answer contract (CORE-02).
    try:
        answer, explanation, gen_tokens, token_source, _ = invoke_llm_with_answer_contract(
            model=chat_model,
            context=context,
            question=query,
            reports_usage=getattr(cfg, "llm_reports_token_usage", "auto"),
        )
        status: Any = "done"
        error_detail = None
    except Exception as e:  # noqa: BLE001 - NFR-2: P1 and P3 must be unaffected
        logger.error("LLM generation failed in P2: %s", e)
        answer, explanation = "", f"Generation error: {e}"
        gen_tokens = TokenUsage()
        token_source = "provider"
        status, error_detail = "error", str(e)

    citations = _citations_from(evidence)
    tokens = TokenUsage(
        input=parse_tokens.input + gen_tokens.input,
        output=parse_tokens.output + gen_tokens.output,
        total=parse_tokens.total + gen_tokens.total,
    )

    return PipelineRecord(
        pipeline="graphrag",
        answer=answer,
        explanation=explanation,
        citations=citations,
        chunks_returned=result.chunks_returned,
        citations_count=len(citations),
        tokens=tokens,
        token_source=token_source,
        latency_ms=(time.perf_counter() - started) * 1000.0,
        trace=None,
        strategy_changed=None,
        stop_reason=None,
        status=status,
        error_detail=error_detail,
    )
