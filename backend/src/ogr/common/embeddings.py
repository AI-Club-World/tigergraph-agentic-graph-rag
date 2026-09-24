"""Embedding utilities for OGR pipelines.
Generates 384-dimensional embeddings with the configured local
sentence-transformers model (`EMBEDDING_MODEL`, default BAAI/bge-small-en-v1.5).
Ingestion and every pipeline's query path call this one module, so the index
and the queries are always embedded by the same model.
"""

from __future__ import annotations

import hashlib
import logging
import math
import threading

logger = logging.getLogger(__name__)

# model_name -> loaded model, or None when loading failed (not retried).
_MODELS: dict[str, object | None] = {}
_MODELS_LOCK = threading.Lock()


def _configured_model() -> str:
    from ogr.common.config import get_default_config

    return get_default_config().embedding_model


def get_embedding_model(model_name: str | None = None):
    """Loads and caches the local embedding model, one instance per model name."""
    model_name = model_name or _configured_model()
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


def embedding_backend(model_name: str | None = None) -> str:
    """'sentence-transformers' or 'hash_fallback' — recorded in each batch
    run's header so a degraded run is visible in its results (NFR-4)."""
    return "sentence-transformers" if get_embedding_model(model_name) is not None else "hash_fallback"


def _fallback_vector(text: str, dim: int) -> list[float]:
    """Deterministic normalized vector from a sha256 hash, for unit testing
    without downloading model weights."""
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    raw = [(seed[i % len(seed)] / 255.0) * 2.0 - 1.0 for i in range(dim)]
    norm = math.sqrt(sum(x * x for x in raw)) or 1.0
    return [x / norm for x in raw]


def embed_query(
    text: str,
    model_name: str | None = None,
    dim: int = 384,
) -> list[float]:
    """Generates a normalized embedding vector for query text.
    Uses sentence-transformers if available; otherwise produces a deterministic normalized vector.
    """
    model = get_embedding_model(model_name)
    if model is not None:
        vector = model.encode(text, normalize_embeddings=True)
        return [float(x) for x in vector]
    return _fallback_vector(text, dim)


def embed_texts(
    texts: list[str],
    model_name: str | None = None,
    dim: int = 384,
    batch_size: int = 64,
) -> list[list[float]]:
    """Batch form of embed_query — one model load, many texts.

    GRAPH-04 embeds all 2,951 documents' chunks; encoding one text at a time
    would reload nothing (the model is cached), but sentence-transformers'
    own batching is materially faster than a Python-level loop over
    `model.encode(single_text)` calls.
    """
    if not texts:
        return []
    model = get_embedding_model(model_name)
    if model is not None:
        vectors = model.encode(texts, normalize_embeddings=True, batch_size=batch_size)
        return [[float(x) for x in vector] for vector in vectors]
    return [_fallback_vector(text, dim) for text in texts]
