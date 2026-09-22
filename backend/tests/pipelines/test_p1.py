"""Unit tests for P1 RAG pipeline conformance and behavior.

Source: implementation-plan-RAG.md Verification Plan Group 1:
- test_p1_conforms_to_pipeline_record
- test_p1_citations_resolve_to_doc_ids
- test_p1_tokens_captured_not_estimated
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from ogr.common.config import RunConfig
from ogr.common.contracts import Citation, PipelineRecord, TokenUsage
from ogr.graph.client import TigerGraphClient
from ogr.pipelines.p1_rag import run_p1_rag


def _create_mock_chunks(count: int = 10):
    """Creates a set of mock chunks with distinct parent doc_ids and chunk_ids."""
    chunks = []
    for i in range(count):
        doc_id = f"Q{1000 + i}"
        chunks.append({
            "chunk_id": f"{doc_id}_c{i % 3}",
            "doc_id": doc_id,
            "text": f"Context excerpt {i} regarding Olympic competition details for document {doc_id}.",
            "score": 0.95 - (i * 0.05),
            "vtype": "Chunk",
        })
    return chunks


def _create_mock_llm(answer_text="26", explanation_text="There were 26 nations competing based on the official event report."):
    """Creates a mock LangChain chat model returning valid CORE-02 JSON and token usage."""
    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.content = (
        f'{{"answer": "{answer_text}", "explanation": "{explanation_text}"}}'
    )
    mock_response.usage_metadata = {
        "input_tokens": 142,
        "output_tokens": 28,
        "total_tokens": 170,
    }
    mock_model.invoke.return_value = mock_response
    return mock_model


def test_p1_conforms_to_pipeline_record():
    """Group 1: Asserts that P1 output conforms strictly to the shared PipelineRecord contract."""
    mock_chunks = _create_mock_chunks(10)
    config = RunConfig(k=10)
    client = TigerGraphClient(config=config, mock_chunks=mock_chunks)
    model = _create_mock_llm("26", "26 nations competed in Sailing at the 2016 Olympics.")

    record = run_p1_rag(
        query="How many nations competed in Sailing at the 2016 Summer Olympics – Women's RS:X?",
        client=client,
        config=config,
        model=model,
    )

    assert isinstance(record, PipelineRecord)
    assert record.pipeline == "rag"
    assert record.answer == "26"
    assert "26 nations" in record.explanation
    assert record.status == "done"
    assert record.error_detail is None

    # Conform to trace field specifications (null for P1)
    assert record.trace is None
    assert record.strategy_changed is None
    assert record.stop_reason is None

    # Counts populated per guidebook requirement
    assert record.chunks_returned == 10
    assert record.citations_count == 10
    assert len(record.citations) == 10


def test_p1_citations_resolve_to_doc_ids():
    """Group 1: Asserts that citations resolve source_id to parent doc_id (QID) and retain chunk_id."""
    mock_chunks = _create_mock_chunks(10)
    config = RunConfig(k=10)
    client = TigerGraphClient(config=config, mock_chunks=mock_chunks)
    model = _create_mock_llm("26", "Explanation text.")

    record = run_p1_rag(
        query="Sample question?",
        client=client,
        config=config,
        model=model,
    )

    for i, citation in enumerate(record.citations):
        expected_doc_id = f"Q{1000 + i}"
        expected_chunk_id = f"{expected_doc_id}_c{i % 3}"

        assert isinstance(citation, Citation)
        assert citation.source_id == expected_doc_id, (
            f"Citation source_id must be parent doc_id {expected_doc_id}, got {citation.source_id}"
        )
        assert citation.chunk_id == expected_chunk_id, (
            f"Citation chunk_id must retain display id {expected_chunk_id}, got {citation.chunk_id}"
        )
        assert citation.ref_type == "chunk"


def test_p1_tokens_captured_not_estimated():
    """Group 1: Asserts that token usage is captured at the provider/invocation layer, not estimated post-hoc."""
    mock_chunks = _create_mock_chunks(5)
    config = RunConfig(k=5)
    client = TigerGraphClient(config=config, mock_chunks=mock_chunks)
    model = _create_mock_llm("Answer", "Explanation")

    record = run_p1_rag(
        query="Test query?",
        client=client,
        config=config,
        model=model,
    )

    # Provider tokens captured from usage_metadata
    assert record.tokens.input == 142
    assert record.tokens.output == 28
    assert record.tokens.total == 170
    assert record.token_source == "provider"
    assert record.latency_ms > 0.0
