"""Embedding switching: the 2-model cap, eviction/replace deletion scope,
checkpointed resumable jobs (config-docs/EMBEDDING-SWITCHING.md)."""

from __future__ import annotations

import dataclasses

import pytest

import ogr.ingest.embedding_index as ei
from ogr.common.embedding_models import EMBEDDING_MODELS
from ogr.graph.client import TigerGraphClient
from ogr.ingest.embedding_index import EmbeddingStore, SwitchRefused, run_job
from tests.graph.fake_tigergraph import seeded

QWEN, GEMMA, GTE, MXBAI, BGE = (
    "qwen3-embedding-0.6b", "embeddinggemma-300m", "gte-large-en-v1.5", "mxbai-embed-large-v1", "bge-large-en-v1.5",
)
CHUNKS = [f"D1_c{i}" for i in range(7)]
CORPUS = set(CHUNKS)
VT = {k: m.vertex_type for k, m in EMBEDDING_MODELS.items()}


@pytest.fixture
def store(tmp_path):
    return EmbeddingStore(tmp_path / "embeddings.json")


@pytest.fixture(autouse=True)
def small_batches(monkeypatch):
    monkeypatch.setattr(ei, "CHECKPOINT_BATCH", 3)  # 7 chunks -> batches of 3, 3, 1


def _client(graph):
    return TigerGraphClient(conn=graph)


class _Embedder:
    """Records every batch it embeds; can fail on a chosen call."""

    def __init__(self, fail_on: int | None = None):
        self.batches: list[list[str]] = []
        self.fail_on = fail_on

    def __call__(self, model, texts):
        self.batches.append(texts)
        if self.fail_on is not None and len(self.batches) == self.fail_on:
            raise ConnectionError("rate limited (429)")
        return [[0.5] * model.dim for _ in texts]


def _stored(store, *keys, covering=CHUNKS):
    for key in keys:
        store.add_covered(key, list(covering))


# ── deletion scope ───────────────────────────────────────────────────────────


class TestDeletionNeverCascades:
    def test_evicting_a_model_removes_only_its_vertices_index_and_edges(self):
        graph = seeded(CHUNKS, {VT[BGE]: CHUNKS, VT[QWEN]: CHUNKS})
        removed = _client(graph).delete_embeddings(EMBEDDING_MODELS[BGE])
        assert removed == len(CHUNKS)
        assert graph.getVertexCount(VT[BGE]) == 0 and not graph.edges_of("HAS_EMBEDDING", VT[BGE])
        # Canonical chunks, their documents' edges and the other model: untouched.
        assert graph.getVertexCount("Chunk") == len(CHUNKS)
        assert len(graph.edges_of("HAS_CHUNK")) == len(CHUNKS)
        assert graph.getVertexCount(VT[QWEN]) == len(CHUNKS)
        assert len(graph.edges_of("HAS_EMBEDDING", VT[QWEN])) == len(CHUNKS)
        assert graph.calls == [("delVertices", VT[BGE])]

    def test_deleting_some_chunks_embeddings_keeps_the_rest(self):
        graph = seeded(CHUNKS, {VT[BGE]: CHUNKS, VT[QWEN]: CHUNKS})
        _client(graph).delete_embeddings(EMBEDDING_MODELS[BGE], CHUNKS[:2])
        assert graph.getVertexCount(VT[BGE]) == 5 and graph.getVertexCount(VT[QWEN]) == 7
        assert graph.getVertexCount("Chunk") == 7

    def test_a_delete_can_never_be_pointed_at_chunk(self):
        graph = seeded(CHUNKS, {VT[BGE]: CHUNKS})
        forged = dataclasses.replace(EMBEDDING_MODELS[BGE], vertex_type="Chunk")
        with pytest.raises(ValueError, match="not an embedding vertex type"):
            _client(graph).delete_embeddings(forged)
        assert graph.calls == [] and graph.getVertexCount("Chunk") == 7


class TestIdempotentWrites:
    def test_writing_a_chunk_again_overwrites_its_embedding(self):
        graph = seeded(CHUNKS)
        client = _client(graph)
        model = EMBEDDING_MODELS[GEMMA]
        client.upsert_embeddings(model, [(c, [0.1] * 768) for c in CHUNKS[:3]])
        client.upsert_embeddings(model, [(c, [0.2] * 768) for c in CHUNKS[:3]])
        assert graph.getVertexCount(VT[GEMMA]) == 3
        assert len(graph.edges_of("HAS_EMBEDDING", VT[GEMMA])) == 3
        assert graph.vertices[VT[GEMMA]]["D1_c0"]["emb"] == [0.2] * 768

    def test_a_vector_of_the_wrong_size_is_never_written(self):
        graph = seeded(CHUNKS)
        with pytest.raises(ValueError, match="768"):
            _client(graph).upsert_embeddings(EMBEDDING_MODELS[GEMMA], [("D1_c0", [0.1] * 1024)])
        assert graph.calls == []


# ── switch decisions ─────────────────────────────────────────────────────────


