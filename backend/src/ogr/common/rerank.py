"""Cross-encoder re-ranking of prose chunks — no LLM call.

G-2 / LLM DP-2 (ARCHITECTURE-SPEC, Decision log): Cloudflare Workers AI `@cf/baai/bge-reranker-base`
(512-token context; chunks are 300). Used by P3 only — P1 stays the unfiltered
baseline (AD-9, LLM DP-1). When Cloudflare is unavailable (no credentials,
quota, outage) the same model runs locally (`BAAI/bge-reranker-base` via
sentence-transformers), so a run's ranking does not depend on a provider's
quota. Only if both fail is the input order returned unchanged.
"""

from __future__ import annotations

import logging
from typing import Any

from ogr.common.embeddings import _post_json

logger = logging.getLogger(__name__)

RERANK_MODEL = "@cf/baai/bge-reranker-base"


def rerank(query: str, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return `chunks` sorted by cross-encoder relevance to `query`, best first."""
    if len(chunks) < 2 or not query:
        return chunks
    from ogr.common.config import get_default_config

    cfg = get_default_config()
    if not (cfg.cloudflare_account_id and cfg.cloudflare_api_token):
        return _rerank_local(query, chunks)
    url = f"https://api.cloudflare.com/client/v4/accounts/{cfg.cloudflare_account_id}/ai/run/{RERANK_MODEL}"
    try:
        body = _post_json(
            url,
            {"query": query, "contexts": [{"text": c.get("text", "")} for c in chunks]},
            cfg.cloudflare_api_token,
        )
        scores = {int(r["id"]): float(r["score"]) for r in body["result"]["response"]}
    except Exception as e:
        logger.warning("Cloudflare rerank failed (%s); using the local model", str(e)[:200])
        return _rerank_local(query, chunks)
    order = sorted(range(len(chunks)), key=lambda i: -scores.get(i, float("-inf")))
    return [chunks[i] for i in order]


LOCAL_RERANK_MODEL = "BAAI/bge-reranker-base"
_local_model: Any = None
_local_failed = False


def _rerank_local(query: str, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The same cross-encoder, locally; the input order if it cannot load."""
    global _local_model, _local_failed
    if _local_failed:
        return chunks
    try:
        if _local_model is None:
            from sentence_transformers import CrossEncoder

            try:
                _local_model = CrossEncoder(LOCAL_RERANK_MODEL, local_files_only=True)
            except Exception:
                _local_model = CrossEncoder(LOCAL_RERANK_MODEL)
        scores = _local_model.predict([(query, c.get("text", "")) for c in chunks])
    except Exception as e:  # noqa: BLE001 - reranking is an improvement, never a requirement
        logger.warning("Local rerank unavailable (%s); keeping retrieval order", str(e)[:200])
        _local_failed = True
        return chunks
    order = sorted(range(len(chunks)), key=lambda i: -float(scores[i]))
    return [chunks[i] for i in order]
