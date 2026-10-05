"""Per-model embedding (config-docs/EMBEDDING-SWITCHING.md)."""

from __future__ import annotations

import logging
import sys

import pytest

from ogr.common import embeddings as embeddings_module
from ogr.common.embedding_models import EMBEDDING_MODELS, UnknownEmbeddingModel, resolve_model
from ogr.common.embeddings import (
    EmbeddingUnavailable,
    embed_query,
    embed_texts,
    embedding_backend,
    get_embedding_model,
)


@pytest.fixture
def no_local(monkeypatch):
    """No weights: only the hash fallback (non-strict) is left."""
    monkeypatch.setattr(embeddings_module, "get_embedding_model", lambda *_a, **_k: None)


class _Local:
    def __init__(self, dim):
        self.dim = dim
        self.seen: list[str] = []

    def encode(self, texts, normalize_embeddings, batch_size):
        self.seen.extend(texts)
        return [[1.0] + [0.0] * (self.dim - 1) for _ in texts]


class TestCatalog:
    def test_five_models_with_their_dimensions_and_own_vertex_types(self):
        assert {m.label: m.dim for m in EMBEDDING_MODELS.values()} == {
            "Qwen3-Embedding-0.6B": 1024, "EmbeddingGemma-300M": 768, "gte-large-en-v1.5": 1024,
            "mxbai-embed-large-v1": 1024, "bge-large-en-v1.5": 1024,
        }
        assert len({m.vertex_type for m in EMBEDDING_MODELS.values()}) == 5

    def test_resolves_aliases_and_rejects_unknown_models(self):
        assert resolve_model("BAAI/bge-large-en-v1.5").key == "bge-large-en-v1.5"
        assert resolve_model("@cf/baai/bge-large-en-v1.5").key == "bge-large-en-v1.5"
        assert resolve_model("EmbeddingGemma-300M").key == "embeddinggemma-300m"
        with pytest.raises(UnknownEmbeddingModel):
            resolve_model("@cf/baai/bge-m3")


class TestEmbedTexts:
    def test_empty_input_returns_empty_output(self):
        assert embed_texts([]) == []

    def test_vectors_have_the_models_dimension(self, no_local):
        assert all(len(v) == 768 for v in embed_texts(["a", "b"], model_name="embeddinggemma-300m"))
        assert len(embed_query("q", model_name="qwen3-embedding-0.6b")) == 1024

    def test_query_and_document_prompts_are_the_models_own(self, monkeypatch):
        local = _Local(768)
        monkeypatch.setattr(embeddings_module, "get_embedding_model", lambda *_a, **_k: local)
        embed_query("who won", model_name="embeddinggemma-300m")
        embed_texts(["a passage"], model_name="embeddinggemma-300m")
        assert local.seen == ["task: search result | query: who won", "title: none | text: a passage"]

    def test_a_vector_of_the_wrong_size_is_refused(self, monkeypatch):
        monkeypatch.setattr(embeddings_module, "get_embedding_model", lambda *_a, **_k: _Local(1024))
        with pytest.raises(ValueError, match="expected 768"):
            embed_texts(["x"], model_name="embeddinggemma-300m")


class TestStrictMode:
    def test_strict_never_returns_hash_noise(self, no_local):
        with pytest.raises(EmbeddingUnavailable, match="bge-large-en-v1.5"):
            embed_texts(["x"], model_name="bge-large-en-v1.5", strict=True)
        with pytest.raises(EmbeddingUnavailable):
            embed_query("x", model_name="gte-large-en-v1.5", strict=True)

    def test_non_strict_falls_back_to_the_hash(self, no_local):
        assert len(embed_texts(["x"])[0]) == 1024
        assert embedding_backend() == "hash_fallback"


class TestModelLoadFailure:
    def test_failed_load_is_logged_and_reported_as_fallback(self, monkeypatch, caplog):
        monkeypatch.setitem(sys.modules, "sentence_transformers", None)  # import now fails
        monkeypatch.setattr(embeddings_module, "_MODELS", {})
        with caplog.at_level(logging.ERROR, logger="ogr.common.embeddings"):
            assert embedding_backend("mxbai-embed-large-v1") == "hash_fallback"
        assert "mixedbread-ai/mxbai-embed-large-v1" in caplog.text and "NOT semantic" in caplog.text

    def test_cache_is_keyed_by_model_name(self, monkeypatch):
        class _Fake:
            def __init__(self, name, **kwargs):
                self.name = name
                self.kwargs = kwargs

        monkeypatch.setitem(sys.modules, "sentence_transformers", type(sys)("sentence_transformers"))
        sys.modules["sentence_transformers"].SentenceTransformer = _Fake
        monkeypatch.setattr(embeddings_module, "_MODELS", {})
        assert get_embedding_model("model-a").name == "model-a"
        assert get_embedding_model("model-b").name == "model-b"
        assert get_embedding_model("model-a") is get_embedding_model("model-a")
        # gte-large ships custom modelling code.
        assert get_embedding_model("gte", trust_remote_code=True).kwargs["trust_remote_code"] is True


