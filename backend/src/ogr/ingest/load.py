"""GRAPH-05: load vertices/edges into TigerGraph.

Source spec: implementation-plan-GRAPH.md Group 2 · TECHNICAL-SPEC §2
Requirement: FR-11 · Gate: G1

Upserts Document, OlympicEvent, Games, Sport, Venue and Chunk vertices, and
every edge in the schema, from GRAPH-02's `ParsedDocument` output and
GRAPH-04's `Chunk` output. `PREV_EDITION`/`NEXT_EDITION` are resolved by a
(sport, event name, year) join against the `prev`/`next` infobox fields,
which are already-present years (93.5%/97.7% of events, post-fix) rather
than an inference problem.

Idempotent by construction: `upsertVertex`/`upsertEdge` are upserts, so
re-running this module against an already-loaded graph updates rather than
duplicates (GRAPH plan's own rollback note: "truncate graph, re-run; ingest
is idempotent by doc_id").

Untestable without a live graph: whether pyTigerGraph's `upsertVertex`/
`upsertEdge` calls actually succeed against the schema in `schema.gsql`. The
tests here exercise the load logic — what gets upserted, and the PREV/NEXT
join — against a fake connection that records calls.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ogr.graph.client import TigerGraphClient
from ogr.ingest.chunk_embed import Chunk
from ogr.ingest.infobox import ParsedDocument

__all__ = ["LoadReport", "load_graph"]


@dataclass
class LoadReport:
    """What got upserted, and how well PREV/NEXT resolved — the load-time
    equivalent of GRAPH-02's coverage report."""

    documents: int = 0
    olympic_events: int = 0
    games: int = 0
    sports: int = 0
    venues: int = 0
    chunks: int = 0
    prev_edges_resolved: int = 0
    prev_edges_unresolved: int = 0
    next_edges_resolved: int = 0
    next_edges_unresolved: int = 0
    edges: int = 0


def _games_year(games_id: str | None) -> int | None:
    if not games_id:
        return None
    year_part = games_id.split("-", 1)[0]
    return int(year_part) if year_part.isdigit() else None


def _games_season(games_id: str | None) -> str | None:
    if not games_id or "-" not in games_id:
        return None
    return games_id.split("-", 1)[1]


def _build_event_year_index(docs: Iterable[ParsedDocument]) -> dict[tuple[str, str, int], str]:
    """(sport_name, event_name, games_year) -> event_id, for PREV/NEXT resolution."""
    index: dict[tuple[str, str, int], str] = {}
    for doc in docs:
        if not (doc.is_olympic_event and doc.sport_name and doc.event_name):
            continue
        year = _games_year(doc.games_id)
        if year is None:
            continue
        index[(doc.sport_name, doc.event_name, year)] = doc.event_id or doc.doc_id
    return index


def _flush(conn, kind: str, key: tuple, payload: list, batch_size: int) -> None:
    """Send one accumulated batch. `kind` selects the pyTigerGraph call."""
    for i in range(0, len(payload), batch_size):
        window = payload[i : i + batch_size]
        if kind == "V":
            conn.upsertVertices(key[0], window)
        else:
            conn.upsertEdges(key[0], key[1], key[2], window)


