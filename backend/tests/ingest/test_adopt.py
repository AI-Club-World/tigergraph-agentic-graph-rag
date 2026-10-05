"""A fresh install adopts a graph built elsewhere instead of treating it as empty."""

from __future__ import annotations

import json
from types import SimpleNamespace

from ogr.common.embedding_models import EMBEDDING_MODELS
from ogr.ingest.adopt import adopt_graph
from ogr.ingest.embedding_index import EmbeddingStore
from ogr.ingest.registry import DatasetRegistry

BGE = EMBEDDING_MODELS["bge-large-en-v1.5"]


def _client(vertices):
    return SimpleNamespace(vertex_ids=lambda vtype: sorted(vertices.get(vtype, [])))


def _corpus(tmp_path, ids, name="corpus"):
    folder = tmp_path / "corpus"
    folder.mkdir(exist_ok=True)
    (folder / f"{name}.jsonl").write_text(
        "".join(json.dumps({"doc_id": i, "title": i, "text": "t"}) + "\n" for i in ids), encoding="utf-8"
    )
    return folder


def _state(tmp_path):
    return DatasetRegistry(tmp_path / "out" / "datasets.json"), EmbeddingStore(tmp_path / "out" / "embeddings.json")


GRAPH = {
    "Document": ["Q1", "Q2"],
    "OlympicEvent": ["e1"],
    "Chunk": ["Q1_c0", "Q1_c1", "Q2_c0"],
    BGE.vertex_type: ["Q1_c0", "Q1_c1", "Q2_c0"],
}


def test_a_graph_built_elsewhere_is_recorded_with_its_embeddings(tmp_path):
    registry, store = _state(tmp_path)
    adopted = adopt_graph(_client(GRAPH), registry, store, _corpus(tmp_path, ["Q1", "Q2", "Q3"]), BGE.key)
    assert adopted["dataset"] == "corpus" and adopted["embeddings"] == {BGE.key: 3}
    entry = registry.get("corpus")
    assert entry["documents"] == 2 and entry["chunks"] == 3 and entry["adopted"] is True
    assert registry.current_layout()
    # The point: the model is complete for the adopted chunks, so queries and benchmarks run.
    assert store.model_status(BGE.key, registry.all_chunk_ids())["complete"]
    assert store.active() == BGE.key


def test_nothing_is_adopted_when_documents_are_not_from_one_corpus_file(tmp_path):
    registry, store = _state(tmp_path)
    assert adopt_graph(_client(GRAPH), registry, store, _corpus(tmp_path, ["Q1"]), BGE.key) is None
    assert not registry.exists and not store.path.exists()


def test_a_recorded_dataset_or_an_empty_graph_is_left_alone(tmp_path):
    registry, store = _state(tmp_path)
    assert adopt_graph(_client({}), registry, store, _corpus(tmp_path, ["Q1"]), BGE.key) is None
    registry.reset(BGE.key, BGE.dim)
    registry.record("mine", {"doc_ids": ["Q1"]}, {"documents": 1, "events": 0, "chunks": 0}, 1)
    assert adopt_graph(_client(GRAPH), registry, store, _corpus(tmp_path, ["Q1", "Q2"]), BGE.key) is None
    assert registry.get("corpus") is None


def test_an_empty_record_left_by_a_failed_reset_build_is_adopted_over(tmp_path):
    # A confirmed reset wrote an empty datasets.json and reset the store, then the
    # build failed before recording its dataset; the graph still holds everything.
    registry, store = _state(tmp_path)
    registry.reset(BGE.key, BGE.dim)
    store.reset(BGE.key)
    adopted = adopt_graph(_client(GRAPH), registry, store, _corpus(tmp_path, ["Q1", "Q2"]), BGE.key)
    assert adopted and registry.get("corpus")["chunks"] == 3
    assert store.model_status(BGE.key, registry.all_chunk_ids())["complete"]
