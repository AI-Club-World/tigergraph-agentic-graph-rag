"""Tests for GRAPH-01 (schema) and GRAPH-07 (query library) installers.

Full GSQL syntax validation only happens against a live TigerGraph
connection — these tests check the committed files contain the vertex/edge/
query names the rest of the codebase already depends on by name
(client.py calls `runInstalledQuery("q1_lookup")` etc., verify.py checks for
all five), and that the installers hand that exact text to `conn.gsql()`.
"""

from __future__ import annotations

from ogr.graph.client import TigerGraphClient
from ogr.graph.schema import QUERIES_DIR, QUERY_FILES, SCHEMA_PATH, install_queries, install_schema


class _FakeConn:
    def __init__(self):
        self.gsql_calls: list[str] = []

    def gsql(self, text: str) -> str:
        self.gsql_calls.append(text)
        return "ok"


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

    def test_vector_attributes_are_384_dim_cosine(self):
        text = SCHEMA_PATH.read_text(encoding="utf-8")
        assert text.count('DIMENSION=384, METRIC="COSINE"') == 2

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

    def test_q5_vtype_parameter_branches_between_chunk_and_event(self):
        text = (QUERIES_DIR / "q5_hybrid_search.gsql").read_text(encoding="utf-8")
        assert "Chunk.emb" in text
        assert "OlympicEvent.emb" in text


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

    def test_install_without_a_connection_raises_rather_than_silently_no_op(self):
        client = TigerGraphClient()  # no conn, no config host -> conn stays None
        client.config.tg_host = ""
        try:
            install_schema(client)
            raised = False
        except RuntimeError:
            raised = True
        assert raised
