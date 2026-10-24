"""Round-2 fact layer: schema job, queries, client and loader (gate G1).

No live TigerGraph: the GSQL is checked for the names the code relies on
and for never dropping the graph; the loader runs against a fake
connection. A real install is the first true syntax check."""

from __future__ import annotations

import json

from ogr.common.config import RunConfig
from ogr.datasets import detect_adapter
from ogr.graph.client import TigerGraphClient
from ogr.graph.schema import (
    QUERIES_DIR,
    QUERY_FILES,
    ROUND2_QUERY_FILES,
    ROUND2_SCHEMA_PATH,
    has_round2_schema,
    install_round2,
)
from ogr.ingest.load_claims import load_claims, load_claims_for_build
from tests.datasets.test_adapters import TITLE, TestBlockRecords
from tests.ingest.test_infobox import CANOE


class FakeConn:
    def __init__(self, types=("Document", "Chunk", "OlympicEvent"), claim_rows=()):
        self.types = list(types)
        self.vertices: dict[str, dict[str, dict]] = {}
        self.edges: list[tuple[str, str, str, str, str, dict]] = []
        self.gsql_calls: list[str] = []
        self.installed: set[str] = set()
        self.claim_rows = list(claim_rows)
        self.queries: list[tuple[str, dict]] = []

    def getVertexTypes(self):
        return self.types

    def gsql(self, text):
        self.gsql_calls.append(text)
        if "add_round2_types" in text:
            self.types += ["Dataset", "Source", "Entity", "Claim"]
        for name in ("q5s_search", "q6_claims"):
            if f"INSTALL QUERY {name}" in text:
                self.installed.add(name)
        return "ok"

    def getInstalledQueries(self):
        return {f"GET /query/OlympicGraphRAG/{n}": {} for n in self.installed}

    def upsertVertices(self, vtype, rows):
        self.vertices.setdefault(vtype, {}).update({vid: attrs for vid, attrs in rows})
        return len(rows)

    def upsertEdges(self, src, edge, tgt, rows, **_):
        self.edges += [(src, s, edge, tgt, t, a) for s, t, a in rows]
        return len(rows)

    def runInstalledQuery(self, name, params):
        self.queries.append((name, params))
        if name == "q6_claims":
            return [{"results": [r for r in self.claim_rows if r["subject_id"] in params["subject_ids"]]}]
        return [{"top_chunks": [], "distances": {}}]

    def getVertices(self, vtype):
        return [{"v_id": k, "attributes": v} for k, v in self.vertices.get(vtype, {}).items()]


def _client(conn) -> TigerGraphClient:
    return TigerGraphClient(config=RunConfig(), conn=conn)


class TestFiles:
    def test_the_job_adds_types_and_never_drops_the_graph(self):
        text = ROUND2_SCHEMA_PATH.read_text(encoding="utf-8")
        assert "DROP GRAPH" not in text and "DROP VERTEX" not in text and "DROP EDGE" not in text
        assert "CREATE SCHEMA_CHANGE JOB add_round2_types FOR GRAPH OlympicGraphRAG" in text
        for vtype in ("Dataset", "Source", "Entity", "Claim"):
            assert f"ADD VERTEX {vtype} (" in text
        for edge in ("IN_DATASET", "ASSERTS", "FROM_SOURCE", "ABOUT", "SUPERSEDES", "CONTRADICTS"):
            assert f"EDGE {edge} (" in text
        # Existing Round-1 types are only referenced, never altered.
        assert "ALTER VERTEX" not in text

    def test_round1_queries_are_untouched_and_round2_queries_are_separate(self):
        assert set(QUERY_FILES).isdisjoint(ROUND2_QUERY_FILES)
        q6 = (QUERIES_DIR / "q6_claims.gsql").read_text(encoding="utf-8")
        assert "CREATE OR REPLACE QUERY q6_claims(" in q6 and "INSTALL QUERY q6_claims" in q6
        q5s = (QUERIES_DIR / "q5s_search.gsql").read_text(encoding="utf-8")
        from ogr.common.embedding_models import EMBEDDING_MODELS

        for model in EMBEDDING_MODELS.values():
            assert f'emb_type == "{model.vertex_type}"' in q5s
        assert "reverse_IN_DATASET" in q5s


class TestInstall:
    def test_installs_the_types_once_then_only_the_queries(self):
        conn = FakeConn()
        client = _client(conn)
        assert not has_round2_schema(client)
        install_round2(client)
        assert has_round2_schema(client)
        assert sum("add_round2_types" in t for t in conn.gsql_calls) == 1
        install_round2(client)
        assert sum("add_round2_types" in t for t in conn.gsql_calls) == 1
        assert conn.installed == {"q5s_search", "q6_claims"}


