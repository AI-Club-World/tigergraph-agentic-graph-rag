"""Tests for embed_texts, the batch form GRAPH-04 uses to embed 2,951 documents."""

from __future__ import annotations

from ogr.common.embeddings import embed_query, embed_texts


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
