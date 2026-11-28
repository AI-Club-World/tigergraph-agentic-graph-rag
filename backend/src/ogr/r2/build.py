"""Build the Round-2 graph from `corpus.jsonl` (SOLUTION-DESIGN §1-2).

    python -m ogr.r2.build corpus.jsonl [--counts graph_counts.json]

Order, each step idempotent except the first (which resets the graph):

1. `install_schema`: Round-1 schema, drops and recreates OlympicGraphRAG.
2. `install_round2`: the fact layer (Entity, Claim, ...) and its queries.
3. `install_r2_answer`: Athlete, WON, SourceRecord, REPORTS_ON and the ten
   `r2_*` queries.
3b. `install_queries`: Round-1 Q1-Q5, so the three-pipeline demo UI keeps
   working on the same graph (RAG still needs embeddings built separately).
4. `load_graph`: Document, OlympicEvent, Games, Sport, Venue, Chunk and their
   edges. Chunks are written WITHOUT embeddings: the Round-2 path reads text by
   document id or keyword, so no Embedding_* vertex is created and the build
   needs no embedding model (`load_graph` skips the vector when a chunk has none).
5. Athlete, WON, SourceRecord, REPORTS_ON, and an Entity plus one Claim per
   infobox key for every non-Olympic infobox page (ASSERTS, ABOUT).

Returns what was loaded and the graph's own counts by type, which the brief
asks to be submitted (`graph_counts.json`).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ogr.datasets.base import ClaimRecord
from ogr.graph.schema import install_queries, install_r2_answer, install_round2, install_schema
from ogr.ingest.load import load_graph
from ogr.ingest.load_claims import _claim_attrs, _upsert_edges, _upsert_vertices
from ogr.r2.corpus_model import CorpusModel, build_model

logger = logging.getLogger(__name__)

__all__ = ["BuildReport", "build", "graph_counts", "load_r2_layer"]

CORPUS_DATASET = "corpus"
CORPUS_SOURCE = "src:corpus"


@dataclass
class BuildReport:
    """`loaded`: vertices and edges the loaders wrote, by type (from their own
    counts). `graph`: the server's counts by type after the load ({} when the
    connection cannot say)."""

    loaded_vertices: dict[str, int] = field(default_factory=dict)
    loaded_edges: dict[str, int] = field(default_factory=dict)
    graph: dict[str, dict[str, int]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def graph_counts(client: Any) -> dict[str, dict[str, int]]:
    """Vertex and edge counts by type from the server (`getVertexCount('*')`,
    `getEdgeCount('*')`); empty dicts when the connection has no such call."""
    client._ensure_connection()
    conn = client.conn
    out: dict[str, dict[str, int]] = {"vertices": {}, "edges": {}}
    if conn is None:
        return out
    for key, method in (("vertices", "getVertexCount"), ("edges", "getEdgeCount")):
        call = getattr(conn, method, None)
        if not callable(call):
            continue
        counts = call("*")
        if isinstance(counts, dict):
            out[key] = {name: int(n) for name, n in sorted(counts.items())}
    return out


SETTLE_INTERVAL_S = 10.0
SETTLE_MAX_S = 300.0


def settled_graph_counts(
    client: Any, interval_s: float | None = None, max_s: float | None = None
) -> dict[str, dict[str, int]]:
    """`graph_counts`, read until two consecutive reads agree: Savanna applies
    upserts asynchronously, so counts read right after the load are too low."""
    interval = SETTLE_INTERVAL_S if interval_s is None else interval_s
    limit = SETTLE_MAX_S if max_s is None else max_s
    prev = graph_counts(client)
    if not (prev["vertices"] or prev["edges"]):
        return prev
    waited = 0.0
    while waited < limit:
        time.sleep(interval)
        waited += interval
        cur = graph_counts(client)
        if cur == prev:
            return cur
        prev = cur
    return prev


def load_r2_layer(client: Any, model: CorpusModel) -> tuple[dict[str, int], dict[str, int]]:
    """Write Athlete/WON, SourceRecord/REPORTS_ON and the Entity/Claim facts.

    Vertices first, then edges: an edge to a vertex not yet written is created
    as an empty stub that would hide a failed load. Every write is an upsert.
    """
    conn = client._require_conn()
    vertices: dict[str, int] = {}
    edges: dict[str, int] = {}

    athletes = [(a.athlete_id, {"name": a.name}) for _, a in sorted(model.athletes.items())]
    records = [(r.doc_id, {
        "title": r.title, "source_name": r.source_name, "authority": r.authority,
        "published_at": r.published_at, "published_text": r.published_text, "text": r.text,
    }) for r in model.sources]
    entities = [(e.entity_id, {"name": e.name, "entity_type": e.entity_type}) for e in model.entities]
    entity_doc = {e.entity_id: e.doc_id for e in model.entities}
    claims: list[tuple[str, dict[str, Any]]] = []
    asserts: list[tuple[str, str, dict]] = []
    about: list[tuple[str, str, dict]] = []
    names = {e.entity_id: e.name for e in model.entities}
    for f in model.facts:
        record = ClaimRecord(
            claim_id=f.claim_id, doc_id=f.doc_id, dataset_id=CORPUS_DATASET, subject_id=f.entity_id,
            subject_name=names[f.entity_id], predicate=f.predicate, value_text=f.value_text,
            value_num=f.value_num, source_id=CORPUS_SOURCE,
        )
        claims.append((f.claim_id, {**_claim_attrs(record), "value_note": f.note}))
        asserts.append((entity_doc[f.entity_id], f.claim_id, {}))
        about.append((f.claim_id, f.entity_id, {}))

    for vtype, rows in (
        ("Athlete", athletes), ("SourceRecord", records), ("Entity", entities), ("Claim", claims),
    ):
        _upsert_vertices(conn, vtype, rows)
        vertices[vtype] = len(rows)

    won = [
        (w.athlete_id, w.event_id,
         {"medal": w.medal, "noc": w.noc, "place": w.place, "event_key": w.event_key,
          "athlete_name": w.athlete_name})
        for w in model.won
    ]
    reports = [(link.record_id, link.event_id, {"score": link.score}) for link in model.links]
    for src, etype, tgt, rows in (
        ("Athlete", "WON", "OlympicEvent", won),
        ("SourceRecord", "REPORTS_ON", "OlympicEvent", reports),
        ("Document", "ASSERTS", "Claim", asserts),
        ("Claim", "ABOUT", "Entity", about),
    ):
        _upsert_edges(conn, src, etype, tgt, rows)
        edges[etype] = len(rows)
    return vertices, edges


def build(corpus_path: str | Path, client: Any, counts_path: str | Path | None = None) -> BuildReport:
    """Reset the graph, install the Round-2 schema and queries, load the corpus."""
    model = build_model(corpus_path)
    logger.info("Parsed %d events, %d entities, %d source records, %d chunks",
                len(model.events), len(model.entities), len(model.sources), len(model.chunks))

    install_schema(client)
    install_round2(client)
    install_r2_answer(client)
    install_queries(client)

    report = load_graph(client, model.documents, model.chunks)
    vertices = {
        "Document": report.documents, "OlympicEvent": report.olympic_events, "Games": report.games,
        "Sport": report.sports, "Venue": report.venues, "Chunk": report.chunks,
    }
    extra_vertices, edges = load_r2_layer(client, model)
    result = BuildReport(
        loaded_vertices={**vertices, **extra_vertices},
        loaded_edges={"round1_edges_total": report.edges, **edges},
        graph=settled_graph_counts(client),
    )
    if counts_path:
        Path(counts_path).write_text(json.dumps(result.graph, indent=2, sort_keys=True), encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse

    from ogr.graph.client import TigerGraphClient

    parser = argparse.ArgumentParser(description="Build the Round-2 TigerGraph graph from a corpus.")
    parser.add_argument("corpus", help="corpus.jsonl")
    parser.add_argument("--counts", default="graph_counts.json", help="where to write vertex/edge counts")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    report = build(args.corpus, TigerGraphClient(), counts_path=args.counts)
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