def load_graph(
    client: TigerGraphClient,
    docs: list[ParsedDocument],
    chunks: list[Chunk] | None = None,
    batch_size: int = 500,
) -> LoadReport:
    """Upsert every document, event, games/sport/venue vertex, chunk and edge.

    Upserts are accumulated by type and sent with `upsertVertices`/
    `upsertEdges` rather than one REST call per object. The corpus is ~2.9k
    documents and ~16.7k chunks; at one call each that is ~45k round trips
    (measured ~0.38s each against a Savanna workspace, so roughly five
    hours). Batching makes the same load a few minutes.
    """
    client._ensure_connection()
    if client.conn is None:
        raise RuntimeError("No TigerGraph connection available; cannot load")
    conn = client.conn

    report = LoadReport()
    seen_games: set[str] = set()
    seen_sports: set[str] = set()
    seen_venues: set[str] = set()

    v_document: list[tuple] = []
    v_event: list[tuple] = []
    v_games: list[tuple] = []
    v_sport: list[tuple] = []
    v_venue: list[tuple] = []
    v_chunk: list[tuple] = []
    e_describes: list[tuple] = []
    e_at_games: list[tuple] = []
    e_in_sport: list[tuple] = []
    e_held_at: list[tuple] = []
    e_prev: list[tuple] = []
    e_next: list[tuple] = []
    e_has_chunk: list[tuple] = []

    for doc in docs:
        v_document.append((doc.doc_id, {
            "title": doc.title,
            "url": doc.url,
            "infobox_type": doc.infobox_type or "",
            "approx_tokens": doc.approx_tokens,
            "wikipedia_pageid": str(doc.wikipedia_pageid or ""),
        }))
        report.documents += 1

        if not doc.is_olympic_event:
            continue

        event_id = doc.event_id or doc.doc_id
        v_event.append((event_id, {
            "event_name": doc.event_name or "",
            "competitors": doc.competitors if doc.competitors is not None else 0,
            "competitors_text": doc.competitors_text or "",
            "nations": doc.nations if doc.nations is not None else 0,
            "nations_text": doc.nations_text or "",
            "date_text": doc.date_text or "",
            "date_month": doc.date_month if doc.date_month is not None else 0,
            "date_day_start": doc.date_day_start if doc.date_day_start is not None else 0,
            "date_day_end": doc.date_day_end if doc.date_day_end is not None else 0,
            "date_year": doc.date_year if doc.date_year is not None else 0,
            "gold": doc.gold,
            "silver": doc.silver,
            "bronze": doc.bronze,
            "gold_noc": doc.gold_noc or "",
            "win_value": doc.win_value or "",
            "win_label": doc.win_label or "",
            "parse_confidence": doc.parse_confidence,
        }))
        e_describes.append((doc.doc_id, event_id, {}))
        report.olympic_events += 1

        if doc.games_id:
            if doc.games_id not in seen_games:
                v_games.append((doc.games_id, {
                    "year": _games_year(doc.games_id) or 0,
                    "season": _games_season(doc.games_id) or "",
                }))
                seen_games.add(doc.games_id)
                report.games += 1
            e_at_games.append((event_id, doc.games_id, {}))

        if doc.sport_name:
            if doc.sport_name not in seen_sports:
                v_sport.append((doc.sport_name, {}))
                seen_sports.add(doc.sport_name)
                report.sports += 1
            e_in_sport.append((event_id, doc.sport_name, {}))

        if doc.venue_name:
            if doc.venue_name not in seen_venues:
                v_venue.append((doc.venue_name, {}))
                seen_venues.add(doc.venue_name)
                report.venues += 1
            e_held_at.append((event_id, doc.venue_name, {"date_text": doc.date_text or ""}))

    # PREV_EDITION / NEXT_EDITION: resolved by (sport, event name, year) join,
    # not inference — the prev/next fields are already years.
    year_index = _build_event_year_index(docs)
    for doc in docs:
        if not doc.is_olympic_event:
            continue
        event_id = doc.event_id or doc.doc_id
        if doc.prev_year is not None and doc.sport_name and doc.event_name:
            target = year_index.get((doc.sport_name, doc.event_name, doc.prev_year))
            if target:
                e_prev.append((event_id, target, {}))
                report.prev_edges_resolved += 1
            else:
                report.prev_edges_unresolved += 1
        if doc.next_year is not None and doc.sport_name and doc.event_name:
            target = year_index.get((doc.sport_name, doc.event_name, doc.next_year))
            if target:
                e_next.append((event_id, target, {}))
                report.next_edges_resolved += 1
            else:
                report.next_edges_unresolved += 1

    for chunk in chunks or []:
        attrs: dict[str, object] = {
            "doc_id": chunk.doc_id,
            "text": chunk.text,
            "seq": chunk.seq,
            "token_count": chunk.token_count,
        }
        if chunk.embedding:
            attrs["emb"] = chunk.embedding
        v_chunk.append((chunk.chunk_id, attrs))
        e_has_chunk.append((chunk.doc_id, chunk.chunk_id, {}))
        report.chunks += 1

    # Vertices before edges: an edge to a vertex that does not exist yet is
    # silently created as an empty stub, which would mask load failures.
    for vtype, payload in (
        ("Document", v_document), ("OlympicEvent", v_event), ("Games", v_games),
        ("Sport", v_sport), ("Venue", v_venue), ("Chunk", v_chunk),
    ):
        # Chunk rows carry a 1024-float vector each, so they go in smaller
        # windows to keep any single request a sane size.
        size = max(1, batch_size // 5) if vtype == "Chunk" else batch_size
        _flush(conn, "V", (vtype,), payload, size)

    for src, etype, tgt, payload in (
        ("Document", "DESCRIBES", "OlympicEvent", e_describes),
        ("OlympicEvent", "AT_GAMES", "Games", e_at_games),
        ("OlympicEvent", "IN_SPORT", "Sport", e_in_sport),
        ("OlympicEvent", "HELD_AT", "Venue", e_held_at),
        ("OlympicEvent", "PREV_EDITION", "OlympicEvent", e_prev),
        ("OlympicEvent", "NEXT_EDITION", "OlympicEvent", e_next),
        ("Document", "HAS_CHUNK", "Chunk", e_has_chunk),
    ):
        _flush(conn, "E", (src, etype, tgt), payload, batch_size)
        report.edges += len(payload)

    return report
