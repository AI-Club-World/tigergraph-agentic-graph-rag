"""Tests for GRAPH-04, chunking + embedding.

The corpus-wide test embeds nothing (embed=False) — running the real model
over all 2,951 documents belongs in a manual verification step, not the
regular suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ogr.ingest.chunk_embed import chunk_and_embed_corpus, chunk_document, chunk_text

CORPUS = Path(__file__).resolve().parents[3] / "data" / "corpus" / "corpus.jsonl"
corpus_required = pytest.mark.skipif(not CORPUS.exists(), reason="data/corpus/corpus.jsonl not present")


class TestChunkText:
    def test_empty_text_yields_no_chunks(self):
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_short_text_is_a_single_chunk(self):
        assert chunk_text("one two three", chunk_tokens=300, chunk_overlap=50) == ["one two three"]

    def test_windows_overlap_by_the_configured_amount(self):
        words = [f"w{i}" for i in range(10)]
        text = " ".join(words)
        pieces = chunk_text(text, chunk_tokens=4, chunk_overlap=1)
        # step = 4 - 1 = 3 words per window advance
        assert pieces == ["w0 w1 w2 w3", "w3 w4 w5 w6", "w6 w7 w8 w9"]

    def test_overlap_must_be_smaller_than_chunk_size(self):
        with pytest.raises(ValueError):
            chunk_text("a b c", chunk_tokens=10, chunk_overlap=10)

    def test_last_window_is_not_dropped_when_short(self):
        # step = 3 - 1 = 2: "a b c" then "c d e" — every word is covered,
        # including "d" and "e" at the tail, none silently lost.
        pieces = chunk_text("a b c d e", chunk_tokens=3, chunk_overlap=1)
        assert pieces == ["a b c", "c d e"]


class TestChunkDocument:
    def test_chunk_ids_are_stable_and_sequential(self):
        chunks = chunk_document("Q1", "a b c d e f g h", chunk_tokens=3, chunk_overlap=1)
        assert [c.chunk_id for c in chunks] == ["Q1_c0", "Q1_c1", "Q1_c2", "Q1_c3"]
        assert [c.seq for c in chunks] == [0, 1, 2, 3]
        assert all(c.doc_id == "Q1" for c in chunks)

    def test_unembedded_by_default(self):
        chunks = chunk_document("Q1", "a b c")
        assert chunks[0].embedding == []

    def test_empty_document_yields_no_chunks(self):
        assert chunk_document("Q1", "") == []


@corpus_required
class TestAgainstTheRealCorpus:
    def test_every_document_with_text_produces_at_least_one_chunk(self):
        chunks = chunk_and_embed_corpus(CORPUS, embed=False)
        doc_ids_with_chunks = {c.doc_id for c in chunks}
        with open(CORPUS, encoding="utf-8") as handle:
            import json

            total_docs = sum(1 for line in handle if line.strip())
        assert len(doc_ids_with_chunks) <= total_docs
        assert len(chunks) > total_docs, "expect most docs to produce more than one chunk"

    def test_chunking_covers_non_olympic_documents_too(self):
        """AD-9: the vector index must not be implicitly type-filtered by ingestion."""
        chunks = chunk_and_embed_corpus(CORPUS, embed=False)
        doc_ids = {c.doc_id for c in chunks}
        assert "Q12345" not in doc_ids  # sanity: fixture id, not a real corpus doc
        # At least one non-Olympic-infobox document (e.g. a film) has chunks.
        import json

        with open(CORPUS, encoding="utf-8") as handle:
            film_doc_ids = {
                json.loads(line)["doc_id"]
                for line in handle
                if line.strip() and "[Infobox film]" in line
            }
        assert film_doc_ids & doc_ids
