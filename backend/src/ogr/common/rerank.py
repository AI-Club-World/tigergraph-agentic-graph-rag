"""Cross-encoder re-ranking of prose chunks — no LLM call.

LLM-ALLOCATION plan G-2 / DP-2: Cloudflare Workers AI `@cf/baai/bge-reranker-base`
(512-token context; chunks are 300). Used by P3 only — P1 stays the unfiltered
baseline (AD-9, DP-1). When the reranker is unavailable the input order is
returned unchanged, so a P3 run never ranks worse than without it.
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
        return chunks
    url = f"https://api.cloudflare.com/client/v4/accounts/{cfg.cloudflare_account_id}/ai/run/{RERANK_MODEL}"
    try:
        body = _post_json(
            url,
            {"query": query, "contexts": [{"text": c.get("text", "")} for c in chunks]},
            cfg.cloudflare_api_token,
        )
        scores = {int(r["id"]): float(r["score"]) for r in body["result"]["response"]}
    except Exception as e:
        logger.warning("Rerank failed (%s); keeping retrieval order", str(e)[:200])
        return chunks
    order = sorted(range(len(chunks)), key=lambda i: -scores.get(i, float("-inf")))
    return [chunks[i] for i in order]
