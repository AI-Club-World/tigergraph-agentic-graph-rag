"""The Round-2 tools as LLM tool specs and the executor that runs them (SOLUTION-DESIGN §3).

`run_tool` calls the R2Graph method, records the call in the trace as it happens (a `tg` step,
which also writes the TigerGraph query log; a LocalR2Graph call is recorded with `tigergraph`
false and never logged) and returns a compact JSON string for the model: empty fields dropped,
rows and text capped, truncation stated so the model can narrow the query. `rank_rows` is a
deterministic local helper over an earlier result, recorded as a `local` step.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ogr.r2.graph_backend import QueryResult, R2Graph, series_extremes
from ogr.r2.local_graph import LocalR2Graph
from ogr.r2.trace import TraceRecorder

__all__ = ["TOOL_SPECS", "FINISH_SPEC", "TOOL_NAMES", "ToolContext", "run_tool", "compact_result",
           "MAX_ROWS", "TEXT_CAP", "MAX_CHARS"]

MAX_ROWS = 60       # rows of one result the model sees
TEXT_CAP = 2000     # characters of one text field the model sees
MAX_CHARS = 24000   # characters of one tool result (about 6k tokens)


def _obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or []}


_STR = {"type": "string"}
_SEASON = {"type": "string", "enum": ["Summer", "Winter", ""],
           "description": "Summer, Winter or empty for both"}
_YEAR = {"type": "integer", "description": "Games year, 0 for any"}
_MEDAL = {"type": "string", "enum": ["gold", "silver", "bronze", ""]}

_SPECS: list[dict[str, Any]] = [
    {"name": "find_events",
     "description": "List Olympic events (one row per event): medallists with NOCs, nations, competitors, "
                    "venue, date. Use for the results or details of events or Games, filtered by sport, "
                    "year, season or event-name text. Includes fictional events (synthetic=true).",
     "parameters": _obj({"sport": _STR, "year": _YEAR, "season": _SEASON, "event_contains": _STR})},
    {"name": "medals_by_nation",
     "description": "Medal counts per nation (NOC), highest first, with the events behind each count. "
                    "Use to compare nations or find who won most or fewest.",
     "parameters": _obj({"sport": _STR, "year": _YEAR, "season": _SEASON, "medal": _MEDAL})},
    {"name": "event_series",
     "description": "One row per edition of an event across Games (year, nations, competitors, gold "
                    "medallists) plus max and min over editions. Use for how something changed over time.",
     "parameters": _obj({"event_contains": _STR, "sport": _STR, "season": _SEASON}, ["event_contains"])},
    {"name": "athlete_medals",
     "description": "Every medal of one athlete with event, year and doc_id. Use for an athlete's career.",
     "parameters": _obj({"name": _STR}, ["name"])},
    {"name": "repeat_winners",
     "description": "Athletes who won the same event at two or more Games, with years and doc_ids.",
     "parameters": _obj({"sport": _STR, "medal": _MEDAL, "season": _SEASON})},
    {"name": "entity_facts",
     "description": "Infobox facts of non-Olympic pages (films, office holders, people, ...) found by name: "
                    "{field: value} per entity.",
     "parameters": _obj({"name_contains": _STR,
                         "entity_type": {**_STR, "description": "e.g. film, officeholder"}},
                        ["name_contains"])},
    {"name": "find_entities",
     "description": "Find non-Olympic entities by an infobox field and a value substring; returns all their "
                    "facts. Use to list or compare entities that meet a condition.",
     "parameters": _obj({"entity_type": _STR, "predicate": {**_STR, "description": "infobox field name"},
                         "value_contains": _STR})},
    {"name": "source_records",
     "description": "Dated source records (scoreboards, notices, schedules, bulletins, news, emails, ...) "
                    "about fictional events: source name, authority class, publication time, full text. "
                    "Use when sources may disagree or change over time; compare authority and time.",
     "parameters": _obj({"event_contains": _STR, "year": _YEAR})},
    {"name": "text_search",
     "description": "Chunks of article text containing ALL the given terms (case-insensitive). Use for "
                    "reasons, background and facts stated only in prose.",
     "parameters": _obj({"terms": {"type": "array", "items": _STR}, "limit": {"type": "integer"}},
                        ["terms"])},
    {"name": "read_document",
     "description": "Read one document's text in order by doc_id, to check details a row does not show.",
     "parameters": _obj({"doc_id": _STR, "max_chars": {"type": "integer"}}, ["doc_id"])},
    {"name": "rank_rows",
     "description": "Sort rows of an earlier tool result locally by a field (dotted path; a list counts as "
                    "its length) and keep the top n. Use for most/fewest or ordering instead of doing it "
                    "by eye.",
     "parameters": _obj({"result_id": _STR, "field": _STR,
                         "order": {"type": "string", "enum": ["asc", "desc"]},
                         "top_n": {"type": "integer"}}, ["result_id", "field"])},
]

FINISH_SPEC: dict[str, Any] = {
    "name": "finish",
    "description": "Give the final answer. Call exactly once when done.",
    "parameters": _obj({
        "status": {"type": "string", "enum": ["answered", "partial", "not_in_corpus"]},
        "answer": {"description": "Plain text, or JSON (object/array) for lists and records. Omit when "
                                  "not_in_corpus."},
        "explanation": {"type": "string", "description": "Short account of how the answer was reached"},
        "citations": {"type": "array", "items": _STR, "description": "doc_ids supporting the answer"},
    }, ["status", "explanation"]),
}

TOOL_SPECS = [{"type": "function", "function": s} for s in _SPECS]
TOOL_NAMES = [s["name"] for s in _SPECS]
_SCHEMAS = {s["name"]: s["parameters"] for s in _SPECS}


@dataclass
class ToolContext:
    """What one question's tool calls leave behind: earlier results (for rank_rows) and the doc_ids
    the model has actually been shown."""

    results: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    seen_doc_ids: list[str] = field(default_factory=list)

    def next_id(self) -> str:
        return f"r{len(self.results) + 1}"

    def note_docs(self, value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "doc_id" and isinstance(item, str):
                    if item and item not in self.seen_doc_ids:
                        self.seen_doc_ids.append(item)
                elif key == "doc_ids" and isinstance(item, list):
                    for d in item:
                        if isinstance(d, str) and d and d not in self.seen_doc_ids:
                            self.seen_doc_ids.append(d)
                else:
                    self.note_docs(item)
        elif isinstance(value, list):
            for item in value:
                self.note_docs(item)


# --- compact output ------------------------------------------------------------

def _clean(value: Any, state: dict[str, bool]) -> Any:
    if isinstance(value, dict):
        out = {k: _clean(v, state) for k, v in value.items()}
        return {k: v for k, v in out.items() if v not in (None, "", [], {}, 0, False)}
    if isinstance(value, list):
        return [_clean(v, state) for v in value]
    if isinstance(value, str) and len(value) > TEXT_CAP:
        state["text"] = True
        return value[:TEXT_CAP].rstrip() + " ...[cut]"
    return value


def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)


def compact_result(rows: list[dict[str, Any]], result_id: str, extra: dict[str, Any] | None = None,
                   max_rows: int = MAX_ROWS) -> tuple[str, list[dict[str, Any]]]:
    """(JSON text for the model, the rows it contains). Truncation is stated in the text."""
    state = {"text": False}
    total = len(rows)
    shown = [_clean(r, state) for r in rows[:max_rows]]
    while True:
        head: dict[str, Any] = {"result_id": result_id, "total_rows": total, "shown_rows": len(shown)}
        if extra:
            head.update(extra)
        notes = []
        if len(shown) < total:
            notes.append(f"showing the first {len(shown)} of {total} rows; narrow the query or use rank_rows")
        if state["text"]:
            notes.append(f"long text fields cut at {TEXT_CAP} characters; use read_document for the rest")
        if notes:
            head["truncated"] = "; ".join(notes)
        text = _dump({**head, "rows": shown})
        if len(text) <= MAX_CHARS or len(shown) <= 1:
            return text, shown
        shown = shown[: max(1, int(len(shown) * 0.7))]


# --- executor ------------------------------------------------------------------

def _coerce(name: str, args: dict[str, Any]) -> tuple[dict[str, Any], str]:
    schema = _SCHEMAS[name]
    props = schema["properties"]
    out: dict[str, Any] = {}
    for key, spec in props.items():
        if key not in args or args[key] is None:
            continue
        value = args[key]
        kind = spec.get("type")
        try:
            if kind == "integer":
                value = int(value)
            elif kind == "string":
                value = str(value)
            elif kind == "array":
                value = [str(v) for v in (value if isinstance(value, list) else [value])]
        except (TypeError, ValueError):
            return {}, f"parameter {key} must be {kind}"
        out[key] = value
    missing = [k for k in schema["required"] if k not in out or out[k] in ("", [])]
    if missing:
        return {}, "missing required parameter: " + ", ".join(missing)
    return out, ""


def is_tigergraph(graph: Any) -> bool:
    return not isinstance(graph, LocalR2Graph)


def _dotted(row: Any, path: str) -> Any:
    for part in path.split("."):
        row = row.get(part) if isinstance(row, dict) else None
    if isinstance(row, list):
        return len(row)
    return row


def _rank(ctx: ToolContext, args: dict[str, Any], trace: TraceRecorder) -> str:
    started = time.perf_counter()
    rid = args["result_id"]
    rows = ctx.results.get(rid)
    if rows is None:
        return _dump({"error": f"unknown result_id {rid}; known: {sorted(ctx.results)}"})
    field_name = args["field"]
    desc = args.get("order", "desc") != "asc"
    keyed = [(r, _dotted(r, field_name)) for r in rows]
    present = [(r, v) for r, v in keyed if isinstance(v, int | float | str) and not isinstance(v, bool)]
    if present and all(isinstance(v, int | float) for _, v in present):
        present.sort(key=lambda p: p[1], reverse=desc)  # stable: ties keep the original order
    else:
        present.sort(key=lambda p: str(p[1]).lower(), reverse=desc)
    ranked = [r for r, _ in present]
    top = int(args.get("top_n") or 10)
    new_id = ctx.next_id()
    ctx.results[new_id] = ranked
    info = {"ranked_by": field_name, "order": "desc" if desc else "asc",
            "rows_without_field": len(rows) - len(ranked)}
    text, shown = compact_result(ranked[:max(1, top)], new_id, info)
    ctx.note_docs(shown)
    trace.local("rank_rows", int((time.perf_counter() - started) * 1000),
                note=f"{rid} by {field_name} {'desc' if desc else 'asc'}, top {top} of {len(ranked)}")
    return text


def run_tool(graph: R2Graph, name: str, args: dict[str, Any] | None, trace: TraceRecorder,
             ctx: ToolContext | None = None) -> str:
    """Run one tool call; return the compact JSON string the model sees. Never raises."""
    ctx = ctx if ctx is not None else ToolContext()
    if name not in _SCHEMAS:
        return _dump({"error": f"unknown tool {name}", "tools": TOOL_NAMES})
    params, problem = _coerce(name, args if isinstance(args, dict) else {})
    if problem:
        return _dump({"error": problem})
    if name == "rank_rows":
        return _rank(ctx, params, trace)

    started_at = datetime.now(UTC)
    t0 = time.perf_counter()
    try:
        result: QueryResult = getattr(graph, name)(**params)
    except Exception as e:  # the tool failed: record it, tell the model, keep going
        ms = int((time.perf_counter() - t0) * 1000)
        error = f"{type(e).__name__}: {e}"[:300]
        _record(graph, trace, name, name, params, 0, ms, started_at, error)
        return _dump({"error": f"{name} failed: {error}"})
    error = result.error or ""
    _record(graph, trace, name, result.query, result.params, result.row_count, int(round(result.ms)),
            started_at, error)
    rid = ctx.next_id()
    ctx.results[rid] = result.rows
    extra: dict[str, Any] = {}
    if name == "event_series" and result.rows:
        extra["extremes"] = {"nations": series_extremes(result.rows, "nations"),
                             "competitors": series_extremes(result.rows, "competitors")}
    if error:
        extra["error"] = error[:300]
    text, shown = compact_result(result.rows, rid, extra)
    ctx.note_docs(shown)
    return text


def _record(graph: Any, trace: TraceRecorder, tool: str, query: str, params: Any, rows: int, ms: int,
            started_at: datetime, error: str) -> None:
    if is_tigergraph(graph):
        trace.tg(tool, query, params, rows, ms, ok=not error, error=error or None, started_at=started_at,
                 note=("error: " + error) if error else None)
    else:
        trace.local_query(tool, query, params, rows, ms, note=("error: " + error) if error else None)
