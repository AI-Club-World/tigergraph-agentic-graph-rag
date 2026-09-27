"""Tests for GRAPH-05's loader — no live TigerGraph, upserts are recorded
against a fake connection.
"""

from __future__ import annotations

import pytest

from ogr.graph.client import TigerGraphClient
from ogr.ingest.chunk_embed import Chunk
from ogr.ingest.infobox import parse_document
from ogr.ingest.load import load_graph


class _FakeConn:
    def __init__(self):
        self.vertices: list[tuple[str, str, dict]] = []
        self.edges: list[tuple[str, str, str, str, str, dict]] = []

    def upsertVertex(self, vtype, vid, attrs):
        self.vertices.append((vtype, vid, attrs))

    def upsertEdge(self, src_type, src_id, edge_type, tgt_type, tgt_id, attrs=None):
        self.edges.append((src_type, src_id, edge_type, tgt_type, tgt_id, attrs or {}))

    # The loader batches its upserts (one REST call per type, not per object).
    # These fan a batch back out into the same per-object records the
    # assertions below already read, so what is asserted is unchanged.
    def upsertVertices(self, vtype, vertices):
        for vid, attrs in vertices:
            self.upsertVertex(vtype, vid, attrs)
        return len(vertices)

    def upsertEdges(self, src_type, edge_type, tgt_type, edges):
        for src_id, tgt_id, attrs in edges:
            self.upsertEdge(src_type, src_id, edge_type, tgt_type, tgt_id, attrs)
        return len(edges)


CANOE = {
    "doc_id": "Q1",
    "title": "Canoeing at the 2012 Summer Olympics - Men's K-2 1000 metres",
    "url": "https://en.wikipedia.org/wiki/x",
    "text": """[Infobox Olympic event]
  event: Men's canoe sprint K-2 1,000 metres
  games: 2012 Summer
  venue: Eton Dorney
  date: 6 to 8 August
  competitors: 24
  gold: A B
  prev: 2008

Prose.
""",
}

CANOE_2008 = {
    "doc_id": "Q0",
    "title": "Canoeing at the 2008 Summer Olympics - Men's K-2 1000 metres",
    "url": "https://en.wikipedia.org/wiki/y",
    "text": """[Infobox Olympic event]
  event: Men's canoe sprint K-2 1,000 metres
  games: 2008 Summer
  venue: Some Venue
  competitors: 20
  gold: C D
  next: 2012

Prose.
""",
}

FILM = {"doc_id": "Q2", "title": "A Film", "url": "u", "text": "[Infobox film]\n  director: X\n\nProse.\n"}


def _client(conn: _FakeConn) -> TigerGraphClient:
    return TigerGraphClient(conn=conn)


class TestVertexAndEdgeCounts:
    def test_non_olympic_documents_get_a_document_vertex_only(self):
        conn = _FakeConn()
        report = load_graph(_client(conn), [parse_document(FILM)])
        assert report.documents == 1
        assert report.olympic_events == 0
        vtypes = {v[0] for v in conn.vertices}
        assert vtypes == {"Document"}

    def test_olympic_document_produces_the_full_vertex_and_edge_set(self):
        conn = _FakeConn()
        doc = parse_document(CANOE)
        report = load_graph(_client(conn), [doc])

        assert report.documents == 1
        assert report.olympic_events == 1
        assert report.games == 1
        assert report.sports == 1
        assert report.venues == 1

        vtypes = [v[0] for v in conn.vertices]
        assert vtypes.count("Document") == 1
        assert vtypes.count("OlympicEvent") == 1
        assert vtypes.count("Games") == 1
        assert vtypes.count("Sport") == 1
        assert vtypes.count("Venue") == 1

        edge_types = {e[2] for e in conn.edges}
        assert {"DESCRIBES", "AT_GAMES", "IN_SPORT", "HELD_AT"} <= edge_types

    def test_shared_games_sport_venue_vertices_are_not_duplicated(self):
        conn = _FakeConn()
        doc_a = parse_document(dict(CANOE, doc_id="Qa"))
        doc_b = parse_document(dict(CANOE, doc_id="Qb"))
        report = load_graph(_client(conn), [doc_a, doc_b])
        assert report.games == 1
        assert report.sports == 1
        assert report.venues == 1
        assert report.olympic_events == 2