def _row(claim_id, subject, value, dataset="corpus", **extra):
    return {"claim_id": claim_id, "dataset_id": dataset, "doc_id": "Q1", "subject_id": subject,
            "subject_name": TITLE, "predicate": "gold", "value_text": value, "value_num": 0.0,
            "has_num": False, "valid_from": "", "valid_to": "", "observed_at": "", "source_id": "src:wikipedia.org",
            "extraction_conf": 1.0, "hedged": False, "hedge_terms": "", "revision": False, **extra}


class TestClient:
    def test_claims_come_back_as_records(self):
        conn = FakeConn(claim_rows=[_row("c1", "e1", "A", has_num=True, value_num=24.0, hedge_terms="about; reportedly")])
        [claim] = _client(conn).claims(["e1"], "gold", ["corpus"])
        assert claim.value_num == 24.0 and claim.hedge_terms == ["about", "reportedly"]
        assert claim.observed_at is None and claim.valid_from is None
        assert conn.queries[-1] == ("q6_claims", {"subject_ids": ["e1"], "predicate": "gold", "dataset_ids": ["corpus"]})

    def test_no_subjects_no_query(self):
        conn = FakeConn()
        assert _client(conn).claims([]) == [] and conn.queries == []

    def test_a_dataset_scope_uses_q5s_and_no_scope_keeps_q5(self):
        conn = FakeConn()
        client = _client(conn)
        client.hybrid_search([0.0] * 1024, k=3, embedding_model="bge-large-en-v1.5")
        client.hybrid_search([0.0] * 1024, k=3, embedding_model="bge-large-en-v1.5", dataset_ids=["corpus"])
        assert [q for q, _ in conn.queries] == ["q5_hybrid_search", "q5s_search"]
        assert conn.queries[1][1]["dataset_ids"] == ["corpus"]


class TestLoader:
    def test_block_records_load_the_fact_layer_against_round1_claims(self, tmp_path):
        from ogr.ingest.infobox import event_id_for_title

        event = event_id_for_title(TITLE)
        path = tmp_path / "r2.jsonl"
        path.write_text(json.dumps(TestBlockRecords.RECORD), encoding="utf-8")
        # The Round-1 page already says someone else won gold.
        conn = FakeConn(types=["Dataset", "Source", "Entity", "Claim"],
                        claim_rows=[_row("r1", event, "Rudolf Dombi; Roland Kokeny")])
        report = load_claims(_client(conn), path, "r2", adapter="block_records",
                             chunk_ids=["r2-1_c0"], event_ids=[event])
        assert (report.claims, report.sources, report.supersedes) == (2, 1, 1)
        assert set(conn.vertices) == {"Dataset", "Source", "Claim"}  # every subject is an event
        assert conn.vertices["Source"]["src:ioc"]["has_prior"] is True
        kinds = {(e[2], e[3]) for e in conn.edges}
        assert ("IN_DATASET", "Dataset") in kinds and ("ABOUT", "OlympicEvent") in kinds
        sup = [e for e in conn.edges if e[2] == "SUPERSEDES"]
        assert sup and sup[0][4] == "r1" and "revision" in sup[0][5]["reason"]
        assert ("Chunk", "r2-1_c0", "IN_DATASET", "Dataset", "r2", {}) in conn.edges
        # Never a Round-1 vertex type.
        assert not {"OlympicEvent", "Document", "Chunk"} & set(conn.vertices)

    def test_a_claim_about_an_unknown_event_gets_no_about_edge(self, tmp_path):
        path = tmp_path / "c.jsonl"
        path.write_text(json.dumps(CANOE), encoding="utf-8")
        conn = FakeConn(types=["Dataset", "Source", "Entity", "Claim"])
        load_claims(_client(conn), path, "corpus", adapter="olympic", event_ids=[])
        assert not [e for e in conn.edges if e[2] == "ABOUT"]

    def test_a_build_loads_claims_only_on_a_round2_graph(self, tmp_path):
        path = tmp_path / "corpus.jsonl"
        path.write_text(json.dumps(CANOE), encoding="utf-8")
        assert load_claims_for_build(_client(FakeConn()), path, "corpus", [], []) is None
        note = load_claims_for_build(
            _client(FakeConn(types=["Dataset", "Source", "Entity", "Claim"])), path, "corpus", [], []
        )
        assert note == "9 claims, 0 SUPERSEDES, 0 CONTRADICTS"

    def test_adapter_detection(self, tmp_path):
        r1 = tmp_path / "corpus.jsonl"
        r1.write_text(json.dumps(CANOE), encoding="utf-8")
        r2 = tmp_path / "r2.jsonl"
        r2.write_text(json.dumps(TestBlockRecords.RECORD), encoding="utf-8")
        assert (detect_adapter(r1), detect_adapter(r2)) == ("olympic", "block_records")
