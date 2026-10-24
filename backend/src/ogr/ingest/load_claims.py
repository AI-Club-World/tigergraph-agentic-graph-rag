"""Load a dataset's fact layer: Dataset, Source, Entity, Claim and their edges
(Round 2, ROUND2-DESIGN.md §2, gate G1).

Runs after the Round-1 loader has written the dataset's Document and Chunk
vertices. It never writes or changes an OlympicEvent, Document or Chunk
vertex; it only adds the Round-2 vertices and edges that point at them.
Every write is an upsert, so loading the same dataset again is idempotent.

Relations and source reliability are computed over the new claims together
with the claims already in the graph about the same subjects, so a new
dataset's statements are weighed against the Round-1 ones.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ogr.datasets import adapter_for
from ogr.datasets.base import ClaimRecord, SourceRecord
from ogr.reasoning.relations import build_relations
from ogr.reasoning.reliability import estimate_reliability, prior_for

logger = logging.getLogger(__name__)

__all__ = ["ClaimLoadReport", "backfill", "load_claims", "load_claims_for_build"]

BATCH = 500


@dataclass
class ClaimLoadReport:
    dataset_id: str
    documents: int = 0
    chunks: int = 0
    claims: int = 0
    sources: int = 0
    entities: int = 0
    supersedes: int = 0
    contradicts: int = 0


def _batches(rows: list[Any]) -> Iterable[list[Any]]:
    for start in range(0, len(rows), BATCH):
        yield rows[start:start + BATCH]


def _upsert_vertices(conn: Any, vtype: str, rows: list[tuple[str, dict]]) -> None:
    for batch in _batches(rows):
        conn.upsertVertices(vtype, batch)


def _upsert_edges(conn: Any, src: str, edge: str, tgt: str, rows: list[tuple[str, str, dict]],
                  must_exist: bool = False) -> None:
    for batch in _batches(rows):
        if must_exist:
            try:
                conn.upsertEdges(src, edge, tgt, batch, vertexMustExist=True)
                continue
            except TypeError:  # a connection without the option (tests, old pyTigerGraph)
                pass
        conn.upsertEdges(src, edge, tgt, batch)


def _claim_attrs(c: ClaimRecord) -> dict[str, Any]:
    return {
        "dataset_id": c.dataset_id, "doc_id": c.doc_id, "subject_id": c.subject_id,
        "subject_name": c.subject_name, "predicate": c.predicate, "value_text": c.value_text,
        "value_num": float(c.value_num) if c.value_num is not None else 0.0,
        "has_num": c.value_num is not None,
        "valid_from": c.valid_from or "", "valid_to": c.valid_to or "", "observed_at": c.observed_at or "",
        "source_id": c.source_id, "extraction_conf": float(c.extraction_conf), "hedged": c.hedged,
        "hedge_terms": "; ".join(c.hedge_terms), "revision": c.revision,
    }


def load_claims(
    client: Any,
    corpus: str | Path,
    dataset_id: str,
    adapter: str = "olympic",
    title: str = "",
    chunk_ids: Iterable[str] = (),
    event_ids: Iterable[str] | None = None,
) -> ClaimLoadReport:
    """Write the fact layer for one dataset.

    `chunk_ids`: the dataset's chunks (from the build or the registry), for
    IN_DATASET, which the scoped search Q5S seeds from. `event_ids`: the
    OlympicEvent ids in the graph; a claim about an event outside it gets
    no ABOUT edge (it would otherwise create an empty OlympicEvent).
    """
    adapter_impl = adapter_for(adapter, dataset_id)
    docs: list[SourceRecord] = list(adapter_impl.documents(Path(corpus)))
    claims: list[ClaimRecord] = [c for d in docs for c in adapter_impl.claims(d)]
    report = ClaimLoadReport(dataset_id, documents=len(docs), claims=len(claims))

    subjects = sorted({c.subject_id for c in claims})
    others = [c for c in client.claims(subjects) if c.dataset_id != dataset_id] if subjects else []
    priors = {d.source_id: prior_for(d) for d in docs}
    reliability = estimate_reliability(claims + others, priors)
    new_ids = {c.claim_id for c in claims}
    relations = [r for r in build_relations(claims + others) if r.src in new_ids or r.dst in new_ids]
    report.supersedes = sum(1 for r in relations if r.kind == "SUPERSEDES")
    report.contradicts = sum(1 for r in relations if r.kind == "CONTRADICTS")

    conn = client._require_conn()
    _upsert_vertices(conn, "Dataset", [(dataset_id, {"title": title or dataset_id, "adapter": adapter})])
    sources: dict[str, SourceRecord] = {}
    for d in docs:
        sources.setdefault(d.source_id, d)
    _upsert_vertices(conn, "Source", [
        (sid, {
            "name": d.source_name or sid, "source_class": d.source_class,
            "reliability_prior": float(prior_for(d) or 0.0), "has_prior": prior_for(d) is not None,
            "reliability_est": float(reliability.get(sid, 0.0)),
        })
        for sid, d in sorted(sources.items()) if sid
    ])
    report.sources = len(sources)
    entities = sorted({(c.subject_id, c.subject_name) for c in claims if c.subject_id.startswith("ent:")})
    _upsert_vertices(conn, "Entity", [(eid, {"name": name, "entity_type": ""}) for eid, name in entities])
    report.entities = len(entities)
    _upsert_vertices(conn, "Claim", [(c.claim_id, _claim_attrs(c)) for c in claims])

    chunk_list = sorted(set(chunk_ids))
    report.chunks = len(chunk_list)
    _upsert_edges(conn, "Document", "IN_DATASET", "Dataset", [(d.doc_id, dataset_id, {}) for d in docs])
    _upsert_edges(conn, "Chunk", "IN_DATASET", "Dataset", [(cid, dataset_id, {}) for cid in chunk_list])
    _upsert_edges(conn, "Claim", "IN_DATASET", "Dataset", [(c.claim_id, dataset_id, {}) for c in claims])
    _upsert_edges(conn, "Source", "IN_DATASET", "Dataset",
                  [(s, dataset_id, {}) for s in sorted(sources) if s])
    _upsert_edges(conn, "Entity", "IN_DATASET", "Dataset", [(e, dataset_id, {}) for e, _ in entities])
    _upsert_edges(conn, "Document", "ASSERTS", "Claim", [(c.doc_id, c.claim_id, {}) for c in claims])
    _upsert_edges(conn, "Document", "FROM_SOURCE", "Source",
                  [(d.doc_id, d.source_id, {}) for d in docs if d.source_id])
    known_events = set(event_ids) if event_ids is not None else None
    about_events = [
        (c.claim_id, c.subject_id, {}) for c in claims
        if not c.subject_id.startswith("ent:") and (known_events is None or c.subject_id in known_events)
    ]
    _upsert_edges(conn, "Claim", "ABOUT", "OlympicEvent", about_events, must_exist=True)
    _upsert_edges(conn, "Claim", "ABOUT", "Entity",
                  [(c.claim_id, c.subject_id, {}) for c in claims if c.subject_id.startswith("ent:")])
    _upsert_edges(conn, "Claim", "SUPERSEDES", "Claim",
                  [(r.src, r.dst, {"reason": r.reason}) for r in relations if r.kind == "SUPERSEDES"])
    _upsert_edges(conn, "Claim", "CONTRADICTS", "Claim",
                  [(r.src, r.dst, {"reason": r.reason}) for r in relations if r.kind == "CONTRADICTS"])
    client._source_reliability = None
    logger.info("Claims loaded for %s: %s", dataset_id, report)
    return report


def backfill(
    client: Any, registry: Any, corpora: dict[str, Path], adapters: dict[str, str]
) -> list[ClaimLoadReport]:
    """The fact layer for datasets already in the graph (Round-1 included):
    claims from each dataset's file, IN_DATASET from the registry's chunk
    ids. No re-ingest and no re-embedding."""
    reports = []
    data = registry.read()["datasets"]
    every_event = sorted({e for d in data.values() for e in d.get("event_ids", [])})
    for name, entry in sorted(data.items()):
        if name not in corpora:
            logger.warning("Backfill: no corpus file for dataset %s; skipped", name)
            continue
        reports.append(load_claims(
            client, corpora[name], name, adapter=adapters.get(name, "olympic"),
            chunk_ids=entry.get("chunk_ids", []), event_ids=every_event,
        ))
    return reports


def load_claims_for_build(
    client: Any, corpus: str | Path, dataset_id: str, chunk_ids: Iterable[str], event_ids: Iterable[str]
) -> str | None:
    """A build's last graph step: the fact layer for the dataset just loaded,
    when the graph has the Round-2 types (None when it does not). A failure
    is reported, never raised: the Round-1 graph is already complete."""
    from ogr.datasets import detect_adapter
    from ogr.graph.schema import has_round2_schema

    try:
        if not has_round2_schema(client):
            return None
        report = load_claims(client, corpus, dataset_id, adapter=detect_adapter(corpus),
                             chunk_ids=chunk_ids, event_ids=event_ids)
    except Exception as e:  # noqa: BLE001 - reported on the build, not raised
        logger.error("Claims not loaded for %s: %s", dataset_id, e)
        return f"claims not loaded: {str(e)[:200]}"
    return (f"{report.claims} claims, {report.supersedes} SUPERSEDES, "
            f"{report.contradicts} CONTRADICTS")

