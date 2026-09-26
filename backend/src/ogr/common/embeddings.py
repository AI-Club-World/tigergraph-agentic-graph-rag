"""Embedding utilities for OGR pipelines.
One model — BAAI bge-m3, 1024-dim — for ingestion and every pipeline's query
path, so the index and the queries are always embedded by the same model.

The model is served by the first host that works (DP-4, LLM-ALLOCATION plan):
Cloudflare Workers AI `@cf/baai/bge-m3` → NVIDIA NIM `baai/bge-m3` → local
sentence-transformers `BAAI/bge-m3` → hash fallback. A host is skipped when
its credentials are absent. Every tier runs the same model, so a vector from
any tier lives in the one index space.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
import urllib.request

logger = logging.getLogger(__name__)

CLOUDFLARE_MODEL = "@cf/baai/bge-m3"
NVIDIA_MODEL = "baai/bge-m3"
LOCAL_MODEL = "BAAI/bge-m3"
NVIDIA_EMBEDDINGS_URL = "https://integrate.api.nvidia.com/v1/embeddings"
# Texts per HTTP request; keeps each request well under provider size limits.
REMOTE_BATCH_SIZE = 50

# model_name -> loaded model, or None when loading failed (not retried).
_MODELS: dict[str, object | None] = {}
_MODELS_LOCK = threading.Lock()


def get_embedding_model(model_name: str = LOCAL_MODEL):
    """Loads and caches the local embedding model, one instance per model name."""
    with _MODELS_LOCK:
        if model_name not in _MODELS:
            try:
                from sentence_transformers import SentenceTransformer

                try:
                    # Cached weights first: an online check on every process
                    # start hits Hugging Face rate limits (90 s waits observed).
                    _MODELS[model_name] = SentenceTransformer(model_name, local_files_only=True)
                except Exception:
                    _MODELS[model_name] = SentenceTransformer(model_name)
            except Exception as e:
                # Every embedding after this is a hash pseudo-vector, so
                # semantic search runs against noise. Say so loudly, once.
                logger.error(
                    "Embedding model %r failed to load (%s); using the hash fallback — "
                    "vector search results are NOT semantic",
                    model_name,
                    e,
                )
                _MODELS[model_name] = None
        return _MODELS[model_name]


def _post_json(url: str, payload: dict, token: str, timeout_s: float = 60.0) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        return json.loads(response.read())


def _embed_cloudflare(texts: list[str], account_id: str, token: str) -> list[list[float]]:
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{CLOUDFLARE_MODEL}"
    return _post_json(url, {"text": texts}, token)["result"]["data"]


def _embed_nvidia(texts: list[str], token: str) -> list[list[float]]:
    body = _post_json(
        NVIDIA_EMBEDDINGS_URL,
        {"model": NVIDIA_MODEL, "input": texts, "encoding_format": "float"},
        token,
    )
    return [row["embedding"] for row in sorted(body["data"], key=lambda row: row["index"])]


def _remote_tiers() -> list[tuple[str, object]]:
    """(name, embed_fn) for each remote host whose credentials are configured."""
    from ogr.common.config import get_default_config

    cfg = get_default_config()
    tiers: list[tuple[str, object]] = []
    if cfg.cloudflare_account_id and cfg.cloudflare_api_token:
        tiers.append((
            "cloudflare",
            lambda batch: _embed_cloudflare(batch, cfg.cloudflare_account_id, cfg.cloudflare_api_token),
        ))
    if cfg.nvidia_api_key:
        tiers.append(("nvidia_nim", lambda batch: _embed_nvidia(batch, cfg.nvidia_api_key)))
    return tiers


def embedding_backend(model_name: str | None = None) -> str:
    """Primary tier — 'cloudflare', 'nvidia_nim', 'sentence-transformers' or
    'hash_fallback' — recorded in each batch run's header so a degraded run is
    visible in its results (NFR-4)."""
    tiers = _remote_tiers()
    if tiers:
        return tiers[0][0]
    return "sentence-transformers" if get_embedding_model() is not None else "hash_fallback"


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [float(x) / norm for x in vector]


def _fallback_vector(text: str, dim: int) -> list[float]:
    """Deterministic normalized vector from a sha256 hash, for unit testing
    without downloading model weights."""
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    raw = [(seed[i % len(seed)] / 255.0) * 2.0 - 1.0 for i in range(dim)]
    return _normalize(raw)


def _embed_batch(texts: list[str], dim: int, batch_size: int) -> list[list[float]]:
    """Embed one batch through the first tier that succeeds."""
    for name, embed in _remote_tiers():
        try:
            vectors = embed(texts)
            if len(vectors) != len(texts):
                raise ValueError(f"{len(vectors)} vectors for {len(texts)} texts")
            return [_normalize(v) for v in vectors]
        except Exception as e:
            logger.warning("Embedding tier %s failed (%s); trying the next tier", name, str(e)[:200])
    model = get_embedding_model()
    if model is not None:
        vectors = model.encode(texts, normalize_embeddings=True, batch_size=batch_size)
        return [[float(x) for x in vector] for vector in vectors]
    return [_fallback_vector(text, dim) for text in texts]


def embed_query(
    text: str,
    model_name: str | None = None,
    dim: int = 1024,
) -> list[float]:
    """Generates a normalized bge-m3 embedding vector for query text.
    `model_name` is kept for caller compatibility; every tier serves bge-m3."""
    return _embed_batch([text], dim, batch_size=1)[0]


def embed_texts(
    texts: list[str],
    model_name: str | None = None,
    dim: int = 1024,
    batch_size: int = 64,
) -> list[list[float]]:
    """Batch form of embed_query — GRAPH-04 embeds every document's chunks,
    so texts go to the host in batches rather than one request per text."""
    vectors: list[list[float]] = []
    for start in range(0, len(texts), REMOTE_BATCH_SIZE):
        vectors.extend(_embed_batch(texts[start:start + REMOTE_BATCH_SIZE], dim, batch_size))
    return vectors
