"""Embedding switching over HTTP: server-side refusals (whatever the UI
shows) and the query-time block (config-docs/EMBEDDING-SWITCHING.md)."""

from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

import ogr.api.main as api_main
from ogr.api.security import get_config
from ogr.common.embedding_models import EMBEDDING_MODELS
from ogr.graph.client import TigerGraphClient
from tests.conftest import make_embeddings_ready
from tests.graph.fake_tigergraph import seeded

HEADERS = {"X-API-Key": "k"}
QWEN, GTE, BGE = "qwen3-embedding-0.6b", "gte-large-en-v1.5", "bge-large-en-v1.5"


@pytest.fixture
def client(monkeypatch):
    # The real override chain (store's active model applies), plus an API key.
    api_main.app.dependency_overrides[get_config] = lambda: api_main._get_config_with_overrides().model_copy(
        update={"ogr_api_key": "k"}
    )
    api_main._builds.clear()
    api_main._queries.clear()
    api_main._embedding_job["task"] = None
    started = []
    monkeypatch.setattr(api_main, "_run_query", lambda qid, q, queue, config: started.append(config) or _noop())
    with TestClient(api_main.app) as c:
        c.started = started
        yield c
    api_main.app.dependency_overrides.clear()
    api_main._builds.clear()


async def _noop():
    return None


class _Running:
    def done(self):
        return False


def _ready(*keys, active=BGE):
    store = make_embeddings_ready(api_main.OUT_DIR, model_key=active)
    for key in keys:
        store.add_covered(key, ["Q1_c0"])
    return store


class TestOverview:
    def test_lists_every_model_with_its_state_and_the_cap(self, client):
        _ready(QWEN)
        body = client.get("/embeddings", headers=HEADERS).json()
        states = {m["key"]: m["state"] for m in body["models"]}
        assert states == {
            QWEN: "complete", "embeddinggemma-300m": "not_stored", GTE: "not_stored",
            "mxbai-embed-large-v1": "not_stored", BGE: "complete",
        }
        assert body["active"] == BGE and body["cap"] == 2 and body["stored"] == [QWEN, BGE]
        assert body["switch_disabled_reason"] is None

    def test_a_job_left_running_by_a_dead_process_reads_as_resumable(self, client):
        store = _ready()
        store.begin_switch(GTE, "parallel", None, {"Q1_c0"}, BGE)
        job = client.get("/embeddings", headers=HEADERS).json()["job"]
        assert job["status"] == "failed" and "restart" in job["error"]


