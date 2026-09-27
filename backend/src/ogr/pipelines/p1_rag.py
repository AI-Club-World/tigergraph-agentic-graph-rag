"""P1 — Unfiltered RAG Baseline Pipeline.

Source spec: TECHNICAL-SPEC §8.1 · ARCHITECTURE-SPEC §2, AD-9 · APPLICATION-SPEC FR-2/4/10
Plan: implementation-plan-RAG.md (PLAN-002)

CRITICAL ARCHITECTURAL CONSTRAINT (AD-9):
This baseline is strictly UNFILTERED. Its retrieval ceiling must remain visible, not masked.
- Q5 is called directly via TigerGraphClient with vtype="Chunk", k from run_config (k=10).
- No candidate_set, no type filtering, no re-ranking, no relevance threshold.
- LangChain is used ONLY for the single LLM generation call; no retriever classes are imported.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ogr.common.config import RunConfig, get_default_config
from ogr.common.contracts import Citation, PipelineRecord, TokenUsage
from ogr.common.embeddings import embed_query
from ogr.common.llm import LLMRateLimitError, get_chat_model, invoke_llm_with_answer_contract
from ogr.graph.client import TigerGraphClient

logger = logging.getLogger(__name__)


def format_chunks_into_context(chunks: list[dict[str, Any]]) -> str:
    """Formats retrieved chunks into text context for the shared generation prompt."""
    if not chunks:
        return "No relevant documents found."

    context_parts: list[str] = []
    for idx, chunk in enumerate(chunks, 1):
        doc_id = chunk.get("doc_id", "unknown")
        chunk_id = chunk.get("chunk_id", "unknown")
        text = chunk.get("text", "").strip()
        context_parts.append(f"[{idx}] [Doc: {doc_id} | Chunk: {chunk_id}]\n{text}")

    return "\n\n".join(context_parts)


def run_p1_rag(
    query: str,
    client: TigerGraphClient | None = None,
    config: RunConfig | None = None,
    model: Any | None = None,
) -> PipelineRecord:
    """Executes the P1 unfiltered RAG pipeline.

    Steps:
    1. Embed query into vector using the configured local embedding model.
    2. Retrieve top-k chunks via Q5 hybrid_search with vtype='Chunk' (NO candidate_set, NO filter, NO rerank).
    3. Format context and invoke single generation call with CORE-02 shared prompt.
    4. Populate citations resolving source_id to parent doc_id (wikidata QID) and chunk_id for display.
    5. Return structured PipelineRecord with latency and token metrics captured at the invocation layer.
    """
    total_start_time = time.perf_counter()
    cfg = config or get_default_config()
    tg_client = client or TigerGraphClient(cfg)

    # Step 1: Embed query with the model whose index is searched below. A
    # failure fails the pipeline: a stand-in vector would search noise.
    query_vector = embed_query(query, model_name=cfg.embedding_model, strict=True)

    # Step 2: Unfiltered retrieval via Q5 (Chunk only, k=10 per DP-1 / DP-2 Option A)
    # AD-9: No candidate_set, no type predicate, no post-retrieval filtering, no re-ranking
    retrieved_chunks = tg_client.hybrid_search(
        query_vector=query_vector,
        k=cfg.k,
        vtype="Chunk",
        candidate_set=None,
        embedding_model=cfg.embedding_model,
    )
    chunks_returned = len(retrieved_chunks)

    # Step 3: Format context
    context = format_chunks_into_context(retrieved_chunks)

    # Step 4: Single generation call using shared answer contract (CORE-02)
    if model is None:
        model = get_chat_model(cfg)

    try:
        answer, explanation, tokens, token_source, gen_latency_ms = invoke_llm_with_answer_contract(
            model=model,
            context=context,
            question=query,
            reports_usage=cfg.llm_reports_token_usage,
        )
        status = "done"
        error_detail = None
    except LLMRateLimitError:
        raise  # DP-3: stop the run; the user switches model
    except Exception as e:
        logger.error("LLM generation failed in P1: %s", e)
        answer = ""
        explanation = f"Generation error: {e}"
        tokens = TokenUsage(input=0, output=0, total=0)
        token_source = "provider"
        status = "error"
        error_detail = str(e)

    # Step 5: Build citations (source_id = parent doc_id, chunk_id retained for display)
    citations: list[Citation] = []
    for chunk in retrieved_chunks:
        doc_id = chunk.get("doc_id", "")
        chunk_id = chunk.get("chunk_id")
        citations.append(
            Citation(
                source_id=doc_id,
                chunk_id=chunk_id,
                ref_type="chunk",
            )
        )
    citations_count = len(citations)

    total_latency_ms = (time.perf_counter() - total_start_time) * 1000.0

    return PipelineRecord(
        pipeline="rag",
        answer=answer,
        explanation=explanation,
        citations=citations,
        chunks_returned=chunks_returned,
        citations_count=citations_count,
        tokens=tokens,
        token_source=token_source,
        latency_ms=total_latency_ms,
        trace=None,
        strategy_changed=None,
        stop_reason=None,
        status=status,
        error_detail=error_detail,
    )
