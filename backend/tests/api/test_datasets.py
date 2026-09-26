"""Multi-dataset build: choose/upload a dataset, rebuild-or-cancel, keep others."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import ogr.api.main as api_main
from ogr.api.security import get_config
from ogr.common.config import RunConfig
from ogr.ingest.registry import DatasetRegistry

HEADERS = {"X-API-Key": "k"}
DOC = json.dumps({"doc_id": "Q1", "title": "Sailing at the 2016 Summer Olympics", "text": "Sailing text."})


@pytest.fixture
def env(monkeypatch, tmp_path):
    corpora = tmp_path / "corpus"
    corpora.mkdir()
    (corpora / "olympics.jsonl").write_text(DOC + "\n", encoding="utf-8")
    monkeypatch.setattr(api_main, "CORPUS_DIR", corpora)
    monkeypatch.setattr(api_main, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(api_main, "_get_client", lambda config: SimpleNamespace(conn=None, _ensure_connection=lambda: None))
    api_main._builds.clear()
    previous = api_main.app.dependency_overrides.get(get_config)
    api_main.app.dependency_overrides[get_config] = lambda: RunConfig(ogr_api_key="k", embedding_dim=1024)
    with TestClient(api_main.app) as c:
        yield SimpleNamespace(client=c, corpora=corpora, registry=DatasetRegistry(tmp_path / "out" / "datasets.json"))
    if previous is None:
        api_main.app.dependency_overrides.pop(get_config, None)
    else:
        api_main.app.dependency_overrides[get_config] = previous


def test_lists_corpora_with_build_state(env):
    env.registry.reset("@cf/baai/bge-m3", 1024)
    env.registry.record("olympics", {"doc_ids": ["Q1"]}, {"documents": 1, "events": 0, "chunks": 1}, 10)
    body = env.client.get("/corpora", headers=HEADERS).json()
    [row] = body["corpora"]
    assert row["name"] == "olympics" and row["documents"] == 1
    assert row["built"]["documents"] == 1 and "doc_ids" not in row["built"]


def test_upload_validates_and_stores_a_new_dataset(env):
    ok = env.client.post("/corpora/finance", headers=HEADERS, content=(DOC + "\n" + DOC).encode())
    assert ok.status_code == 201 and ok.json()["documents"] == 2
    assert (env.corpora / "finance.jsonl").exists()
    assert env.client.post("/corpora/finance", headers=HEADERS, content=DOC.encode()).status_code == 409
    bad = env.client.post("/corpora/broken", headers=HEADERS, content=b'{"title": "no id"}\n')
    assert bad.status_code == 400 and "Line 1" in bad.json()["detail"]
    assert env.client.post("/corpora/../evil", headers=HEADERS, content=DOC.encode()).status_code in (400, 404)


def test_same_dataset_twice_asks_to_rebuild_or_cancel(env):
    env.registry.reset("@cf/baai/bge-m3", 1024)
    env.registry.record("olympics", {"doc_ids": ["Q1"]}, {"documents": 1, "events": 0, "chunks": 1}, 10)
    response = env.client.post("/build", headers=HEADERS, json={"dataset": "olympics"})
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "already_built" and "Rebuild" in detail["message"]
    assert env.client.post("/build", headers=HEADERS, json={"dataset": "olympics", "rebuild": True}).status_code == 202


def test_graph_with_another_embedding_size_requires_a_reset(env):
    env.registry.reset("BAAI/bge-small-en-v1.5", 384)
    response = env.client.post("/build", headers=HEADERS, json={"dataset": "olympics"})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "reset_required"
    assert env.client.post("/build", headers=HEADERS, json={"dataset": "olympics", "reset": True}).status_code == 202


def test_untracked_graph_with_data_requires_a_reset(env, monkeypatch):
    conn = MagicMock()
    conn.getVertexCount.return_value = 2951
    monkeypatch.setattr(api_main, "_get_client", lambda config: SimpleNamespace(conn=conn, _ensure_connection=lambda: None))
    response = env.client.post("/build", headers=HEADERS, json={"dataset": "olympics"})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "reset_required"


def test_rebuild_removes_only_ids_no_other_dataset_wrote(tmp_path):
    registry = DatasetRegistry(tmp_path / "datasets.json")
    registry.reset("@cf/baai/bge-m3", 1024)
    registry.record("a", {"doc_ids": ["Q1", "Q2"], "chunk_ids": ["Q1_c0", "Q2_c0"]}, {}, 1)
    registry.record("b", {"doc_ids": ["Q2", "Q3"], "chunk_ids": ["Q2_c0"]}, {}, 1)
    removable = registry.removable_ids("a")
    assert removable["Document"] == ["Q1"] and removable["Chunk"] == ["Q1_c0"]


def test_delete_vertices_batches_by_type():
    conn = MagicMock()
    conn.delVerticesById.return_value = 2
    removed = api_main._delete_vertices(SimpleNamespace(conn=conn), {"Chunk": ["a", "b", "c"]}, batch=2)
    assert removed == 4
    assert [c.args for c in conn.delVerticesById.call_args_list] == [("Chunk", ["a", "b"]), ("Chunk", ["c"])]


def _run_build_stream(client, body):
    accepted = client.post("/build", headers=HEADERS, json=body)
    assert accepted.status_code == 202, accepted.text
    ids = accepted.json()
    with client.stream("GET", f"/build/{ids['build_id']}/stream", params={"token": ids["stream_token"]}) as r:
        lines = list(r.iter_lines())
    return [json.loads(lines[i + 1][len("data: "):]) for i, line in enumerate(lines) if line == "event: build"]


def test_second_dataset_keeps_the_first_and_rebuild_replaces_its_own(env, monkeypatch):
    import ogr.graph.schema as schema
    import ogr.graph.vector_status as vector_status
    import ogr.ingest.chunk_embed as chunk_embed

    calls = []
    conn = MagicMock()
    conn.getVertexCount.return_value = 0
    conn.delVerticesById.side_effect = lambda vtype, ids: calls.append(("delete", vtype, list(ids))) or len(ids)
    monkeypatch.setattr(api_main, "_get_client", lambda config: SimpleNamespace(
        conn=conn, _ensure_connection=lambda: None, _vocab_cache={}))
    monkeypatch.setattr(schema, "install_schema", lambda client: calls.append(("install_schema",)))
    monkeypatch.setattr(schema, "install_queries", lambda client: calls.append(("install_queries",)))
    monkeypatch.setattr(vector_status, "wait_until_ready", lambda *a, **k: {})
    monkeypatch.setattr(chunk_embed, "embed_chunks", lambda chunks: None)
    monkeypatch.setattr(api_main, "load_graph", lambda client, docs, chunks: SimpleNamespace(
        documents=len(docs), olympic_events=0, games=0, sports=0, venues=0, chunks=len(chunks),
        edges=len(chunks), prev_edges_resolved=0, next_edges_resolved=0))
    (env.corpora / "finance.jsonl").write_text(
        json.dumps({"doc_id": "F1", "title": "Bonds", "text": "Bond yields rose."}) + "\n", encoding="utf-8")

    first = _run_build_stream(env.client, {"dataset": "olympics"})
    assert first[-1]["status"] == "ready" and ("install_schema",) in calls

    calls.clear()
    second = _run_build_stream(env.client, {"dataset": "finance"})
    assert second[-1]["status"] == "ready"
    assert ("install_schema",) not in calls, "a second dataset must not drop the graph"
    assert set(env.registry.read()["datasets"]) == {"olympics", "finance"}

    calls.clear()
    again = _run_build_stream(env.client, {"dataset": "olympics", "rebuild": True})
    assert again[-1]["status"] == "ready"
    assert ("delete", "Document", ["Q1"]) in calls
    assert any(e["stage"] == "remove_previous" and e["status"] == "done" for e in again)
    assert set(env.registry.read()["datasets"]) == {"olympics", "finance"}


def test_stages_are_scoped_to_the_pipelines_they_serve(env, monkeypatch):
    """RAG: chunks/vectors only; GraphRAG: graph only, ready before the vector
    index; Agentic: both. Counts are per part, and restorable after a reload."""
    import ogr.graph.schema as schema
    import ogr.graph.vector_status as vector_status
    import ogr.ingest.chunk_embed as chunk_embed

    conn = MagicMock()
    conn.getVertexCount.return_value = 0
    monkeypatch.setattr(api_main, "_get_client", lambda config: SimpleNamespace(
        conn=conn, _ensure_connection=lambda: None, _vocab_cache={}))
    monkeypatch.setattr(schema, "install_schema", lambda client: None)
    monkeypatch.setattr(schema, "install_queries", lambda client: None)
    monkeypatch.setattr(vector_status, "wait_until_ready", lambda *a, **k: {})
    monkeypatch.setattr(chunk_embed, "embed_chunks", lambda chunks: None)
    monkeypatch.setattr(api_main, "load_graph", lambda client, docs, chunks: SimpleNamespace(
        documents=1, olympic_events=1, games=1, sports=1, venues=1, chunks=4,
        edges=4 + 6, prev_edges_resolved=0, next_edges_resolved=0))

    events = _run_build_stream(env.client, {"dataset": "olympics"})
    done = {e["stage"]: e for e in events if e["status"] == "done"}
    assert "rag" not in done["load_vertices"]["pipeline_affected"]
    assert done["load_vertices"]["items_done"] == 5 and done["load_edges"]["items_done"] == 6
    assert "graphrag" not in done["embed_chunks"]["pipeline_affected"]
    assert done["load_chunks"]["pipeline_affected"] == ["rag", "agentic_graphrag"]
    readies = [(i, e["pipeline_affected"]) for i, e in enumerate(events) if e["status"] == "ready"]
    vector_start = next(i for i, e in enumerate(events) if e["stage"] == "vector_index")
    assert readies[0][1] == ["graphrag"] and readies[0][0] < vector_start
    assert readies[-1][1] == ["rag", "agentic_graphrag"]

    built = env.client.get("/corpora", headers=HEADERS).json()["graph"]["datasets"]["olympics"]
    assert built["entities"] == 5 and built["relationships"] == 6 and built["vectors"] == 4
    assert set(built["ready_ms"]) == {"rag", "graphrag", "agentic_graphrag"}


def test_current_build_can_be_picked_up_after_a_reload(env, monkeypatch):
    api_main._builds.clear()
    assert env.client.get("/build/current", headers=HEADERS).json() == {"build": None}
    events = _run_build_stream(env.client, {"dataset": "olympics"})  # fails at schema (no TigerGraph)
    current = env.client.get("/build/current", headers=HEADERS).json()["build"]
    assert current["dataset"] == "olympics" and current["running"] is False
    assert [e["stage"] for e in current["events"]] == [e["stage"] for e in events]
