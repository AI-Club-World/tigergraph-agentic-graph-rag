"""Keep the suite hermetic: no test may call a live provider or download weights.

Set before `ogr` is imported, so config's load_dotenv() — which never
overrides an existing variable — cannot pull a developer's real keys from
.env. Embedding then uses the local tier from cache, or the hash fallback.
"""

import os

os.environ["HF_HUB_OFFLINE"] = "1"
for _key in (
    "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "NVIDIA_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY",
):
    os.environ[_key] = ""


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_out_dir(monkeypatch, tmp_path):
    """The API writes runtime state (trial history, dataset registry, batch
    runs) under OUT_DIR; tests get their own so a developer's out/ is never
    written by the suite. Tests that need a specific OUT_DIR still set it."""
    import ogr.api.main as api_main

    monkeypatch.setattr(api_main, "OUT_DIR", tmp_path / "out")


@pytest.fixture
def fake_embedder(monkeypatch):
    """A stand-in local model for every catalog model: deterministic vectors
    of that model's own size, so strict embedding (builds, re-embed jobs)
    works without weights."""
    from ogr.common import embeddings
    from ogr.common.embedding_models import EMBEDDING_MODELS

    class _Model:
        def __init__(self, dim):
            self.dim = dim

        def encode(self, texts, normalize_embeddings, batch_size):
            return [embeddings._fallback_vector(t, self.dim) for t in texts]

    def get(name, trust_remote_code=False):
        return _Model(next(m.dim for m in EMBEDDING_MODELS.values() if m.hf_id == name))

    monkeypatch.setattr(embeddings, "get_embedding_model", get)


def make_embeddings_ready(out_dir, model_key="bge-large-en-v1.5", chunk_ids=("Q1_c0",)):
    """A built corpus whose `model_key` embeddings cover every chunk."""
    from ogr.ingest.embedding_index import EmbeddingStore
    from ogr.ingest.registry import DatasetRegistry

    registry = DatasetRegistry(out_dir / "datasets.json")
    registry.reset(model_key, 1024)
    registry.record("corpus", {"doc_ids": ["Q1"], "chunk_ids": list(chunk_ids)}, {"documents": 1, "chunks": 1}, 1)
    store = EmbeddingStore(out_dir / "embeddings.json")
    store.reset(model_key)
    store.add_covered(model_key, list(chunk_ids))
    return store


@pytest.fixture
def ready_embeddings():
    """The active model has complete embeddings: queries and runs may start."""
    import ogr.api.main as api_main

    return make_embeddings_ready(api_main.OUT_DIR)


@pytest.fixture(autouse=True)
def _fresh_health_cache():
    """Health results are cached per process; each test starts without one."""
    import ogr.api.main as api_main

    api_main._health_cache.clear()
    yield
    api_main._health_cache.clear()
