"""Ceiling-protection guard tests for P1 unfiltered baseline (protects AD-9).

Source: implementation-plan-RAG.md Group 2:
- test_p1_passes_no_candidate_set
- test_index_contains_non_olympic_chunks
- test_p1_imports_no_langchain_retrievers (stop condition guard)
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from ogr.common.config import RunConfig
from ogr.graph.client import TigerGraphClient
from ogr.pipelines.p1_rag import run_p1_rag


# Query embedding is strict (never hash noise): a stand-in model serves it here.
pytestmark = pytest.mark.usefixtures("fake_embedder")


def _create_mock_mixed_corpus():
    """Returns a mock chunk collection containing both Olympic and non-Olympic documents (26.7% non-Olympic)."""
    return [
        # Olympic documents
        {"chunk_id": "Q1001_c0", "doc_id": "Q1001", "text": "Olympic sailing event details.", "doc_type": "olympic_event", "vtype": "Chunk"},
        {"chunk_id": "Q1002_c0", "doc_id": "Q1002", "text": "Olympic marathon results.", "doc_type": "olympic_event", "vtype": "Chunk"},
        {"chunk_id": "Q1003_c0", "doc_id": "Q1003", "text": "Olympic fencing competition.", "doc_type": "olympic_event", "vtype": "Chunk"},
        # Non-Olympic documents (corpus is 26.7% non-Olympic: film, officeholder, person)
        {"chunk_id": "Q5001_c0", "doc_id": "Q5001", "text": "A 1998 biographical film about sports.", "doc_type": "film", "vtype": "Chunk"},
        {"chunk_id": "Q5002_c0", "doc_id": "Q5002", "text": "Political officeholder biography.", "doc_type": "officeholder", "vtype": "Chunk"},
        {"chunk_id": "Q5003_c0", "doc_id": "Q5003", "text": "Grand Slam tennis tournament report.", "doc_type": "tennis_tournament", "vtype": "Chunk"},
    ]


def test_p1_passes_no_candidate_set():
    """Group 2 / AD-9: Asserts that P1 passes no candidate_set, applies no post-retrieval filter, and performs no re-rank."""
    corpus = _create_mock_mixed_corpus()
    config = RunConfig(k=6)
    client = TigerGraphClient(config=config, mock_chunks=corpus)

    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.content = '{"answer": "film", "explanation": "Non-Olympic film infobox retrieved."}'
    mock_response.usage_metadata = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
    mock_model.invoke.return_value = mock_response

    record = run_p1_rag(
        query="Tell me about the 1998 sports drama",
        client=client,
        config=config,
        model=mock_model,
    )

    # 1. Inspect Q5 call arguments: candidate_set MUST be None
    args = client.last_query_args
    assert args["candidate_set"] is None, (
        f"AD-9 violation: P1 must not pass a candidate_set to Q5! Got: {args['candidate_set']}"
    )

    # 2. Assert vtype is Chunk
    assert args["vtype"] == "Chunk"

    # 3. Assert k matches config.k
    assert args["k"] == 6

    # 4. Assert all retrieved chunks are retained in citations in the exact retrieved order
    # (no post-retrieval type filter, no relevance threshold, no re-ranking)
    assert record.chunks_returned == 6
    assert [c.source_id for c in record.citations] == [c["doc_id"] for c in corpus]


def test_index_contains_non_olympic_chunks():
    """Group 2 / AD-9: Asserts the chunk collection/index contains chunks from non-Olympic documents.
    This ensures ingestion did not silently type-filter P1, preserving the observable retrieval ceiling.
    """
    corpus = _create_mock_mixed_corpus()
    non_olympic_types = {"film", "officeholder", "person", "tennis_tournament"}

    non_olympic_chunks = [c for c in corpus if c.get("doc_type") in non_olympic_types]
    assert len(non_olympic_chunks) > 0, (
        "AD-9 violation: Corpus must contain non-Olympic chunks (film, officeholder, etc.) to expose P1's retrieval ceiling!"
    )

    # When queried via Q5 without type filtering, non-Olympic chunks must be reachable
    client = TigerGraphClient(config=RunConfig(k=10), mock_chunks=corpus)
    results = client.hybrid_search(query_vector=[0.0] * 384, k=10, vtype="Chunk")
    result_doc_types = {r.get("doc_type") for r in results}
    assert any(dt in non_olympic_types for dt in result_doc_types), (
        "Non-Olympic documents must be reachable by P1 Q5 hybrid_search."
    )


def test_p1_imports_no_langchain_retrievers():
    """Stop condition guard: Asserts p1_rag.py does not import any LangChain retriever wrappers or rerankers.
    Convenience retrievers (ContextualCompressionRetriever, MultiQueryRetriever, EnsembleRetriever)
    silently convert the honest baseline into a tuned one, violating AD-9.
    """
    p1_file = Path(__file__).resolve().parents[2] / "src" / "ogr" / "pipelines" / "p1_rag.py"
    assert p1_file.exists(), f"p1_rag.py not found at {p1_file}"

    tree = ast.parse(p1_file.read_text(encoding="utf-8"))

    forbidden_names = {
        "ContextualCompressionRetriever",
        "MultiQueryRetriever",
        "EnsembleRetriever",
        "BaseRetriever",
        "VectorStoreRetriever",
        "BM25Retriever",
        "TFIDFRetriever",
        "CohereRerank",
        "CrossEncoder",
    }

    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_names.add(node.module)
            for alias in node.names:
                imported_names.add(alias.name)

    violating_imports = forbidden_names.intersection(imported_names)
    assert not violating_imports, (
        f"AD-9 Stop Condition Violated: p1_rag.py must NOT import any retriever wrappers: {violating_imports}"
    )
