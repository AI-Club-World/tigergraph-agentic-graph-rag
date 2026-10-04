"""Adopt a graph this install did not build.

`out/datasets.json` and `out/embeddings.json` are local runtime state (not
committed). A fresh checkout pointed at a TigerGraph graph built elsewhere (a
teammate's machine, a cloud session) has neither, so it would treat a full
graph as empty: no embeddings for any model, every query and benchmark
refused, and a build that asks to reset everything.

`adopt_graph` rebuilds both files from the graph itself: the vertex ids per
type, which corpus file in `data/corpus/` the documents come from, and which
embedding models cover which chunks (an `Embedding_*` vertex's primary id is
the chunk it embeds). It only ever writes a file that does not exist, and it
adopts only when every document in the graph belongs to one corpus file;
anything else is left alone (the Build screen then shows the live counts).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from ogr.common.embedding_models import EMBEDDING_MODELS, resolve_model
from ogr.ingest.embedding_index import EmbeddingStore
from ogr.ingest.registry import DatasetRegistry

logger = logging.getLogger(__name__)

_DOC_ID = re.compile(r'"doc_id"\s*:\s*"((?:[^"\\]|\\.)*)"')


def corpus_doc_ids(path: Path) -> set[str]:
    """Document ids in a JSONL corpus (the first `doc_id` on each line)."""
    ids: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            match = _DOC_ID.search(line)
            if match:
                ids.add(match.group(1))
    return ids


def adopt_graph(
    client: Any,
    registry: DatasetRegistry,
    store: EmbeddingStore,
    corpus_dir: Path,
    default_model: str,
) -> dict[str, Any] | None:
    """Write the missing state files from the graph. Returns what was adopted,
    or None when there was nothing to adopt (or it could not be attributed)."""
    if registry.exists:
        return None
    doc_ids = set(client.vertex_ids("Document"))
    if not doc_ids:
        return None
    owner = None
    for path in sorted(corpus_dir.glob("*.jsonl")) if corpus_dir.exists() else []:
        if doc_ids <= corpus_doc_ids(path):
            owner = path
            break
    if owner is None:
        logger.info("Graph holds %d documents not all from one corpus file; not adopted", len(doc_ids))
        return None

    event_ids = client.vertex_ids("OlympicEvent")
    chunk_ids = client.vertex_ids("Chunk")
    covered = {key: client.vertex_ids(model.vertex_type) for key, model in EMBEDDING_MODELS.items()}
    covered = {key: ids for key, ids in covered.items() if ids}

    # The graph's schema model: the configured one when it has embeddings,
    # else the model covering the most chunks.
    default_key = resolve_model(default_model).key
    active = default_key
    if default_key not in covered and covered:
        active = max(covered, key=lambda k: len(covered[k]))
    model = EMBEDDING_MODELS[active]

    registry.reset(model.key, model.dim)
    registry.record(
        owner.stem,
        {"doc_ids": sorted(doc_ids), "event_ids": event_ids, "chunk_ids": chunk_ids},
        {
            "documents": len(doc_ids),
            "events": len(event_ids),
            "chunks": len(chunk_ids),
            "vectors": len(covered.get(active, [])),
            "embedding_model": model.key,
            "adopted": True,
        },
        owner.stat().st_size,
    )
    if not store.path.exists():
        for key, ids in covered.items():
            store.add_covered(key, ids)
        store.set_active(active)
    summary = {
        "dataset": owner.stem,
        "documents": len(doc_ids),
        "chunks": len(chunk_ids),
        "embeddings": {key: len(ids) for key, ids in covered.items()},
        "active": active,
    }
    logger.info("Adopted the existing graph: %s", summary)
    return summary
