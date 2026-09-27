"""Graph traversal agent — thin wrapper over Q4 (traverse).

Source spec: ARCHITECTURE-SPEC §4 · TECHNICAL-SPEC §3

Implements the 'Graph traversal' specialised agent:
  Q4: traverse(anchor, edge_type, hops)
  Used for TRAVERSE operations — temporal chains and multi-hop relations.
  Primary edges: PREV_EDITION / NEXT_EDITION / HELD_AT
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ogr.graph.client import TigerGraphClient
from ogr.pipelines.p3_agentic.agents.agent_result import AgentResult
from ogr.pipelines.p3_agentic.agents.entity_linking import ResolvedAnchors

logger = logging.getLogger(__name__)


def run_graph_traversal(
    client: TigerGraphClient,
    anchors: ResolvedAnchors,
    edge_type: str = "PREV_EDITION",
    hops: int = 1,
    notes: str = "",
) -> AgentResult:
    """Execute Q4 traverse query and return AgentResult.

    Args:
        client: TigerGraph client.
        anchors: Resolved entity anchors from entity linking.
        edge_type: Edge type to traverse (PREV_EDITION, NEXT_EDITION, HELD_AT).
        hops: Number of hops to traverse.
        notes: Context note for trace.
    """
    t0 = time.perf_counter()

    anchor_value = anchors.title or anchors.event_id or anchors.venue or ""
    if not anchor_value:
        return AgentResult(
            error="No resolved anchor for graph traversal",
            notes=f"edge_type={edge_type}, hops={hops}",
        )

    params = {
        "anchor": anchor_value,
        "edge_type": edge_type,
        "hops": hops,
    }

    raw_results: list[dict[str, Any]] = []
    try:
        raw_results = client._run_query("q4_traverse", params)
    except Exception as e:
        logger.error("Q4 traverse failed: %s", e)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return AgentResult(
            error=str(e),
            latency_ms=latency_ms,
            notes=f"Q4 traverse error: {e}",
        )

    latency_ms = (time.perf_counter() - t0) * 1000.0
    evidence = _normalize_traverse_results(raw_results)

    return AgentResult(
        evidence=evidence,
        chunks_returned=len(evidence),
        citations_count=len(evidence),
        latency_ms=latency_ms,
        notes=notes or f"Q4 traverse: edge={edge_type}, hops={hops}, anchor={anchor_value}",
    )


def _normalize_traverse_results(raw: Any) -> list[dict[str, Any]]:
    if not raw or not isinstance(raw, list):
        return []
    results = []
    for item in raw:
        attrs = item.get("attributes", item)
        results.append({
            "event_id": attrs.get("event_id", item.get("v_id", "")),
            "event_name": attrs.get("event_name", ""),
            "doc_id": attrs.get("doc_id", ""),
            "source": "graph_traversal",
        })
    return results