class TestSwitchDecisions:
    def test_a_complete_model_switches_instantly(self, store):
        _stored(store, BGE, QWEN)
        store.set_active(BGE)
        assert store.begin_switch(QWEN, None, None, CORPUS, BGE) == {"switched": True, "active": QWEN}
        assert store.read()["job"] is None

    def test_an_incomplete_model_needs_an_explicit_choice(self, store):
        _stored(store, BGE)
        store.set_active(BGE)
        with pytest.raises(SwitchRefused) as refused:
            store.begin_switch(QWEN, None, None, CORPUS, BGE)
        assert refused.value.code == "mode_required"
        assert store.read()["job"] is None and store.active() == BGE

    def test_plan_reports_the_real_cap_state(self, store):
        _stored(store, BGE, QWEN)
        store.set_active(BGE)
        plan = store.plan(GTE, CORPUS, BGE)
        assert plan["stored"] == [QWEN, BGE] and plan["cap"] == 2 and not plan["instant"]
        assert plan["parallel"] == {"needs_eviction": True, "evictable": [QWEN, BGE], "stored_after": 2}
        assert plan["replace"]["deletes"] == BGE and plan["replace"]["keeps"] == [QWEN]
        assert plan["replace"]["needs_eviction"] is False
        store.drop(QWEN)
        assert store.plan(GTE, CORPUS, BGE)["parallel"]["needs_eviction"] is False

    def test_a_third_model_in_parallel_requires_an_eviction_first(self, store):
        _stored(store, BGE, QWEN)
        store.set_active(BGE)
        with pytest.raises(SwitchRefused) as refused:
            store.begin_switch(GTE, "parallel", None, CORPUS, BGE)
        assert refused.value.code == "eviction_required" and refused.value.extra["evictable"] == [QWEN, BGE]
        with pytest.raises(SwitchRefused) as invalid:
            store.begin_switch(GTE, "parallel", MXBAI, CORPUS, BGE)
        assert invalid.value.code == "invalid_eviction"
        assert store.read()["job"] is None, "nothing may start before the user picks"

    def test_an_eviction_is_refused_when_under_the_cap(self, store):
        _stored(store, BGE)
        store.set_active(BGE)
        with pytest.raises(SwitchRefused) as refused:
            store.begin_switch(GTE, "parallel", BGE, CORPUS, BGE)
        assert refused.value.code == "eviction_not_needed"

    def test_replace_makes_the_new_model_active_at_once(self, store):
        _stored(store, BGE, QWEN)
        store.set_active(BGE)
        result = store.begin_switch(GTE, "replace", None, CORPUS, BGE)
        assert result["active"] == GTE and result["job"]["delete"] == [BGE]
        assert store.model_status(BGE, CORPUS)["state"] == "evicting"

    def test_parallel_keeps_the_old_model_active_while_building(self, store):
        _stored(store, BGE)
        store.set_active(BGE)
        result = store.begin_switch(GTE, "parallel", None, CORPUS, BGE)
        assert result["active"] == BGE and result["job"]["delete"] == []

    def test_no_second_job_while_one_runs(self, store):
        _stored(store, BGE)
        store.set_active(BGE)
        store.begin_switch(GTE, "parallel", None, CORPUS, BGE)
        with pytest.raises(SwitchRefused) as refused:
            store.begin_switch(MXBAI, "replace", None, CORPUS, BGE)
        assert refused.value.code == "embedding_job_running"


# ── jobs ─────────────────────────────────────────────────────────────────────


def _run(store, graph, embed, ready=lambda: None):
    return run_job(store, _client(graph), corpus=lambda: CORPUS, embed=embed, wait_ready=ready)


