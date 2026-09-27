"""Aggregation agent — wrapper over Q2 (count_where) and Q3 (argmax).

Source spec: ARCHITECTURE-SPEC §4 · TECHNICAL-SPEC §3

Implements the 'Aggregation' specialised agent.
Routes to Q2 (COUNT) or Q3 (ARGMAX) based on intent operation.

Q2: count_where(anchor_sport, anchor_games, anchor_venue, constraints_json, field)
    SumAccum<INT> — widened to accept venue and multiple constraints.

Q3: argmax(anchor_sport, anchor_games, anchor_venue, field)
    HeapAccum top-3 — surfaces parse_confidence exclusion count in notes.

Surfacing parse_confidence: Q2/Q3 return the excluded count from partially-parsed
OlympicEvent records (parse_confidence < 1.0). This makes the system's uncertainty
visible — 'the system tells you what it could not parse' (evidence.py picks up notes).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from ogr.graph.client import TigerGraphClient
from ogr.pipelines.p3_agentic.agents.agent_result import AgentResult
from ogr.pipelines.p3_agentic.agents.entity_linking import ResolvedAnchors
from ogr.pipelines.p3_agentic.intent import IntentSchema

logger = logging.getLogger(__name__)

# Counted events shown after a Q2 count (a long list only costs tokens).
MAX_COUNT_MEMBERS = 30


def run_aggregation(
    client: TigerGraphClient,
    intent: IntentSchema,
    anchors: ResolvedAnchors,
) -> AgentResult:
    """Dispatch to Q2 (COUNT) or Q3 (ARGMAX) based on intent.operation."""
    if intent.operation == "COUNT":
        return _run_count_where(client, intent, anchors)
    elif intent.operation == "ARGMAX":
        return _run_argmax(client, intent, anchors)
    else:
        return AgentResult(
            error=f"Aggregation agent called with unexpected operation: {intent.operation}",
            notes=f"operation={intent.operation}",
        )


# The fields q2_count_where.gsql can filter on.
Q2_FIELDS = frozenset({"competitors", "nations", "date_year"})


def _numeric_constraint_value(value: Any) -> float:
    """Q2's constrainable fields (competitors, nations, date_year) are all
    numeric, but `AnchorConstraint.value` is typed `Any` because the intent
    parser's JSON-schema path may emit a numeric-looking string (`"10"`)
    instead of a number. Serialised as-is, that string makes
    `q2_count_where.gsql`'s `c0.getDouble("value")` raise a GSQL runtime
    error — caught by `_run_query` and returned as `[]`, which silently
    empties evidence for every constrained COUNT question. Coerce once here,
    the one place that knows both what the field expects and what the
    parser may have produced.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        logger.warning("Q2 constraint value %r is not numeric; treating as 0", value)
        return 0.0


def _run_count_where(
    client: TigerGraphClient,
    intent: IntentSchema,
    anchors: ResolvedAnchors,
) -> AgentResult:
    """Execute Q2: count_where(...)"""
    t0 = time.perf_counter()
    # Q2 filters only on these numeric fields; any other constraint (a date,
    # a non-numeric value) would fail every row and read as "0 events". It is
    # left out and named in the trace instead of silently zeroing the count.
    usable, dropped = [], []
    for c in intent.constraints or []:
        try:
            value = float(c.value)
        except (TypeError, ValueError):
            value = None
        if c.field in Q2_FIELDS and value is not None:
            usable.append({**c.model_dump(), "value": value})
        else:
            dropped.append(f"{c.field} {c.op} {c.value!r}")
    constraints_json = json.dumps(usable)
    params = {
        "anchor_sport": anchors.sport or "",
        "anchor_games": anchors.games or "",
        "anchor_venue": anchors.venue or "",
        "constraints_json": constraints_json,
        "field": intent.target_field or "competitors",
    }
    try:
        raw = client._run_query("q2_count_where", params)
    except Exception as e:
        logger.error("Q2 count_where failed: %s", e)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return AgentResult(error=str(e), latency_ms=latency_ms, notes=f"Q2 error: {e}")

    latency_ms = (time.perf_counter() - t0) * 1000.0
    evidence, excluded_count = _normalize_count_results(raw)
    notes = f"Q2 count_where: field={params['field']}"
    if dropped:
        notes += f", constraints not supported by Q2 and ignored: {'; '.join(dropped)}"
    if excluded_count > 0:
        notes += f", excluded_low_confidence={excluded_count}"
    return AgentResult(
        evidence=evidence,
        chunks_returned=len(evidence),
        citations_count=len(evidence),
        latency_ms=latency_ms,
        notes=notes,
    )


def _run_argmax(
    client: TigerGraphClient,
    intent: IntentSchema,
    anchors: ResolvedAnchors,
) -> AgentResult:
    """Execute Q3: argmax(...)"""
    t0 = time.perf_counter()
    params = {
        "anchor_sport": anchors.sport or "",
        "anchor_games": anchors.games or "",
        "anchor_venue": anchors.venue or "",
        "field": intent.target_field or "gold",
    }
    try:
        raw = client._run_query("q3_argmax", params)
    except Exception as e:
        logger.error("Q3 argmax failed: %s", e)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return AgentResult(error=str(e), latency_ms=latency_ms, notes=f"Q3 error: {e}")

    latency_ms = (time.perf_counter() - t0) * 1000.0
    evidence = _normalize_argmax_results(raw)
    return AgentResult(
        evidence=evidence,
        chunks_returned=len(evidence),
        citations_count=len(evidence),
        latency_ms=latency_ms,
        notes=f"Q3 argmax: field={params['field']}, top-3 results",
    )


def _normalize_count_results(raw: Any) -> tuple[list[dict[str, Any]], int]:
    """Q2's count row first, then the counted events it names (capped at
    MAX_COUNT_MEMBERS) so the answer can cite them. The count is Q2's, never
    the number of member rows."""
    results: list[dict[str, Any]] = []
    excluded_count = 0
    if not raw or not isinstance(raw, list):
        return results, excluded_count
    members: list[dict[str, Any]] = []
    for item in raw:
        attrs = item.get("attributes", item)
        if "members" in attrs:
            members.extend(m for m in attrs.get("members") or [] if isinstance(m, dict))
            continue
        if "excluded_count" in attrs:
            excluded_count = attrs["excluded_count"]
        results.append({
            "count": attrs.get("count", attrs.get("count_value", attrs.get("value", 0))),
            "doc_id": attrs.get("doc_id", attrs.get("event_id", "")),
            "source": "aggregation_count",
        })
    members.sort(key=lambda m: str(m.get("event_id", "")))
    if results and len(members) > MAX_COUNT_MEMBERS:
        results[0]["counted_events_listed"] = f"{MAX_COUNT_MEMBERS} of {len(members)}"
    for m in members[:MAX_COUNT_MEMBERS]:
        results.append({
            "counted_event": m.get("event_name", ""),
            "title": m.get("title", ""),
            "event_id": m.get("event_id", ""),
            "doc_id": m.get("doc_id", ""),
            "source": "aggregation_count",
        })
    return results, excluded_count


def _normalize_argmax_results(raw: Any) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if not raw or not isinstance(raw, list):
        return results
    for item in raw:
        attrs = item.get("attributes", item)
        results.append({
            "event_id": attrs.get("event_id", item.get("v_id", "")),
            "event_name": attrs.get("event_name", ""),
            "title": attrs.get("title", ""),
            "value": attrs.get("value", attrs.get("win_value", "")),
            "doc_id": attrs.get("doc_id", ""),
            "source": "aggregation_argmax",
        })
    return results
