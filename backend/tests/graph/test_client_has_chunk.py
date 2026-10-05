"""HAS_CHUNK expansion returns this document's chunks, with their text."""

from __future__ import annotations

from unittest.mock import MagicMock

from ogr.common.config import RunConfig
from ogr.graph.client import TigerGraphClient


def test_expands_only_the_requested_document_with_text():
    conn = MagicMock()
    conn.getEdges.return_value = [
        {"e_type": "HAS_CHUNK", "from_id": "Q1", "to_id": "Q1_c1"},
        {"e_type": "HAS_CHUNK", "from_id": "Q1", "to_id": "Q1_c0"},
    ]
    conn.getVerticesById.return_value = [
        {"v_id": "Q1_c1", "attributes": {"text": "second", "seq": 1}},
        {"v_id": "Q1_c0", "attributes": {"text": "first", "seq": 0}},
    ]
    client = TigerGraphClient(config=RunConfig(), conn=conn)

    chunks = client._expand_has_chunk(["Q1"])

    conn.getEdges.assert_called_once_with("Document", "Q1", "HAS_CHUNK")
    conn.getVerticesById.assert_called_once_with("Chunk", ["Q1_c1", "Q1_c0"])
    assert [(c["chunk_id"], c["text"], c["doc_id"]) for c in chunks] == [
        ("Q1_c0", "first", "Q1"), ("Q1_c1", "second", "Q1"),
    ]
    conn.getEdgesByType.assert_not_called()


def test_document_without_chunks_makes_no_vertex_call():
    conn = MagicMock()
    conn.getEdges.return_value = []
    client = TigerGraphClient(config=RunConfig(), conn=conn)
    assert client._expand_has_chunk(["Q9"]) == []
    conn.getVerticesById.assert_not_called()


def test_printed_vertex_rows_are_flattened_with_their_doc_id():
    """Q1's Document-title fallback prints vertices, not tuple rows."""
    conn = MagicMock()
    conn.runInstalledQuery.return_value = [{"results": [
        {"v_id": "Q42", "v_type": "Document", "attributes": {"title": "Sailing at the 2016 Summer Olympics"}},
    ]}]
    client = TigerGraphClient(config=RunConfig(), conn=conn)
    rows = client._run_query("q1_lookup", {"title": "Sailing at the 2016 Summer Olympics"})
    assert rows == [{"v_id": "Q42", "title": "Sailing at the 2016 Summer Olympics", "doc_id": "Q42"}]
