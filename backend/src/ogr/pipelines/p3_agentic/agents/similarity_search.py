"""Similarity search agent — thin wrapper over Q5 (hybrid_search).

Source spec: ARCHITECTURE-SPEC §4 · TECHNICAL-SPEC §3
Decision: agent DP-2 Option A (ARCHITECTURE-SPEC, Decision log)

Implements the 'Similarity search' specialised agent.
Triggered by the evidence evaluator on scope-coverage failure (DP-2).
Sets strategy_change=True to feed the Strategy-Change Detector.

This is deliberately a thin wrapper over Q5 — the same Q5 called by P1,
but here it is a fallback triggered by evidence evaluation failure, not
the primary retrieval path.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ogr.common.embeddings import embed_query
from ogr.graph.client import TigerGraphClient
from ogr.pipelines.p3_agentic.agents.agent_result import AgentResult

logger = logging.getLogger(__name__)


def run_similarity_search(
    client: TigerGraphClient,
    query: str,
    k: int = 10,
    embedding_model: str | None = None,
    embedding_dim: int = 1024,
    candidate_set: list[str] | None = None,
    triggered_by: str = "scope_coverage_fail",
) -> AgentResult:
    """Execute Q5 hybrid_search similarity expansion.

    Triggered by scope-coverage failure in the Evidence Evaluator (DP-2 Option A).
    strategy_change=True is set to mark this deviation from the initial route.

    Args:
        client: TigerGraph client.
        query: The original question text to embed.
        k: Top-k chunks to retrieve.
        embedding_model: Embedding model name.
        embedding_dim: Vector dimension.
        candidate_set: Optional pre-filtered candidate set (None = unfiltered).
        triggered_by: Context label for trace notes.
    """
    t0 = time.perf_counter()

    try:
        # One model key picks both the query embedding and the index searched.
        query_vector = embed_query(query, model_name=embedding_model, strict=True)
        raw_chunks = client.hybrid_search(
            query_vector=query_vector,
            k=k,
            vtype="Chunk",
            candidate_set=candidate_set,
            embedding_model=embedding_model,
        )
    except Exception as e:
        logger.error("Q5 similarity search failed: %s", e)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return AgentResult(
            error=str(e),
            latency_ms=latency_ms,
            strategy_change=True,
            notes=f"Q5 similarity fallback error: {e}",
        )

    latency_ms = (time.perf_counter() - t0) * 1000.0
    evidence = _normalize_chunks(raw_chunks)

    return AgentResult(
        evidence=evidence,
        chunks_returned=len(evidence),
        citations_count=len(evidence),
        latency_ms=latency_ms,
        strategy_change=True,  # This is always a strategy deviation
        notes=f"Q5 similarity expansion: k={k}, triggered_by={triggered_by}",
    )


def _normalize_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "chunk_id": c.get("chunk_id", ""),
            "doc_id": c.get("doc_id", ""),
            "text": c.get("text", ""),
            "score": c.get("score", 0.0),
            "source": "similarity_search",
        }
        for c in chunks
    ]
