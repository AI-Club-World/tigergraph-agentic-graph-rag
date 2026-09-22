"""Embedding utilities for OGR pipelines.
Generates 384-dimensional query embeddings using sentence-transformers/all-MiniLM-L6-v2.
"""

from __future__ import annotations

import hashlib
import math

_MODEL_INSTANCE = None


def get_embedding_model(model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
    """Loads and caches the local embedding model."""
    global _MODEL_INSTANCE
    if _MODEL_INSTANCE is None:
        try:
            from sentence_transformers import SentenceTransformer
            _MODEL_INSTANCE = SentenceTransformer(model_name)
        except Exception:
            _MODEL_INSTANCE = None
    return _MODEL_INSTANCE


def embed_query(
    text: str,
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    dim: int = 384,
) -> list[float]:
    """Generates a normalized embedding vector for query text.
    Uses sentence-transformers if available; otherwise produces a deterministic normalized vector.
    """
    model = get_embedding_model(model_name)
    if model is not None:
        vector = model.encode(text, normalize_embeddings=True)
        return [float(x) for x in vector]

    # Deterministic fallback vector based on sha256 hash for unit testing without downloading model weights
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    raw = [(seed[i % len(seed)] / 255.0) * 2.0 - 1.0 for i in range(dim)]
    norm = math.sqrt(sum(x * x for x in raw)) or 1.0
    return [x / norm for x in raw]
