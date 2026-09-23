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
        assert all(len(v) == 384 for v in vectors)

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
            assert embedding_backend("some/model") == "hash_fallback"
        assert "some/model" in caplog.text and "NOT semantic" in caplog.text

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