class TestProviderChain:
    """Cloudflare (only for a model it hosts) -> local -> hash."""

    @staticmethod
    def _creds(monkeypatch, cloudflare=True):
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct" if cloudflare else "")
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf-token" if cloudflare else "")

    def test_cloudflare_first_for_the_model_it_hosts(self, monkeypatch):
        self._creds(monkeypatch)
        calls = []

        def fake_post(url, payload, token, timeout_s=60.0):
            calls.append((url, payload, token))
            return {"result": {"data": [[3.0, 4.0] + [0.0] * 1022 for _ in payload["text"]]}}

        monkeypatch.setattr(embeddings_module, "_post_json", fake_post)
        [vector] = embed_texts(["a"], model_name="bge-large-en-v1.5")
        assert vector[:2] == [0.6, 0.8]
        url, payload, token = calls[0]
        assert url.endswith("/accounts/acct/ai/run/@cf/baai/bge-large-en-v1.5")
        # CLS pooling, as BGE and the local model use: both tiers share one space.
        assert payload == {"text": ["a"], "pooling": "cls"} and token == "cf-token"
        assert embedding_backend("bge-large-en-v1.5") == "cloudflare"

    def test_models_cloudflare_does_not_host_never_call_it(self, monkeypatch):
        self._creds(monkeypatch)

        def fail(*_a, **_k):
            raise AssertionError("Cloudflare called for a model it does not host")

        local = _Local(1024)
        monkeypatch.setattr(embeddings_module, "_post_json", fail)
        monkeypatch.setattr(embeddings_module, "get_embedding_model", lambda *_a, **_k: local)
        embed_query("q", model_name="qwen3-embedding-0.6b")
        assert local.seen[0].endswith("Query:q")

    def test_cloudflare_failure_falls_back_to_the_same_model_locally(self, monkeypatch):
        self._creds(monkeypatch)

        def fail(*_a, **_k):
            raise OSError("down")

        loaded = []
        monkeypatch.setattr(embeddings_module, "_post_json", fail)
        monkeypatch.setattr(
            embeddings_module, "get_embedding_model",
            lambda name, trust_remote_code=False: loaded.append(name) or _Local(1024),
        )
        assert embed_query("q", model_name="bge-large-en-v1.5")[0] == 1.0
        assert loaded == ["BAAI/bge-large-en-v1.5"]

    def test_large_inputs_are_sent_in_batches(self, monkeypatch):
        self._creds(monkeypatch)
        sizes = []

        def fake_post(url, payload, token, timeout_s=60.0):
            sizes.append(len(payload["text"]))
            return {"result": {"data": [[1.0] * 1024 for _ in payload["text"]]}}

        monkeypatch.setattr(embeddings_module, "_post_json", fake_post)
        assert len(embed_texts(["t"] * 120, model_name="bge-large-en-v1.5")) == 120
        assert sizes == [50, 50, 20]


def test_embedding_remote_false_keeps_cloudflare_for_nothing_but_rerank(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok")
    monkeypatch.setenv("EMBEDDING_REMOTE", "false")
    monkeypatch.setattr(embeddings_module, "_post_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("remote")))
    local = _Local(1024)
    monkeypatch.setattr(embeddings_module, "get_embedding_model", lambda *_a, **_k: local)
    assert embed_query("q", model_name="bge-large-en-v1.5")[0] == 1.0


def test_a_configured_embedding_host_is_tried_first(monkeypatch):
    monkeypatch.setenv("EMBEDDING_HOST_URL", "https://embed.example")
    sent = {}

    class _Resp:
        def __init__(self, body):
            self.body = body

        def read(self):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def fake_urlopen(request, timeout=0):
        import json as _json

        sent.update(url=request.full_url, body=_json.loads(request.data))
        return _Resp(_json.dumps({"embeddings": [[1.0] + [0.0] * 1023]}).encode())

    monkeypatch.setattr(embeddings_module.urllib.request, "urlopen", fake_urlopen)
    assert embed_query("who won", model_name="bge-large-en-v1.5")[0] == 1.0
    assert sent["url"] == "https://embed.example/embed"
    assert sent["body"]["model"] == "bge-large-en-v1.5"
    assert sent["body"]["texts"][0].startswith("Represent this sentence")  # the model's own prompt
    assert embedding_backend("bge-large-en-v1.5") == "embedding_host"
