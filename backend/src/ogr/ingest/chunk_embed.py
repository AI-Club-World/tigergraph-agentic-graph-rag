"""Chunk + embed the corpus (GRAPH-04).

Source spec: TECHNICAL-SPEC §2.1 (Chunk vertex), §11 (chunk_tokens=300,
chunk_overlap=50, fixed before the first run) · Plan: implementation-plan-GRAPH.md
Group 2 · Requirement: AD-6, AD-9 · Gate: G1

Chunks **all 2,951 documents, not only the Olympic subset**. This is
load-bearing for AD-9: if only parsed Olympic docs enter the vector index, P1
is implicitly type-filtered by ingestion and the unfiltered-baseline argument
collapses (`test_index_contains_non_olympic_chunks` already guards the
consuming side of this).

"Token" in `chunk_tokens`/`chunk_overlap` means a whitespace-split word here,
not a model-specific subword unit. Ingestion must stay deterministic and
dependency-free — no tokenizer call per document — and a word-count window
is the standard cheap proxy for chunk sizing. This is a different
approximation from the corpus's own `approx_tokens` field (chars/4), which is
a document-level accounting number, not a chunking rule; the two are not
expected to agree exactly.

Embedding is bge-m3 (1024-dim, COSINE) via `common/embeddings.py` — an
embedding model, no LLM call (AD-6). Loading the resulting
chunks into TigerGraph is GRAPH-05's job, not this module's; this module's
output is a plain list of `Chunk` objects a caller can embed and hand to a
loader.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ogr.common.embeddings import embed_texts

__all__ = ["Chunk", "chunk_text", "chunk_document", "embed_chunks", "chunk_and_embed_corpus"]


@dataclass
class Chunk:
    """One Chunk vertex's worth of data (TECHNICAL-SPEC §2.1)."""

    chunk_id: str
    doc_id: str
    text: str
    seq: int
    token_count: int
    embedding: list[float] = field(default_factory=list)


def chunk_text(text: str, chunk_tokens: int = 300, chunk_overlap: int = 50) -> list[str]:
    """Split into overlapping windows of `chunk_tokens` words, stepping by
    `chunk_tokens - chunk_overlap` words each time. Empty text yields no
    chunks — there is nothing to embed and nothing to cite.
    """
    if chunk_overlap >= chunk_tokens:
        raise ValueError("chunk_overlap must be smaller than chunk_tokens")

    words = text.split()
    if not words:
        return []

    step = chunk_tokens - chunk_overlap
    pieces: list[str] = []
    start = 0
    while start < len(words):
        window = words[start : start + chunk_tokens]
        pieces.append(" ".join(window))
        if start + chunk_tokens >= len(words):
            break
        start += step
    return pieces


def chunk_document(
    doc_id: str, text: str, chunk_tokens: int = 300, chunk_overlap: int = 50
) -> list[Chunk]:
    """Chunk one document into Chunk records, unembedded (`embedding=[]`)."""
    pieces = chunk_text(text, chunk_tokens, chunk_overlap)
    return [
        Chunk(
            chunk_id=f"{doc_id}_c{i}",
            doc_id=doc_id,
            text=piece,
            seq=i,
            token_count=len(piece.split()),
        )
        for i, piece in enumerate(pieces)
    ]


def embed_chunks(chunks: list[Chunk]) -> None:
    """Embed every chunk's text in place, as one batched model call."""
    if not chunks:
        return
    vectors = embed_texts([chunk.text for chunk in chunks])
    for chunk, vector in zip(chunks, vectors, strict=True):
        chunk.embedding = vector


def chunk_and_embed_corpus(
    corpus_path: str | Path,
    chunk_tokens: int = 300,
    chunk_overlap: int = 50,
    embed: bool = True,
) -> list[Chunk]:
    """Chunk (and, by default, embed) every document in a corpus JSONL file."""
    all_chunks: list[Chunk] = []
    with open(corpus_path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            doc_id = record.get("doc_id", "")
            text = record.get("text", "") or ""
            all_chunks.extend(chunk_document(doc_id, text, chunk_tokens, chunk_overlap))

    if embed:
        embed_chunks(all_chunks)
    return all_chunks