class TestPrevNextResolution:
    def test_prev_year_resolves_via_sport_event_name_and_year_join(self):
        conn = _FakeConn()
        doc_2012 = parse_document(CANOE)
        doc_2008 = parse_document(CANOE_2008)
        report = load_graph(_client(conn), [doc_2012, doc_2008])

        assert report.prev_edges_resolved == 1
        assert report.next_edges_resolved == 1
        prev_edges = [e for e in conn.edges if e[2] == "PREV_EDITION"]
        assert len(prev_edges) == 1
        assert prev_edges[0][1] == doc_2012.event_id
        assert prev_edges[0][4] == doc_2008.event_id

    def test_unresolvable_prev_year_is_counted_not_silently_dropped(self):
        conn = _FakeConn()
        doc = parse_document(CANOE)  # prev=2008, but no 2008 sibling supplied
        report = load_graph(_client(conn), [doc])
        assert report.prev_edges_resolved == 0
        assert report.prev_edges_unresolved == 1
        assert not any(e[2] == "PREV_EDITION" for e in conn.edges)


class TestChunkLoading:
    def test_chunks_get_a_vertex_and_a_has_chunk_edge(self):
        conn = _FakeConn()
        chunks = [
            Chunk(chunk_id="Q1_c0", doc_id="Q1", text="hello", seq=0, token_count=1, embedding=[0.1] * 768),
        ]
        report = load_graph(_client(conn), [parse_document(CANOE)], chunks=chunks, embedding_model="embeddinggemma-300m")
        assert report.chunks == 1
        chunk_vertices = [v for v in conn.vertices if v[0] == "Chunk"]
        assert len(chunk_vertices) == 1
        assert any(e[2] == "HAS_CHUNK" and e[1] == "Q1" and e[4] == "Q1_c0" for e in conn.edges)

    def test_the_vector_goes_to_the_models_own_embedding_vertex(self):
        """The canonical Chunk carries no vector; the model's Embedding_* vertex
        (primary id = chunk_id) does, linked by HAS_EMBEDDING."""
        conn = _FakeConn()
        chunks = [
            Chunk(chunk_id="Q1_c0", doc_id="Q1", text="hello", seq=0, token_count=1, embedding=[0.1] * 768),
        ]
        load_graph(_client(conn), [parse_document(CANOE)], chunks=chunks, embedding_model="embeddinggemma-300m")
        chunk_vertex = next(v for v in conn.vertices if v[0] == "Chunk")
        assert "emb" not in chunk_vertex[2]
        assert [v for v in conn.vertices if v[0].startswith("Embedding_")] == [
            ("Embedding_EmbeddingGemma", "Q1_c0", {"emb": [0.1] * 768}),
        ]
        assert ("Chunk", "Q1_c0", "HAS_EMBEDDING", "Embedding_EmbeddingGemma", "Q1_c0", {}) in conn.edges

    def test_a_vector_of_another_models_size_is_refused(self):
        chunks = [Chunk(chunk_id="Q1_c0", doc_id="Q1", text="x", seq=0, token_count=1, embedding=[0.1] * 1024)]
        with pytest.raises(ValueError, match="1024-dim vector for EmbeddingGemma-300M"):
            load_graph(_client(_FakeConn()), [], chunks=chunks, embedding_model="embeddinggemma-300m")

    def test_unembedded_chunk_omits_the_emb_attribute(self):
        conn = _FakeConn()
        chunks = [Chunk(chunk_id="Q1_c0", doc_id="Q1", text="hello", seq=0, token_count=1)]
        load_graph(_client(conn), [parse_document(CANOE)], chunks=chunks)
        chunk_vertex = next(v for v in conn.vertices if v[0] == "Chunk")
        assert "emb" not in chunk_vertex[2]


class TestNoConnection:
    def test_raises_rather_than_silently_no_op(self):
        client = TigerGraphClient()
        client.config.tg_host = ""
        with pytest.raises(RuntimeError):
            load_graph(client, [])
