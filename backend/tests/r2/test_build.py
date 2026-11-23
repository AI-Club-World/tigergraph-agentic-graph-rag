"""build(): schema installs in order, the load writes the Round-2 layer, and no
embedding vertex is written. A fake connection records every call."""

from __future__ import annotations

import json
import re

import pytest

from ogr.common.config import RunConfig
from ogr.common.embedding_models import EMBEDDING_MODELS
from ogr.graph.client import TigerGraphClient
from ogr.graph.schema import EXPECTED_VERTEX_TYPES, R2_QUERY_FILES, has_r2_answer_schema, install_r2_answer
from ogr.r2.build import build, graph_counts, load_r2_layer

QUERY_RE = re.compile(r"INSTALL QUERY (\w+)")


class FakeConn:
    """Enough of pyTigerGraph for a build: gsql(), type/query listings, upserts, counts."""

    def __init__(self):
        self.types: list[str] = []
        self.installed: set[str] = set()
        self.gsql_calls: list[str] = []
        self.vertices: dict[str, dict[str, dict]] = {}
        self.edges: dict[str, dict[tuple[str, str], dict]] = {}
        self.upserts: list[tuple[str, str]] = []

    def getVertexTypes(self):
        return list(self.types)

    def gsql(self, text):
        self.gsql_calls.append(text)
        if "DROP GRAPH OlympicGraphRAG" in text:  # schema.gsql: reset
            self.types = sorted(EXPECTED_VERTEX_TYPES)
            self.installed.clear()
            self.vertices.clear()
            self.edges.clear()
        if "add_round2_types" in text:
            self.types += ["Dataset", "Source", "Entity", "Claim"]
        if "add_r2_answer_types" in text:
            self.types += ["Athlete", "SourceRecord"]
        self.installed.update(QUERY_RE.findall(text))
        return "ok"

    def getInstalledQueries(self):
        return {f"GET /query/OlympicGraphRAG/{n}": {} for n in self.installed}

    def upsertVertices(self, vtype, rows):
        self.upserts.append(("V", vtype))
        self.vertices.setdefault(vtype, {}).update({vid: attrs for vid, attrs in rows})
        return len(rows)

    def upsertEdges(self, src, edge, tgt, rows, **_):
        self.upserts.append(("E", edge))
        self.edges.setdefault(edge, {}).update({(s, t): a for s, t, a in rows})
        return len(rows)

    def getVertexCount(self, vtype):
        assert vtype == "*"
        return {t: len(v) for t, v in self.vertices.items()}

    def getEdgeCount(self, etype):
        assert etype == "*"
        return {t: len(v) for t, v in self.edges.items()}


def _client(conn) -> TigerGraphClient:
    return TigerGraphClient(config=RunConfig(), conn=conn)


@pytest.fixture()
def built(mini_corpus):
    conn = FakeConn()
    report = build(mini_corpus, _client(conn))
    return conn, report


def test_schema_is_installed_in_order_and_resets_only_first(built):
    conn, _ = built
    names = ["DROP GRAPH" if "DROP GRAPH" in t else "add_round2_types" if "add_round2_types" in t
             else "add_r2_answer_types" if "add_r2_answer_types" in t else None for t in conn.gsql_calls]
    assert [n for n in names if n] == ["DROP GRAPH", "add_round2_types", "add_r2_answer_types"]
    assert sum("add_r2_answer_types" in t for t in conn.gsql_calls) == 1
    assert {f.removesuffix(".gsql") for f in R2_QUERY_FILES} <= conn.installed


def test_no_embedding_vertex_or_edge_is_written(built):
    conn, _ = built
    assert not {m.vertex_type for m in EMBEDDING_MODELS.values()} & set(conn.vertices)
    assert "HAS_EMBEDDING" not in conn.edges
    assert len(conn.vertices["Chunk"]) > 0 and "HAS_CHUNK" in conn.edges


