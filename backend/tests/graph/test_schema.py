"""Tests for GRAPH-01 (schema) and GRAPH-07 (query library) installers.

Full GSQL syntax validation only happens against a live TigerGraph
connection — these tests check the committed files contain the vertex/edge/
query names the rest of the codebase already depends on by name
(client.py calls `runInstalledQuery("q1_lookup")` etc., verify.py checks for
all five), and that the installers hand that exact text to `conn.gsql()`.
"""

from __future__ import annotations

import pytest

from ogr.graph.client import TigerGraphClient
from ogr.graph.schema import QUERIES_DIR, QUERY_FILES, SCHEMA_PATH, install_queries, install_schema


class _FakeConn:
    def __init__(self, installed=("q1_lookup", "q2_count_where", "q3_argmax", "q4_traverse", "q5_hybrid_search")):
        self.gsql_calls: list[str] = []
        self.installed = installed

    def gsql(self, text: str) -> str:
        self.gsql_calls.append(text)
        return "ok"

    def getInstalledQueries(self):
        return {f"GET /query/OlympicGraphRAG/{name}": {} for name in self.installed}


class TestSchemaFile:
    def test_every_vertex_type_is_declared(self):
        text = SCHEMA_PATH.read_text(encoding="utf-8")
        for vertex in ("Document", "OlympicEvent", "Games", "Sport", "Venue", "Chunk"):
            assert f"CREATE VERTEX {vertex}" in text

    def test_every_edge_type_is_declared_with_pinned_endpoints(self):
        text = SCHEMA_PATH.read_text(encoding="utf-8")
        for edge, frm, to in (
            ("DESCRIBES", "Document", "OlympicEvent"),
            ("AT_GAMES", "OlympicEvent", "Games"),
            ("IN_SPORT", "OlympicEvent", "Sport"),
            ("HELD_AT", "OlympicEvent", "Venue"),
            ("HAS_CHUNK", "Document", "Chunk"),
        ):
            assert f"CREATE DIRECTED EDGE {edge} (FROM {frm}, TO {to}" in text
        assert "PREV_EDITION" in text and "NEXT_EDITION" in text

    def test_each_model_has_its_own_vertex_type_index_and_edge(self):
        """schema.gsql must match common/embedding_models.py: one Embedding_*
        type per model, one HNSW index sized to that model, one HAS_EMBEDDING
        pair from Chunk — and no vector on the canonical Chunk itself."""
        import re

        from ogr.common.embedding_models import EMBEDDING_MODELS

        text = SCHEMA_PATH.read_text(encoding="utf-8")
        for model in EMBEDDING_MODELS.values():
            vt = model.vertex_type
            assert f'CREATE VERTEX {vt} (PRIMARY_ID chunk_id STRING) WITH PRIMARY_ID_AS_ATTRIBUTE="true"' in text
            assert f'ALTER VERTEX {vt} ADD VECTOR ATTRIBUTE emb(DIMENSION={model.dim}, METRIC="COSINE");' in text
            assert f"FROM Chunk, TO {vt}" in text
            assert f"DROP VERTEX {vt}" in text
        assert text.count("ADD VECTOR ATTRIBUTE") == len(EMBEDDING_MODELS)
        assert not re.search(r"ALTER VERTEX (Chunk|OlympicEvent) ADD VECTOR", text)
        assert 'WITH REVERSE_EDGE="reverse_HAS_EMBEDDING"' in text

    def test_install_is_idempotent_by_dropping_first(self):
        text = SCHEMA_PATH.read_text(encoding="utf-8")
        assert "DROP GRAPH OlympicGraphRAG" in text


class TestQueryFiles:
    def test_all_five_queries_are_present(self):
        assert len(QUERY_FILES) == 5
        for filename in QUERY_FILES:
            assert (QUERIES_DIR / filename).exists()

    def test_each_query_name_matches_what_client_py_calls(self):
        expected_names = {
            "q1_lookup", "q2_count_where", "q3_argmax", "q4_traverse", "q5_hybrid_search",
        }
        for filename in QUERY_FILES:
            text = (QUERIES_DIR / filename).read_text(encoding="utf-8")
            name = filename.removesuffix(".gsql")
            assert name in expected_names
            # CREATE OR REPLACE, so re-installing over an existing query works.
            assert f"CREATE OR REPLACE QUERY {name}(" in text
            assert f"INSTALL QUERY {name}" in text

    def test_q5_searches_each_models_own_index_and_returns_chunks(self):
        from ogr.common.embedding_models import EMBEDDING_MODELS

        text = (QUERIES_DIR / "q5_hybrid_search.gsql").read_text(encoding="utf-8")
        for model in EMBEDDING_MODELS.values():
            vt = model.vertex_type
            assert f'emb_type == "{vt}"' in text
            # Both the unfiltered and the candidate-set search use this model's index only.
            assert text.count(f"vectorSearch({{{vt}.emb}}") == 2
        assert "Chunk.emb" not in text and "OlympicEvent.emb" not in text
        assert "-(reverse_HAS_EMBEDDING>)- Chunk:c" in text
        assert "PRINT TopChunks AS top_chunks" in text and "PRINT @@distances AS distances" in text


class TestInstallers:
    def test_install_schema_sends_the_schema_file_to_gsql(self):
        conn = _FakeConn()
        client = TigerGraphClient(conn=conn)
        install_schema(client)
        assert len(conn.gsql_calls) == 1
        assert "CREATE VERTEX Document" in conn.gsql_calls[0]

    def test_install_queries_sends_all_five_in_order(self):
        conn = _FakeConn()
        client = TigerGraphClient(conn=conn)
        install_queries(client)
        assert len(conn.gsql_calls) == 5
        assert "q1_lookup" in conn.gsql_calls[0]
        assert "q5_hybrid_search" in conn.gsql_calls[4]

    def test_a_query_that_did_not_install_fails_the_install(self):
        """conn.gsql() returns a failed CREATE/INSTALL QUERY as text; the
        installer must not report success for it."""
        conn = _FakeConn(installed=("q1_lookup", "q3_argmax", "q4_traverse", "q5_hybrid_search"))
        with pytest.raises(RuntimeError, match="q2_count_where"):
            install_queries(TigerGraphClient(conn=conn))

    def test_install_without_a_connection_raises_rather_than_silently_no_op(self):
        client = TigerGraphClient()  # no conn, no config host -> conn stays None
        client.config.tg_host = ""
        try:
            install_schema(client)
            raised = False
        except RuntimeError:
            raised = True
        assert raised