class TestJobs:
    def test_parallel_job_evicts_first_then_embeds_then_activates(self, store):
        graph = seeded(CHUNKS, {VT[BGE]: CHUNKS, VT[QWEN]: CHUNKS})
        _stored(store, BGE, QWEN)
        store.set_active(BGE)
        store.begin_switch(GTE, "parallel", QWEN, CORPUS, BGE)
        embed = _Embedder()
        final = _run(store, graph, embed)
        assert final["status"] == "complete" and final["batches_done"] == 3
        # Eviction ran before the first embedding write for the new model.
        first_write = graph.calls.index(("upsertVertices", VT[GTE], CHUNKS[:3]))
        assert graph.calls.index(("delVertices", VT[QWEN])) < first_write
        assert graph.getVertexCount(VT[QWEN]) == 0
        assert graph.getVertexCount(VT[BGE]) == 7 and graph.getVertexCount(VT[GTE]) == 7
        assert graph.getVertexCount("Chunk") == 7
        assert store.stored() == [GTE, BGE] and store.active() == GTE
        assert store.complete_models(CORPUS) == [GTE, BGE]

    def test_replace_deletes_only_the_outgoing_model(self, store):
        graph = seeded(CHUNKS, {VT[BGE]: CHUNKS, VT[QWEN]: CHUNKS})
        _stored(store, BGE, QWEN)
        store.set_active(BGE)
        store.begin_switch(MXBAI, "replace", None, CORPUS, BGE)
        assert _run(store, graph, _Embedder())["status"] == "complete"
        assert graph.getVertexCount(VT[BGE]) == 0 and not graph.edges_of("HAS_EMBEDDING", VT[BGE])
        assert graph.getVertexCount(VT[QWEN]) == 7 and len(graph.edges_of("HAS_EMBEDDING", VT[QWEN])) == 7
        assert graph.getVertexCount("Chunk") == 7 and len(graph.edges_of("HAS_CHUNK")) == 7
        assert store.stored() == [QWEN, MXBAI] and store.active() == MXBAI

    def test_a_failure_resumes_from_the_last_checkpoint(self, store):
        graph = seeded(CHUNKS, {VT[BGE]: CHUNKS})
        _stored(store, BGE)
        store.set_active(BGE)
        store.begin_switch(GTE, "parallel", None, CORPUS, BGE)
        failed = _run(store, graph, _Embedder(fail_on=2))  # batch 2 of 3 hits a 429
        assert failed["status"] == "failed" and "429" in failed["error"]
        assert failed["batches_done"] == 1 and failed["chunks_done"] == 3
        assert store.model_status(GTE, CORPUS)["state"] == "failed"
        assert store.active() == BGE, "the old model stays queryable"

        store.begin_resume()
        embed = _Embedder()
        assert _run(store, graph, embed)["status"] == "complete"
        # Only the unfinished batches ran again: 4 chunks, not all 7.
        assert sum(map(len, embed.batches)) == 4
        assert graph.getVertexCount(VT[GTE]) == 7

    def test_a_batch_written_before_the_failure_is_not_duplicated(self, store, monkeypatch):
        """The upsert of batch 2 lands but the response is lost: the batch is
        not checkpointed, so a resume writes it again — onto the same ids."""
        graph = seeded(CHUNKS)
        store.set_active(BGE)
        _stored(store, BGE)
        store.begin_switch(GTE, "parallel", None, CORPUS, BGE)
        client = _client(graph)
        real = client.upsert_embeddings
        calls = {"n": 0}

        def flaky(model, rows):
            calls["n"] += 1
            real(model, rows)
            if calls["n"] == 2:
                raise ConnectionError("connection reset after write")
            return len(rows)

        monkeypatch.setattr(client, "upsert_embeddings", flaky)
        run_job(store, client, corpus=lambda: CORPUS, embed=_Embedder(), wait_ready=lambda: None)
        assert graph.getVertexCount(VT[GTE]) == 6 and store.read()["job"]["batches_done"] == 1
        store.begin_resume()
        run_job(store, client, corpus=lambda: CORPUS, embed=_Embedder(), wait_ready=lambda: None)
        assert graph.getVertexCount(VT[GTE]) == 7
        assert len(graph.edges_of("HAS_EMBEDDING", VT[GTE])) == 7
        assert store.model_status(GTE, CORPUS)["complete"]

    def test_not_complete_until_the_vector_index_is_ready(self, store):
        graph = seeded(CHUNKS)
        _stored(store, BGE)
        store.set_active(BGE)
        store.begin_switch(GTE, "parallel", None, CORPUS, BGE)

        def not_ready():
            raise TimeoutError("index still building")

        assert _run(store, graph, _Embedder(), not_ready)["status"] == "failed"
        assert not store.model_status(GTE, CORPUS)["complete"]
        store.begin_resume()
        embed = _Embedder()
        assert _run(store, graph, embed)["status"] == "complete"
        assert embed.batches == [], "every batch was checkpointed; only the index wait reran"

    def test_a_failed_eviction_is_retried_on_resume(self, store, monkeypatch):
        graph = seeded(CHUNKS, {VT[BGE]: CHUNKS, VT[QWEN]: CHUNKS})
        _stored(store, BGE, QWEN)
        store.set_active(BGE)
        store.begin_switch(GTE, "parallel", QWEN, CORPUS, BGE)
        client = _client(graph)
        monkeypatch.setattr(client, "delete_embeddings", lambda model, ids=None: (_ for _ in ()).throw(OSError("down")))
        embed = _Embedder()
        run_job(store, client, corpus=lambda: CORPUS, embed=embed, wait_ready=lambda: None)
        assert store.read()["job"]["status"] == "failed" and embed.batches == [], "no embedding before the eviction"
        store.begin_resume()
        assert _run(store, graph, embed)["status"] == "complete"
        assert graph.getVertexCount(VT[QWEN]) == 0 and store.stored() == [GTE, BGE]

    def test_a_model_that_lost_chunks_is_completed_for_just_those(self, store):
        graph = seeded(CHUNKS, {VT[QWEN]: CHUNKS[:5]})
        _stored(store, BGE)
        _stored(store, QWEN, covering=CHUNKS[:5])
        store.set_active(BGE)
        assert store.model_status(QWEN, CORPUS)["state"] == "incomplete"
        store.begin_complete(QWEN, CORPUS)
        embed = _Embedder()
        assert _run(store, graph, embed)["status"] == "complete"
        assert sum(map(len, embed.batches)) == 2 and store.model_status(QWEN, CORPUS)["complete"]