def test_round1_and_round2_vertices_are_loaded(built, mini_model):
    conn, report = built
    assert len(conn.vertices["Document"]) == len(mini_model.documents) == 17
    assert len(conn.vertices["OlympicEvent"]) == 11
    assert len(conn.vertices["Athlete"]) == len(mini_model.athletes)
    assert set(conn.vertices["SourceRecord"]) == {"SYN-A", "SYN-B"}
    assert conn.vertices["SourceRecord"]["SYN-A"]["authority"] == "operational"
    assert conn.vertices["SourceRecord"]["SYN-A"]["published_at"] == "2028-07-23T21:09:00-07:00"
    assert report.loaded_vertices["Document"] == 17 and report.loaded_vertices["Athlete"] == len(
        mini_model.athletes)


def test_won_edges_carry_medal_noc_place_and_event_key(built):
    conn, report = built
    won = conn.edges["WON"]
    assert len(won) == report.loaded_edges["WON"]
    attrs = won[("lee mu", "judo-2020-Summer-men-s-73-kg")]
    assert attrs == {"medal": "bronze", "noc": "JPN", "place": 1, "event_key": "mens 73 kg"}
    assert won[("max nu", "judo-2020-Summer-men-s-73-kg")]["place"] == 2
    assert won[("eva echo", "judo-2020-Summer-mixed-team")] == {
        "medal": "gold", "noc": "FRA", "place": 1, "event_key": "mixed team"}


def test_reports_on_edges_point_at_events_that_exist(built):
    conn, _ = built
    links = conn.edges["REPORTS_ON"]
    assert links[("SYN-A", "archery-2028-Summer-women-s-individual")] == {"score": 1.0}
    assert {e for _, e in links} <= set(conn.vertices["OlympicEvent"])


def test_entities_and_claims_with_numbers_notes_and_edges(built):
    conn, _ = built
    assert conn.vertices["Entity"]["ent:F1"] == {"name": "Splash (film)", "entity_type": "film"}
    claim = conn.vertices["Claim"]["ent:F1:budget"]
    assert (claim["value_text"], claim["value_num"], claim["has_num"], claim["value_note"]) == (
        "$8 million", 8e6, True, "USD")
    assert claim["predicate"] == "budget" and claim["subject_id"] == "ent:F1" and claim["doc_id"] == "F1"
    assert conn.vertices["Claim"]["ent:F1:director"]["has_num"] is False
    assert ("F1", "ent:F1:budget") in conn.edges["ASSERTS"]
    assert ("ent:F1:budget", "ent:F1") in conn.edges["ABOUT"]
    assert "ent:P1:predecessor1" in conn.vertices["Claim"]  # key after "jr/sr" survived


def test_graph_counts_come_from_the_server_by_type(built):
    conn, report = built
    assert report.graph["vertices"]["Athlete"] == len(conn.vertices["Athlete"])
    assert report.graph["edges"]["WON"] == len(conn.edges["WON"])
    assert graph_counts(_client(conn)) == report.graph
    assert graph_counts(TigerGraphClient(config=RunConfig(), conn=object())) == {"vertices": {}, "edges": {}}


def test_counts_file_is_written(mini_corpus, tmp_path):
    out = tmp_path / "graph_counts.json"
    report = build(mini_corpus, _client(FakeConn()), counts_path=out)
    assert json.loads(out.read_text()) == report.graph and report.graph["vertices"]["Document"] == 17


def test_install_r2_answer_installs_the_job_once_then_only_queries():
    conn = FakeConn()
    conn.types = sorted(EXPECTED_VERTEX_TYPES)
    client = _client(conn)
    assert not has_r2_answer_schema(client)
    install_r2_answer(client)
    install_r2_answer(client)
    assert sum("add_r2_answer_types" in t for t in conn.gsql_calls) == 1
    assert has_r2_answer_schema(client)


def test_a_missing_query_fails_the_install():
    conn = FakeConn()
    conn.types = sorted(EXPECTED_VERTEX_TYPES) + ["Athlete", "SourceRecord"]
    conn.gsql = lambda text: "syntax error"
    with pytest.raises(RuntimeError, match="Round-2 queries not installed"):
        install_r2_answer(_client(conn))


def test_load_is_idempotent(mini_model):
    conn = FakeConn()
    client = _client(conn)
    load_r2_layer(client, mini_model)
    first = {t: dict(v) for t, v in conn.vertices.items()}
    load_r2_layer(client, mini_model)
    assert conn.vertices == first
