"""Embedding utilities for OGR pipelines.

Every call names the embedding model (`common/embedding_models.py`); the
index a vector is written to and the index a query vector searches are both
chosen from that same model key, so the two can never come from different
models (config-docs/EMBEDDING-SWITCHING.md).

A model is served by the first host that works: Cloudflare Workers AI (only
for a model Cloudflare hosts, and only with credentials) → local
sentence-transformers → hash fallback. Every real tier runs the same model,
so a vector from any of them lives in that model's one space.

The hash fallback is noise, not a model. Non-strict callers get it (loudly
logged, recorded as the run's `embedding_backend`) so a machine without
weights can still exercise the pipelines; `strict=True` raises instead, and
every write to an embedding index is strict — noise is never stored as a
model's embeddings.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
import urllib.request

from ogr.common.embedding_models import EmbeddingModel, resolve_model

logger = logging.getLogger(__name__)

# Texts per HTTP request; keeps each request well under provider size limits.
REMOTE_BATCH_SIZE = 50

# hf_id -> loaded model, or None when loading failed (not retried).
_MODELS: dict[str, object | None] = {}
_MODELS_LOCK = threading.Lock()


class EmbeddingUnavailable(RuntimeError):
    """No real tier could serve the model (raised only in strict mode)."""


def get_embedding_model(model_name: str, trust_remote_code: bool = False):
    """Loads and caches a local sentence-transformers model, one instance per name."""
    with _MODELS_LOCK:
        if model_name not in _MODELS:
            try:
                from sentence_transformers import SentenceTransformer

                kwargs = {"trust_remote_code": True} if trust_remote_code else {}
                try:
                    # Cached weights first: an online check on every process
                    # start hits Hugging Face rate limits (90 s waits observed).
                    _MODELS[model_name] = SentenceTransformer(model_name, local_files_only=True, **kwargs)
                except Exception:
                    _MODELS[model_name] = SentenceTransformer(model_name, **kwargs)
            except Exception as e:
                logger.error(
                    "Embedding model %r failed to load (%s); non-strict callers get the hash "
                    "fallback — vector search results are NOT semantic",
                    model_name,
                    e,
                )
                _MODELS[model_name] = None
        return _MODELS[model_name]


def _local(model: EmbeddingModel):
    return get_embedding_model(model.hf_id, model.trust_remote_code)


def _post_json(url: str, payload: dict, token: str, timeout_s: float = 60.0) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        # Explicit User-Agent: Cloudflare-fronted APIs (Groq, Workers AI) reject
        # urllib's default one with error 1010 / HTTP 403.
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "ogr/0.1",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        return json.loads(response.read())


def _embed_cloudflare(
    texts: list[str], account_id: str, token: str, model_id: str, options: dict[str, str] | None = None
) -> list[list[float]]:
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model_id}"
    return _post_json(url, {"text": texts, **(options or {})}, token)["result"]["data"]


def _remote_tiers(model: EmbeddingModel) -> list[tuple[str, object]]:
    """(name, embed_fn) for each remote host that serves `model` and is configured."""
    from ogr.common.config import get_default_config

    cfg = get_default_config()
    tiers: list[tuple[str, object]] = []
    cloudflare_ready = cfg.cloudflare_account_id and cfg.cloudflare_api_token
    if cfg.embedding_remote and model.cloudflare_id and cloudflare_ready:
        tiers.append((
            "cloudflare",
            lambda batch: _embed_cloudflare(
                batch, cfg.cloudflare_account_id, cfg.cloudflare_api_token, model.cloudflare_id,
                dict(model.cloudflare_options),
            ),
        ))
    return tiers


def embedding_backend(model_name: str | None = None) -> str:
    """Primary tier for the model — 'cloudflare', 'sentence-transformers' or
    'hash_fallback' — recorded in each batch run's header and each embedding
    index so a degraded run is visible in its results (NFR-4)."""
    model = resolve_model(model_name)
    tiers = _remote_tiers(model)
    if tiers:
        return tiers[0][0]
    return "sentence-transformers" if _local(model) is not None else "hash_fallback"


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [float(x) / norm for x in vector]


def _fallback_vector(text: str, dim: int) -> list[float]:
    """Deterministic normalized vector from a sha256 hash, for unit testing
    without downloading model weights."""
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    raw = [(seed[i % len(seed)] / 255.0) * 2.0 - 1.0 for i in range(dim)]
    return _normalize(raw)


def _embed_batch(model: EmbeddingModel, texts: list[str], batch_size: int, strict: bool) -> list[list[float]]:
    """Embed one batch (prompts already applied) through the first tier that succeeds."""
    errors = []
    for name, embed in _remote_tiers(model):
        try:
            vectors = embed(texts)
            if len(vectors) != len(texts):
                raise ValueError(f"{len(vectors)} vectors for {len(texts)} texts")
            return [_check_dim(model, _normalize(v)) for v in vectors]
        except Exception as e:
            errors.append(f"{name}: {str(e)[:200]}")
            logger.warning(
                "Embedding tier %s failed for %s (%s); trying the next tier", name, model.key, str(e)[:200]
            )
    local = _local(model)
    if local is not None:
        vectors = local.encode(texts, normalize_embeddings=True, batch_size=batch_size)
        return [_check_dim(model, [float(x) for x in vector]) for vector in vectors]
    if strict:
        raise EmbeddingUnavailable(
            f"No host could serve {model.label}: {'; '.join(errors) or 'no remote tier'}; "
            f"local {model.hf_id} not loadable"
        )
    return [_fallback_vector(text, model.dim) for text in texts]


def _check_dim(model: EmbeddingModel, vector: list[float]) -> list[float]:
    if len(vector) != model.dim:
        raise ValueError(f"{model.label} returned a {len(vector)}-dim vector; expected {model.dim}")
    return vector


def embed_query(
    text: str,
    model_name: str | None = None,
    dim: int | None = None,
    strict: bool = False,
) -> list[float]:
    """A normalized query embedding from `model_name`, with its query prompt.
    `dim` is kept for caller compatibility; the model fixes the dimension."""
    model = resolve_model(model_name)
    return _embed_batch(model, [model.query_prefix + text], batch_size=1, strict=strict)[0]


def embed_texts(
    texts: list[str],
    model_name: str | None = None,
    dim: int | None = None,
    batch_size: int = 64,
    strict: bool = False,
) -> list[list[float]]:
    """Document embeddings from `model_name` (its document prompt applied),
    sent to the host in batches rather than one request per text."""
    model = resolve_model(model_name)
    prepared = [model.doc_prefix + t for t in texts]
    vectors: list[list[float]] = []
    for start in range(0, len(prepared), REMOTE_BATCH_SIZE):
        vectors.extend(_embed_batch(model, prepared[start:start + REMOTE_BATCH_SIZE], batch_size, strict))
    return vectors
