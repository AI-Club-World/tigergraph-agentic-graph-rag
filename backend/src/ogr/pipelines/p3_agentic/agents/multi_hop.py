"""Multi-hop reasoning agent — planner chaining Q4 → Q1.

Source spec: ARCHITECTURE-SPEC §4 · TECHNICAL-SPEC §3

Implements the 'Multi-hop reasoning' specialised agent.
Chains: Q4 (traverse temporal edges) → Q1 (direct lookup on resolved event).

Used for temporal chains like:
  "What sport was contested at the previous edition of [event]?"
  → Q4 traverses PREV_EDITION from anchor event
  → Q1 looks up the target field on the traversed event

This is the correct amount of machinery for the five question types —
stated explicitly, not apologised for.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ogr.graph.client import TigerGraphClient
from ogr.pipelines.p3_agentic.agents.agent_result import AgentResult
from ogr.pipelines.p3_agentic.agents.entity_linking import (
    ResolvedAnchors,
    edition_of,
    lookup_named_event,
    narrow_to_date,
    narrow_to_games,
)
from ogr.pipelines.p3_agentic.intent import IntentSchema

logger = logging.getLogger(__name__)


# Q1 calls per venue expansion: a venue can host 100+ events across Games;
# the Games anchor narrows them, the cap bounds the round trips.
MAX_VENUE_EVENTS = 30


def _lookup_rows(client: TigerGraphClient, event_id: str, target_field: str) -> list[dict[str, Any]]:
    return client._run_query("q1_lookup", {"event_id": event_id, "target_field": target_field}) or []


def _anchor_event_ids(client: TigerGraphClient, intent: IntentSchema, anchors: ResolvedAnchors) -> list[str]:
    """The event(s) the question names. Q4 matched `event_name` across every
    edition, so the anchor is resolved first — Q1 by title, narrowed to the
    Games anchor — and the traversal starts from those event ids only."""
    if anchors.event_id:
        return [anchors.event_id]
    if not anchors.title:
        return []
    rows = lookup_named_event(client, anchors, intent.target_field or "")
    ids = [r.get("event_id") for r in rows if r.get("event_id")]
    # No event by that name (e.g. a page title): traverse from the name itself.
    return ids or [anchors.title]


def _evidence(row: dict[str, Any], event_id: str, target_field: str) -> dict[str, Any]:
    return {
        **row,
        "event_id": row.get("event_id") or event_id,
        "target_field": target_field,
        "value": row.get(target_field, row.get("value", "")),
        "doc_id": row.get("doc_id", ""),
        "source": "multi_hop",
    }


def run_venue_events(
    client: TigerGraphClient,
    intent: IntentSchema,
    anchors: ResolvedAnchors,
) -> AgentResult:
    """Venue-anchored question: Q4 HELD_AT (venue -> its events) -> Q1 per
    event, narrowed to the Games anchor. Q4's HELD_AT rows carry only ids and
    names, so Q1 supplies the attributes (medallists, dates) and the doc_id."""
    t0 = time.perf_counter()
    if not anchors.venue:
        return AgentResult(error="Venue expansion: no resolved venue", notes="edge_type=HELD_AT")
    target_field = intent.target_field or "event_name"
    try:
        events = client._run_query(
            "q4_traverse", {"anchor": anchors.venue, "edge_type": "HELD_AT", "hops": 1}
        )
        # Narrow to the anchored edition before the cap: a stadium hosts dozens
        # of events per Games, and the cap would otherwise keep an arbitrary 30.
        events = events or []
        year = anchors.date_year or (int(anchors.games[:4]) if anchors.games else None)
        in_edition = [
            ev for ev in events
            if (anchors.games and edition_of(ev.get("event_id", "")) == anchors.games)
            or (not anchors.games and year and edition_of(ev.get("event_id", "")).startswith(f"{year}-"))
        ]
        events = in_edition or events
        rows: list[dict[str, Any]] = []
        for event in events[:MAX_VENUE_EVENTS]:
            event_id = event.get("event_id", "")
            if event_id:
                rows += [_evidence(r, event_id, target_field)
                         for r in _lookup_rows(client, event_id, target_field)]
    except Exception as e:
        logger.error("Venue expansion failed: %s", e)
        return AgentResult(error=str(e), latency_ms=(time.perf_counter() - t0) * 1000.0)
    evidence = narrow_to_date(narrow_to_games(rows, anchors.games), anchors)
    return AgentResult(
        evidence=evidence,
        chunks_returned=len(evidence),
        citations_count=len(evidence),
        latency_ms=(time.perf_counter() - t0) * 1000.0,
        notes=f"Q4(HELD_AT)→Q1: venue={anchors.venue}, events={len(events or [])}, kept={len(evidence)}",
    )


def run_multi_hop(
    client: TigerGraphClient,
    intent: IntentSchema,
    anchors: ResolvedAnchors,
    edge_type: str = "PREV_EDITION",
    hops: int = 1,
) -> AgentResult:
    """Execute the anchor -> Q4 -> Q1 chain for multi-hop/temporal questions.

    Step 0: resolve the named event to its event id(s) (Q1 + Games anchor).
    Step 1: Q4 traverse from each anchor event along edge_type for hops steps.
    Step 2: Q1 lookup target_field on each traversed event.
    """
    t0 = time.perf_counter()
    target_field = intent.target_field or "event_name"

    try:
        anchor_ids = _anchor_event_ids(client, intent, anchors)
    except Exception as e:
        logger.error("Multi-hop anchor lookup failed: %s", e)
        return AgentResult(error=f"Q1 error: {e}", latency_ms=(time.perf_counter() - t0) * 1000.0)
    if not anchor_ids:
        return AgentResult(
            error="Multi-hop: no resolved anchor for Q4 traversal",
            notes=f"edge_type={edge_type}, hops={hops}",
        )

    # Step 1: Q4 traverse
    traversal_results: list[dict[str, Any]] = []
    try:
        for anchor_value in anchor_ids:
            params_q4 = {"anchor": anchor_value, "edge_type": edge_type, "hops": hops}
            traversal_results += client._run_query("q4_traverse", params_q4) or []
    except Exception as e:
        logger.error("Multi-hop Q4 failed: %s", e)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return AgentResult(error=f"Q4 error: {e}", latency_ms=latency_ms)

    if not traversal_results:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return AgentResult(
            evidence=[],
            chunks_returned=0,
            latency_ms=latency_ms,
            notes=f"Q4→Q1: no results from traversal anchor={anchor_ids}",
        )

    # Step 2: Q1 lookup on each traversed event
    all_evidence: list[dict[str, Any]] = []
    for traversed in traversal_results:
        attrs = traversed.get("attributes", traversed)
        event_id = attrs.get("event_id") or traversed.get("v_id", "")
        if not event_id:
            continue
        try:
            for r in _lookup_rows(client, event_id, target_field):
                all_evidence.append(_evidence(r.get("attributes", r), event_id, target_field))
        except Exception as e:
            logger.warning("Multi-hop Q1 lookup failed for event %s: %s", event_id, e)

    latency_ms = (time.perf_counter() - t0) * 1000.0
    return AgentResult(
        evidence=all_evidence,
        chunks_returned=len(all_evidence),
        citations_count=len(all_evidence),
        latency_ms=latency_ms,
        notes=(
            f"Q4→Q1 chain: edge={edge_type}, hops={hops}, anchors={len(anchor_ids)}, "
            f"traversed={len(traversal_results)}, resolved={len(all_evidence)}"
        ),
    )