class TestServerSideRefusals:
    def test_no_switch_while_a_build_runs(self, client):
        _ready(QWEN)
        api_main._builds["b1"] = {"task": _Running()}
        overview = client.get("/embeddings", headers=HEADERS).json()
        assert overview["build_running"] is True and "build" in overview["switch_disabled_reason"]
        for request in (
            lambda: client.post("/embeddings/switch", headers=HEADERS, json={"model": QWEN}),
            lambda: client.post("/embeddings/switch", headers=HEADERS, json={"model": GTE, "mode": "parallel"}),
            lambda: client.patch("/settings", headers=HEADERS, json={"embedding_model": QWEN}),
            lambda: client.post("/embeddings/resume", headers=HEADERS),
        ):
            response = request()
            assert response.status_code == 409 and response.json()["detail"]["code"] == "build_running"
        assert api_main._embedding_store().active() == BGE

    def test_no_build_while_a_re_embed_job_runs(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(api_main, "CORPUS_DIR", tmp_path)
        (tmp_path / "other.jsonl").write_text('{"doc_id": "X", "text": "t"}\n')
        _ready()
        api_main._embedding_job["task"] = _Running()
        response = client.post("/build", headers=HEADERS, json={"dataset": "other"})
        assert response.status_code == 409 and response.json()["detail"]["code"] == "embedding_job_running"

    def test_switching_to_an_unembedded_model_needs_the_users_choice(self, client):
        _ready()
        response = client.post("/embeddings/switch", headers=HEADERS, json={"model": GTE})
        assert response.status_code == 409 and response.json()["detail"]["code"] == "mode_required"
        patched = client.patch("/settings", headers=HEADERS, json={"embedding_model": GTE})
        assert patched.status_code == 409 and patched.json()["detail"]["code"] == "embedding_switch_required"

    def test_the_eviction_prompt_cannot_be_skipped(self, client):
        _ready(QWEN)
        response = client.post("/embeddings/switch", headers=HEADERS, json={"model": GTE, "mode": "parallel"})
        detail = response.json()["detail"]
        assert response.status_code == 409 and detail["code"] == "eviction_required"
        assert detail["evictable"] == [QWEN, BGE]
        assert api_main._embedding_store().read()["job"] is None

    def test_plan_carries_the_real_cap_state(self, client):
        _ready(QWEN)
        plan = client.get("/embeddings/plan", headers=HEADERS, params={"model": GTE}).json()
        assert plan["stored"] == [QWEN, BGE] and plan["parallel"]["needs_eviction"] is True
        assert plan["replace"]["deletes"] == BGE


class TestQueryTimeBlock:
    def test_a_model_without_embeddings_blocks_the_query_and_lists_the_complete_ones(self, client):
        store = _ready(QWEN)
        store.set_active(GTE)  # e.g. a stale selection: GTE has nothing stored
        response = client.post("/query", headers=HEADERS, json={"query": "who won?"})
        detail = response.json()["detail"]
        assert response.status_code == 409 and detail["code"] == "embedding_mismatch"
        assert detail["selected"]["key"] == GTE and detail["selected"]["state"] == "not_stored"
        assert [m["key"] for m in detail["available"]] == [QWEN, BGE]
        assert client.started == []

    def test_equal_dimensions_are_not_equal_models(self, client):
        """Qwen3 and bge-large are both 1024-dim; bge-large embeddings must
        still never answer a query for Qwen3."""
        store = _ready()
        store.set_active(QWEN)
        assert EMBEDDING_MODELS[QWEN].dim == EMBEDDING_MODELS[BGE].dim
        response = client.post("/query", headers=HEADERS, json={"query": "q"})
        assert response.status_code == 409 and [m["key"] for m in response.json()["detail"]["available"]] == [BGE]

    def test_picking_an_offered_model_runs_the_query_with_it(self, client):
        store = _ready()
        store.set_active(QWEN)
        response = client.post("/query", headers=HEADERS, json={"query": "q", "embedding_model": BGE})
        assert response.status_code == 202
        [config] = client.started
        assert config.embedding_model == BGE and config.embedding_dim == 1024

    def test_naming_an_incomplete_model_is_blocked_too(self, client):
        store = _ready()
        store.begin_switch(GTE, "parallel", None, {"Q1_c0"}, BGE)  # building
        response = client.post("/query", headers=HEADERS, json={"query": "q", "embedding_model": GTE})
        assert response.status_code == 409 and response.json()["detail"]["selected"]["state"] == "building"

    def test_benchmark_runs_are_blocked_the_same_way(self, client, monkeypatch, tmp_path):
        monkeypatch.setattr(api_main, "QUESTIONS_DIR", tmp_path)
        (tmp_path / "public.jsonl").write_text('{"question_id": "q1", "question": "?"}\n')
        store = _ready()
        store.set_active(QWEN)
        response = client.post("/batch", headers=HEADERS, json={"dataset": "public"})
        assert response.status_code == 409 and response.json()["detail"]["code"] == "embedding_mismatch"

    def test_the_search_uses_the_models_own_index(self):
        graph = seeded(["Q1_c0"])
        calls = []
        graph.runInstalledQuery = lambda name, params: calls.append((name, params)) or []
        tg = TigerGraphClient(conn=graph)
        tg.hybrid_search([0.1] * 768, k=3, embedding_model="embeddinggemma-300m")
        assert calls[0][1]["emb_type"] == "Embedding_EmbeddingGemma"
        with pytest.raises(ValueError, match="1024 dims"):
            tg.hybrid_search([0.1] * 1024, k=3, embedding_model="embeddinggemma-300m")


class TestSwitchEndToEnd:
    def test_parallel_switch_embeds_then_activates(self, client, monkeypatch, fake_embedder):
        import ogr.graph.vector_status as vector_status

        _ready()
        graph = seeded(["Q1_c0"], {"Embedding_BGELarge": ["Q1_c0"]})
        tg = TigerGraphClient(conn=graph)
        monkeypatch.setattr(api_main, "_get_client", lambda config: tg)
        monkeypatch.setattr(vector_status, "wait_until_ready", lambda *a, **k: {})

        response = client.post("/embeddings/switch", headers=HEADERS, json={"model": GTE, "mode": "parallel"})
        assert response.status_code == 202 and response.json()["active"] == BGE
        deadline = time.monotonic() + 10
        while api_main._embedding_job_running() and time.monotonic() < deadline:
            asyncio.run(asyncio.sleep(0.05))
        body = client.get("/embeddings", headers=HEADERS).json()
        assert body["job"]["status"] == "complete", body["job"]
        assert body["active"] == GTE and body["stored"] == [GTE, BGE]
        assert graph.getVertexCount("Embedding_GteLarge") == 1 and graph.getVertexCount("Embedding_BGELarge") == 1
        # Now instant, both ways.
        assert client.patch("/settings", headers=HEADERS, json={"embedding_model": BGE}).status_code == 200
        assert client.get("/settings").json()["embedding_model"] == BGE
