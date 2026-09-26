"""Tests for embed_texts, the batch form GRAPH-04 uses to embed 2,951 documents."""

from __future__ import annotations

import logging
import sys

from ogr.common import embeddings as embeddings_module
from ogr.common.embeddings import embed_query, embed_texts, embedding_backend, get_embedding_model


class TestEmbedTexts:
    def test_empty_input_returns_empty_output(self):
        assert embed_texts([]) == []

    def test_one_vector_per_input_text(self):
        vectors = embed_texts(["hello", "world", "hello"])
        assert len(vectors) == 3
        assert all(len(v) == 1024 for v in vectors)

    def test_matches_embed_query_for_the_same_text(self):
        """Batch and single-text paths must agree — two embedding
        implementations disagreeing silently would be worse than either
        implementation being wrong the same way everywhere."""
        [batch_vector] = embed_texts(["a fixed piece of text"])
        single_vector = embed_query("a fixed piece of text")
        assert len(batch_vector) == len(single_vector)
        assert all(abs(a - b) < 1e-6 for a, b in zip(batch_vector, single_vector, strict=True))


class TestModelLoadFailure:
    def test_failed_load_is_logged_and_reported_as_fallback(self, monkeypatch, caplog):
        monkeypatch.setitem(sys.modules, "sentence_transformers", None)  # import now fails
        monkeypatch.setattr(embeddings_module, "_MODELS", {})
        with caplog.at_level(logging.ERROR, logger="ogr.common.embeddings"):
            assert embedding_backend() == "hash_fallback"
        assert "BAAI/bge-m3" in caplog.text and "NOT semantic" in caplog.text

    def test_cache_is_keyed_by_model_name(self, monkeypatch):
        class _Fake:
            def __init__(self, name):
                self.name = name

        monkeypatch.setitem(sys.modules, "sentence_transformers", type(sys)("sentence_transformers"))
        sys.modules["sentence_transformers"].SentenceTransformer = _Fake
        monkeypatch.setattr(embeddings_module, "_MODELS", {})
        assert get_embedding_model("model-a").name == "model-a"
        assert get_embedding_model("model-b").name == "model-b"
        assert get_embedding_model("model-a") is get_embedding_model("model-a")


class TestProviderChain:
    """DP-4: Cloudflare -> local -> hash, one model (bge-m3) on every tier."""

    @staticmethod
    def _creds(monkeypatch, cloudflare=True):
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct" if cloudflare else "")
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf-token" if cloudflare else "")

    def test_cloudflare_first_and_vectors_normalized(self, monkeypatch):
        self._creds(monkeypatch)
        calls = []

        def fake_post(url, payload, token, timeout_s=60.0):
            calls.append((url, payload, token))
            return {"result": {"data": [[3.0, 4.0] for _ in payload["text"]]}}

        monkeypatch.setattr(embeddings_module, "_post_json", fake_post)
        assert embed_texts(["a", "b"]) == [[0.6, 0.8], [0.6, 0.8]]
        url, payload, token = calls[0]
        assert url.endswith("/accounts/acct/ai/run/@cf/baai/bge-m3")
        assert payload == {"text": ["a", "b"]} and token == "cf-token"
        assert embedding_backend() == "cloudflare"

    def test_cloudflare_failure_falls_back_to_local_bge_m3(self, monkeypatch):
        self._creds(monkeypatch)

        def fail(*_a, **_k):
            raise OSError("down")

        class _Local:
            def encode(self, texts, normalize_embeddings, batch_size):
                return [[1.0, 0.0] for _ in texts]

        loaded = []
        monkeypatch.setattr(embeddings_module, "_post_json", fail)
        monkeypatch.setattr(
            embeddings_module, "get_embedding_model", lambda name="BAAI/bge-m3": loaded.append(name) or _Local()
        )
        assert embed_query("q") == [1.0, 0.0]
        assert loaded == ["BAAI/bge-m3"]

    def test_no_credentials_means_no_remote_call(self, monkeypatch):
        self._creds(monkeypatch, cloudflare=False)

        def fail(*_a, **_k):
            raise AssertionError("remote tier called without credentials")

        monkeypatch.setattr(embeddings_module, "_post_json", fail)
        assert len(embed_query("q")) == 1024

    def test_large_inputs_are_sent_in_batches(self, monkeypatch):
        self._creds(monkeypatch)
        sizes = []

        def fake_post(url, payload, token, timeout_s=60.0):
            sizes.append(len(payload["text"]))
            return {"result": {"data": [[1.0] for _ in payload["text"]]}}

        monkeypatch.setattr(embeddings_module, "_post_json", fake_post)
        assert len(embed_texts(["t"] * 120)) == 120
        assert sizes == [50, 50, 20]
