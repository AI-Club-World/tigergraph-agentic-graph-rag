"""The ten Round-2 graph tools behind one interface (SOLUTION-DESIGN §3).

`R2Graph` is what the agent calls. Two implementations return the same rows:
`LocalR2Graph` (pure Python over the parsed corpus, for tests and offline
checks) and `TigerGraphR2` (below), one installed GSQL query per tool.

Every method returns a `QueryResult` instead of bare rows: the agent layer
writes `query`, `params`, `len(rows)` and `ms` into the trace step and the
TigerGraph query log, and the numbers must come from the call that ran, not be
rebuilt afterwards (brief: traces are "written by your code as it runs").
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from ogr.common.names import normalize_answer

__all__ = [
    "QueryResult", "R2Graph", "TigerGraphR2", "QUERY_NAMES", "TEXT_TRIM", "MAX_ENTITY_ROWS",
    "trim_text", "chunk_rows_within_budget", "instant_key", "series_extremes", "medallist_rows",
]

TEXT_TRIM = 2500  # characters of one chunk a search row carries
MAX_ENTITY_ROWS = 200  # find_entities with no filter would otherwise return every film

QUERY_NAMES = {
    "find_events": "r2_find_events",
    "medals_by_nation": "r2_medals_by_nation",
    "event_series": "r2_event_series",
    "athlete_medals": "r2_athlete_medals",
    "repeat_winners": "r2_repeat_winners",
    "entity_facts": "r2_entity_facts",
    "find_entities": "r2_find_entities",
    "source_records": "r2_source_records",
    "text_search": "r2_text_search",
    "read_document": "r2_read_document",
}


@dataclass
class QueryResult:
    """One tool call: the installed query's name, the parameters it ran with,
    its rows and how long it took."""

    query: str
    params: dict[str, Any]
    rows: list[dict[str, Any]]
    ms: float
    error: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def row_count(self) -> int:
        return len(self.rows)


class R2Graph(Protocol):
    def find_events(self, sport: str = "", year: int = 0, season: str = "",
                    event_contains: str = "") -> QueryResult: ...

    def medals_by_nation(self, sport: str = "", year: int = 0, season: str = "",
                         medal: str = "") -> QueryResult: ...

    def event_series(self, event_contains: str, sport: str = "", season: str = "") -> QueryResult: ...

    def athlete_medals(self, name: str) -> QueryResult: ...

    def repeat_winners(self, sport: str = "", medal: str = "gold", season: str = "") -> QueryResult: ...

    def entity_facts(self, name_contains: str, entity_type: str = "") -> QueryResult: ...

    def find_entities(self, entity_type: str = "", predicate: str = "",
                      value_contains: str = "") -> QueryResult: ...

    def source_records(self, event_contains: str = "", year: int = 0) -> QueryResult: ...

    def text_search(self, terms: list[str], limit: int = 10) -> QueryResult: ...

    def read_document(self, doc_id: str, max_chars: int = 6000) -> QueryResult: ...


# --- helpers shared by both implementations --------------------------------

def trim_text(text: str, limit: int = TEXT_TRIM) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + " ..."


CHUNK_OVERLAP_WORDS = 50
CHUNK_WORDS = 300


def chunk_rows_within_budget(chunks: list[dict[str, Any]], max_chars: int) -> list[dict[str, Any]]:
    """Chunks of one document, in order, as a continuous text within a budget.

    Consecutive chunks overlap by 50 words (the Round-1 chunker), so reading
    them in order would repeat that text; the repeated words are dropped from
    every chunk that follows a full-size one. The last row that fits is cut at
    the budget and flagged `truncated`.
    """
    rows: list[dict[str, Any]] = []
    used = 0
    previous_full = False
    for chunk in sorted(chunks, key=lambda c: c["seq"]):
        text = chunk["text"]
        if previous_full:
            text = " ".join(text.split()[CHUNK_OVERLAP_WORDS:])
        previous_full = len(chunk["text"].split()) >= CHUNK_WORDS
        row = {**chunk, "text": text, "truncated": False}
        if used + len(text) > max_chars:
            room = max_chars - used
            if room > 0:
                row["text"] = text[:room].rstrip() + " ..."
                row["truncated"] = True
                rows.append(row)
            elif rows:
                rows[-1]["truncated"] = True
            break
        used += len(text)
        rows.append(row)
    return rows


def instant_key(iso: str) -> tuple[int, float]:
    """Sort key for an ISO 8601 stamp with offset: by instant, not by string,
    because the offsets differ (PDT and CET records). Unparseable sorts last."""
    try:
        return (0, datetime.fromisoformat(iso).timestamp())
    except ValueError:
        return (1, 0.0)


def series_extremes(rows: list[dict[str, Any]], key: str = "nations") -> dict[str, Any]:
    """Max and min of `key` over an event series (earliest year wins a tie, the
    same rule the public answers use). Rows with the value 0 (not recorded) are
    skipped."""
    values = [(r[key], r["year"]) for r in rows if r.get(key)]
    if not values:
        return {"max_year": None, "max": None, "min_year": None, "min": None}
    top = max(values, key=lambda v: (v[0], -v[1]))
    low = min(values, key=lambda v: (v[0], v[1]))
    return {"max_year": top[1], "max": top[0], "min_year": low[1], "min": low[0]}


def medallist_rows(medallists: list[Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {"gold": [], "silver": [], "bronze": []}
    for m in medallists:
        out[m.medal].append({"name": m.name, "noc": m.noc})
    return out


# --- TigerGraph implementation ----------------------------------------------

_RS = "\n"   # record separator inside an encoded string field
_FS = "\t"   # field separator


def _decode(text: Any) -> list[list[str]]:
    """`"a\\tb\\nc\\td\\n"` -> [["a","b"],["c","d"]]. GSQL tuples cannot hold
    lists, so a nested list travels as one delimited string field."""
    if not text:
        return []
    return [line.split(_FS) for line in str(text).split(_RS) if line]


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _year(value: Any) -> int:
    """A Games year; 0 when the event has no AT_GAMES edge (MinAccum<INT> then
    still holds its initial INT_MAX)."""
    year = _int(value)
    return year if 0 < year < 3000 else 0


def _medal_lists(encoded: Any) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = {"gold": [], "silver": [], "bronze": []}
    for parts in sorted(_decode(encoded), key=lambda p: (p[0], _int(p[3]) if len(p) > 3 else 0, p[1])):
        if len(parts) >= 3 and parts[0] in out:
            out[parts[0]].append({"name": parts[1], "noc": parts[2]})
    return out


class TigerGraphR2:
    """The ten tools as installed GSQL queries (graph/queries/r2_*.gsql).

    Rows come back through `TigerGraphClient._run_query`, which unwraps the one
    list a query prints, and are mapped to the dicts `LocalR2Graph` returns:
    text for missing strings, 0 for missing numbers, nested lists decoded.
    A query that failed returns no rows and `error` set from the client's
    error buffer, so an empty answer is never mistaken for "nothing matched".
    """

    def __init__(self, client: Any) -> None:
        self.client = client

    def _call(self, tool: str, params: dict[str, Any], mapper: Callable[[dict[str, Any]], Any],
              post: Callable[[list[Any]], list[Any]] | None = None) -> QueryResult:
        query = QUERY_NAMES[tool]
        started = time.perf_counter()
        raw = self.client._run_query(query, params)
        ms = round((time.perf_counter() - started) * 1000, 1)
        errors = []
        drain = getattr(self.client, "drain_errors", None)
        if callable(drain):
            errors = [e for e in drain() if isinstance(e, str)]
        rows = [mapper(r) for r in raw if isinstance(r, dict)]
        if post:
            rows = post(rows)
        return QueryResult(query, params, rows, ms, error="; ".join(errors))

    def find_events(self, sport: str = "", year: int = 0, season: str = "",
                    event_contains: str = "") -> QueryResult:
        params = {"sport": sport, "year": int(year), "season": season, "event_contains": _q(event_contains)}

        def row(r: dict[str, Any]) -> dict[str, Any]:
            return {
                "event_id": r.get("event_id") or "", "doc_id": r.get("doc_id") or "",
                "title": r.get("title") or "", "event_name": r.get("event_name") or "",
                "sport": r.get("sport") or "", "games": r.get("games") or "", "year": _year(r.get("year")),
                "season": r.get("season") or "", "date_text": r.get("date_text") or "",
                "venue": r.get("venue") or "", "competitors": _int(r.get("competitors")),
                "nations": _int(r.get("nations")), **_medal_lists(r.get("medallists")),
                "synthetic": bool(r.get("synthetic")),
            }

        def ordered(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return sorted(rows, key=lambda r: (r["year"], r["sport"].lower(), r["title"]))

        return self._call("find_events", params, row, ordered)

    def medals_by_nation(self, sport: str = "", year: int = 0, season: str = "",
                         medal: str = "") -> QueryResult:
        params = {"sport": sport, "year": int(year), "season": season, "medal": medal.lower()}

        def row(r: dict[str, Any]) -> dict[str, Any]:
            events = sorted({(p[0], p[1]) for p in _decode(r.get("events")) if len(p) >= 2})
            return {"noc": r.get("noc") or "", "count": _int(r.get("medal_count")),
                    "events": [{"title": t, "doc_id": d} for t, d in events]}

        return self._call("medals_by_nation", params, row,
                          lambda rows: sorted(rows, key=lambda r: (-r["count"], r["noc"])))

    def event_series(self, event_contains: str, sport: str = "", season: str = "") -> QueryResult:
        params = {"event_contains": _q(event_contains), "sport": sport, "season": season}

        def row(r: dict[str, Any]) -> dict[str, Any]:
            return {
                "year": _year(r.get("year")), "season": r.get("season") or "",
                "event_id": r.get("event_id") or "",
                "title": r.get("title") or "", "doc_id": r.get("doc_id") or "",
                "event_name": r.get("event_name") or "", "nations": _int(r.get("nations")),
                "competitors": _int(r.get("competitors")), "exact": bool(r.get("exact")),
                "gold": _medal_lists(r.get("medallists"))["gold"],
            }

        def one_per_edition(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            best: dict[tuple[int, str], dict[str, Any]] = {}
            for r in sorted(rows, key=lambda r: (r["year"], not r["exact"], r["title"])):
                best.setdefault((r["year"], r["season"]), r)
            return [{k: v for k, v in r.items() if k != "exact"} for _, r in sorted(best.items())]

        return self._call("event_series", params, row, one_per_edition)

    def athlete_medals(self, name: str) -> QueryResult:
        params = {"name": normalize_answer(name)}

        def row(r: dict[str, Any]) -> dict[str, Any]:
            return {
                "athlete": r.get("athlete") or "", "athlete_id": r.get("athlete_id") or "",
                "medal": r.get("medal") or "", "noc": r.get("noc") or "", "event": r.get("title") or "",
                "event_name": r.get("event_name") or "", "sport": r.get("sport") or "",
                "year": _year(r.get("year")), "doc_id": r.get("doc_id") or "",
            }

        return self._call("athlete_medals", params, row,
                          lambda rows: sorted(rows, key=lambda r: (r["year"], r["event"], r["medal"])))

    def repeat_winners(self, sport: str = "", medal: str = "gold", season: str = "") -> QueryResult:
        params = {"sport": sport, "medal": medal.lower(), "season": season}

        def flat(r: dict[str, Any]) -> dict[str, Any]:
            keys = ("athlete", "event_name", "event_key", "sport", "medal", "doc_id")
            return {k: r.get(k) or "" for k in keys} | {
                "year": _year(r.get("year"))}

        def group(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            groups: dict[tuple, dict[str, Any]] = {}
            for r in sorted(rows, key=lambda r: r["year"]):
                key = (r["athlete"], r["sport"].lower(), r["event_key"], r["medal"])
                g = groups.setdefault(key, {
                    "athlete": r["athlete"], "event_name": r["event_name"], "sport": r["sport"],
                    "medal": r["medal"], "years": [], "doc_ids": [],
                })
                if r["year"] not in g["years"]:
                    g["years"].append(r["year"])
                    g["doc_ids"].append(r["doc_id"])
                    g["event_name"] = r["event_name"]  # rows run oldest first: the latest name wins
            return sorted((g for g in groups.values() if len(g["years"]) >= 2),
                          key=lambda g: (g["athlete"], g["sport"], g["event_name"], g["medal"]))

        return self._call("repeat_winners", params, flat, group)

    def entity_facts(self, name_contains: str, entity_type: str = "") -> QueryResult:
        params = {"name_contains": _q(name_contains), "entity_type": entity_type.lower()}
        return self._call("entity_facts", params, _entity_row, _sort_entities)

    def find_entities(self, entity_type: str = "", predicate: str = "",
                      value_contains: str = "") -> QueryResult:
        wanted = predicate.strip().lower()
        params = {
            "entity_type": entity_type.lower(), "predicate": wanted, "value_contains": _q(value_contains),
            # GSQL cannot strip trailing digits, so the numbered forms are listed here.
            "predicate_variants": [wanted] + [f"{wanted}{i}" for i in range(1, 21)] if wanted else [],
        }
        return self._call("find_entities", params, _entity_row,
                          lambda rows: _sort_entities(rows)[:MAX_ENTITY_ROWS])

    def source_records(self, event_contains: str = "", year: int = 0) -> QueryResult:
        params = {"event_contains": _q(event_contains), "year": int(year)}

        def row(r: dict[str, Any]) -> dict[str, Any]:
            return {
                "doc_id": r.get("doc_id") or "", "title": r.get("title") or "",
                "source_name": r.get("source_name") or "", "authority": r.get("authority") or "",
                "published_at": r.get("published_at") or "", "published_text": r.get("published_text") or "",
                "text": r.get("text") or "",
                "events": sorted(e for e in str(r.get("events") or "").split(_RS) if e),
            }

        def ordered(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return sorted(rows, key=lambda r: (instant_key(r["published_at"]), r["doc_id"]))

        return self._call("source_records", params, row, ordered)

    def text_search(self, terms: list[str], limit: int = 10) -> QueryResult:
        # The tool's `limit` is the query's `max_rows` (LIMIT is a GSQL keyword).
        params = {"terms": [t.lower() for t in terms if t.strip()], "max_rows": int(limit)}

        def row(r: dict[str, Any]) -> dict[str, Any]:
            return {"doc_id": r.get("doc_id") or "", "title": r.get("title") or "",
                    "chunk_id": r.get("chunk_id") or "", "seq": _int(r.get("seq")),
                    "text": trim_text(r.get("text") or "")}

        def ordered(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return sorted(rows, key=lambda r: (r["doc_id"], r["seq"]))[:max(0, int(limit))]

        return self._call("text_search", params, row, ordered)

    def read_document(self, doc_id: str, max_chars: int = 6000) -> QueryResult:
        params = {"doc_id": doc_id}

        def row(r: dict[str, Any]) -> dict[str, Any]:
            return {"doc_id": r.get("doc_id") or "", "title": r.get("title") or "",
                    "chunk_id": r.get("chunk_id") or "", "seq": _int(r.get("seq")),
                    "text": r.get("text") or ""}

        def budgeted(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return chunk_rows_within_budget(rows, max_chars)

        return self._call("read_document", params, row, budgeted)


def _q(text: str) -> str:
    """A search phrase as the GSQL queries compare it: lower case, curly
    apostrophes straight. (Local matching also folds accents and punctuation;
    GSQL has no such function, so it compares the raw lower-cased text.)"""
    return (text or "").lower().replace("’", "'").replace("ʼ", "'").strip()


def _entity_row(r: dict[str, Any]) -> dict[str, Any]:
    facts: dict[str, str] = {}
    numeric: dict[str, dict[str, Any]] = {}
    for parts in sorted(_decode(r.get("facts"))):
        if len(parts) < 2:
            continue
        facts[parts[0]] = parts[1]
        if len(parts) >= 4 and parts[2] == "1":
            numeric[parts[0]] = {"value": float(parts[3] or 0), "note": parts[4] if len(parts) > 4 else ""}
    return {"entity_id": r.get("entity_id") or "", "name": r.get("name") or "",
            "entity_type": r.get("entity_type") or "", "doc_id": r.get("doc_id") or "",
            "facts": facts, "numeric": numeric}


def _sort_entities(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: (r["name"], r["doc_id"]))
