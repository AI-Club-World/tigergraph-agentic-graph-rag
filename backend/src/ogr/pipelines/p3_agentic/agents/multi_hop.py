"""Multi-hop reasoning agent — planner chaining Q4 → Q1.

Source spec: ARCHITECTURE-SPEC §4 · TECHNICAL-SPEC §3
Plan: implementation-plan-AGENT.md Group 3

Implements the 'Multi-hop reasoning' specialised agent.
Chains: Q4 (traverse temporal edges) → Q1 (direct lookup on resolved event).

Used for temporal chains like:
  "What sport was contested at the previous edition of [event]?"
  → Q4 traverses PREV_EDITION from anchor event
  → Q1 looks up the target field on the traversed event

This is the correct amount of machinery for the five question types —
stated explicitly, not apologised for.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ogr.graph.client import TigerGraphClient
from ogr.pipelines.p3_agentic.agents.agent_result import AgentResult
from ogr.pipelines.p3_agentic.agents.entity_linking import ResolvedAnchors
from ogr.pipelines.p3_agentic.intent import IntentSchema

logger = logging.getLogger(__name__)


def run_multi_hop(
    client: TigerGraphClient,
    intent: IntentSchema,
    anchors: ResolvedAnchors,
    edge_type: str = "PREV_EDITION",
    hops: int = 1,
) -> AgentResult:
    """Execute Q4 → Q1 chain for multi-hop/temporal questions.

    Step 1: Q4 traverse from the anchor along edge_type for hops steps.
    Step 2: Q1 lookup target_field on each traversed event.

    Args:
        client: TigerGraph client.
        intent: Parsed intent (provides target_field).
        anchors: Resolved anchor entities.
        edge_type: Edge type for traversal (PREV_EDITION, NEXT_EDITION, HELD_AT).
        hops: Number of traversal hops.
    """
    t0 = time.perf_counter()
    anchor_value = anchors.title or anchors.event_id or anchors.games or ""

    if not anchor_value:
        return AgentResult(
            error="Multi-hop: no resolved anchor for Q4 traversal",
            notes=f"edge_type={edge_type}, hops={hops}",
        )

    # Step 1: Q4 traverse
    traversal_results: list[dict[str, Any]] = []
    try:
        params_q4 = {"anchor": anchor_value, "edge_type": edge_type, "hops": hops}
        traversal_results = client._run_query("q4_traverse", params_q4)
    except Exception as e:
        logger.error("Multi-hop Q4 failed: %s", e)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return AgentResult(error=f"Q4 error: {e}", latency_ms=latency_ms)

    if not traversal_results:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return AgentResult(
            evidence=[],
            chunks_returned=0,
            latency_ms=latency_ms,
            notes=f"Q4→Q1: no results from traversal anchor={anchor_value}",
        )

    # Step 2: Q1 lookup on each traversed event
    all_evidence: list[dict[str, Any]] = []
    target_field = intent.target_field or "event_name"

    for traversed in traversal_results:
        attrs = traversed.get("attributes", traversed)
        event_id = attrs.get("event_id") or traversed.get("v_id", "")
        if not event_id:
            continue
        try:
            params_q1 = {"event_id": event_id, "target_field": target_field}
            q1_results = client._run_query("q1_lookup", params_q1)
            for r in (q1_results or []):
                r_attrs = r.get("attributes", r)
                all_evidence.append({
                    "event_id": event_id,
                    "target_field": target_field,
                    "value": r_attrs.get(target_field, r_attrs.get("value", "")),
                    "doc_id": r_attrs.get("doc_id", ""),
                    "source": "multi_hop",
                })
        except Exception as e:
            logger.warning("Multi-hop Q1 lookup failed for event %s: %s", event_id, e)

    latency_ms = (time.perf_counter() - t0) * 1000.0
    return AgentResult(
        evidence=all_evidence,
        chunks_returned=len(all_evidence),
        citations_count=len(all_evidence),
        latency_ms=latency_ms,
        notes=(
            f"Q4→Q1 chain: edge={edge_type}, hops={hops}, "
            f"traversed={len(traversal_results)}, resolved={len(all_evidence)}"
        ),
    )
