"""Document retrieval agent — HAS_CHUNK expansion for prose fallback.

Source spec: ARCHITECTURE-SPEC §4 · TECHNICAL-SPEC §2.2
Plan: implementation-plan-AGENT.md Group 3, DP-2 Option A

Implements the 'Document retrieval' specialised agent.
Triggered by groundedness failure or empty anchor resolution (DP-2).
Expands from a Document vertex to its Chunks via the HAS_CHUNK edge.

This is the primary fallback for eval-001-shaped questions:
  query anchors on a venue string that matches zero 'venue' fields —
  the entity linker returns None, evidence evaluation calls this agent,
  strategy_change is set True.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ogr.graph.client import TigerGraphClient
from ogr.pipelines.p3_agentic.agents.agent_result import AgentResult

logger = logging.getLogger(__name__)


def run_document_retrieval(
    client: TigerGraphClient,
    doc_ids: list[str] | None = None,
    event_ids: list[str] | None = None,
    triggered_by: str = "groundedness_fail",
) -> AgentResult:
    """Expand Document vertices → Chunks via HAS_CHUNK edge.

    Args:
        client: TigerGraph client.
        doc_ids: List of document QIDs to expand.
        event_ids: List of event IDs (will be resolved to their parent Documents).
        triggered_by: Context label for trace.
    """
    t0 = time.perf_counter()

    ids_to_fetch = doc_ids or []
    if not ids_to_fetch and not event_ids:
        return AgentResult(
            error="No doc_ids or event_ids supplied to document_retrieval",
            strategy_change=True,
            notes=f"triggered_by={triggered_by}",
        )

    try:
        raw_chunks = client._expand_has_chunk(ids_to_fetch)
    except Exception as e:
        logger.error("HAS_CHUNK expansion failed: %s", e)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return AgentResult(
            error=str(e),
            latency_ms=latency_ms,
            strategy_change=True,
            notes=f"HAS_CHUNK error: {e}",
        )

    latency_ms = (time.perf_counter() - t0) * 1000.0
    evidence = _normalize_chunks(raw_chunks)

    return AgentResult(
        evidence=evidence,
        chunks_returned=len(evidence),
        citations_count=len(evidence),
        latency_ms=latency_ms,
        strategy_change=True,  # Prose fallback is always a strategy deviation
        notes=f"HAS_CHUNK expansion: {len(ids_to_fetch)} docs, triggered_by={triggered_by}",
    )


def _normalize_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "chunk_id": c.get("chunk_id", ""),
            "doc_id": c.get("doc_id", ""),
            "text": c.get("text", ""),
            "seq": c.get("seq", 0),
            "source": "document_retrieval",
        }
        for c in chunks
    ]
