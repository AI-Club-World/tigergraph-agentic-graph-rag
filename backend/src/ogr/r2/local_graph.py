"""The ten Round-2 tools in pure Python over `CorpusModel`.

Same parameters and same row shapes as the installed GSQL queries
(`graph/queries/r2_*.gsql`, via `TigerGraphR2`), so tests and offline checks
exercise the tool semantics without a database. The GSQL cannot fold accents
or punctuation, so where it compares lower-cased raw text this module compares
normalized text (`common.names.normalize_answer`); the difference only shows
for accents and apostrophes in a query, and `TigerGraphR2` straightens the
apostrophes before the query runs.

Matching rules (all case-insensitive, deterministic):
- `sport`: exact on the sport named in the event page title; "" = any.
- `year`: the Games year; 0 = any. `season`: "Summer"/"Winter"; "" = any.
- `event_contains` / `name_contains` / `value_contains`: substring of the
  normalized text that starts at a word boundary, so "men's 100 metres" does
  not match inside "women's 100 metres". Events match on the infobox event
  name OR the page title.
- Counts of medals are per medal awarded (event, medal kind, place), so a
  relay team is one medal and two bronzes of one event are two.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from ogr.common.names import normalize_answer
from ogr.r2.corpus_model import CorpusModel, Event, contains_norm
from ogr.r2.graph_backend import (
    MAX_ENTITY_ROWS,
    QUERY_NAMES,
    QueryResult,
    chunk_rows_within_budget,
    instant_key,
    medallist_rows,
    trim_text,
)

__all__ = ["LocalR2Graph"]

MEDALS = ("gold", "silver", "bronze")


class LocalR2Graph:
    def __init__(self, model: CorpusModel) -> None:
        self.model = model
        self._events = model.event_by_id()
        self._chunks_by_doc: dict[str, list[Any]] = {}
        for chunk in model.chunks:
            self._chunks_by_doc.setdefault(chunk.doc_id, []).append(chunk)
        self._facts_by_entity: dict[str, list[Any]] = {}
        for fact in model.facts:
            self._facts_by_entity.setdefault(fact.entity_id, []).append(fact)

    # --- plumbing ---------------------------------------------------------

    def _run(self, tool: str, params: dict[str, Any],
             body: Callable[[], list[dict[str, Any]]]) -> QueryResult:
        started = time.perf_counter()
        rows = body()
        return QueryResult(QUERY_NAMES[tool], params, rows, round((time.perf_counter() - started) * 1000, 1))

    def _select(self, sport: str = "", year: int = 0, season: str = "",
                event_contains: str = "") -> list[Event]:
        needle = normalize_answer(event_contains)
        out = []
        for e in self.model.events:
            if sport and e.sport.lower() != sport.strip().lower():
                continue
            if year and e.year != year:
                continue
            if season and e.season.lower() != season.strip().lower():
                continue
            if needle and not self._name_matches(e, needle):
                continue
            out.append(e)
        return out

    @staticmethod
    def _event_key(e: Event) -> tuple[int, str, str]:
        return (e.year, e.sport.lower(), e.title)

    # --- tools ------------------------------------------------------------

    def find_events(self, sport: str = "", year: int = 0, season: str = "",
                    event_contains: str = "") -> QueryResult:
        params = {"sport": sport, "year": int(year), "season": season, "event_contains": event_contains}

        def body() -> list[dict[str, Any]]:
            rows = []
            for e in sorted(self._select(sport, int(year), season, event_contains), key=self._event_key):
                rows.append({
                    "event_id": e.event_id, "doc_id": e.doc_id, "title": e.title, "event_name": e.event_name,
                    "sport": e.sport, "games": e.games_id, "year": e.year, "season": e.season,
                    "date_text": e.date_text, "venue": e.venue, "competitors": e.competitors,
                    "nations": e.nations, **medallist_rows(sorted(
                        e.medallists, key=lambda m: (m.medal, m.place, m.name))),
                    "synthetic": e.synthetic,
                })
            return rows

        return self._run("find_events", params, body)

    def medals_by_nation(self, sport: str = "", year: int = 0, season: str = "",
                         medal: str = "") -> QueryResult:
        params = {"sport": sport, "year": int(year), "season": season, "medal": medal}

        def body() -> list[dict[str, Any]]:
            wanted = medal.strip().lower()
            awarded: dict[str, set[tuple[str, str, int]]] = {}
            titles: dict[str, dict[str, str]] = {}
            for e in self._select(sport, int(year), season):
                for m in e.medallists:
                    if not m.noc or (wanted and m.medal != wanted):
                        continue
                    awarded.setdefault(m.noc, set()).add((e.event_id, m.medal, m.place))
                    titles.setdefault(m.noc, {})[e.doc_id] = e.title
            rows = [{
                "noc": noc, "count": len(keys),
                "events": [{"title": t, "doc_id": d}
                           for d, t in sorted(titles[noc].items(), key=lambda x: (x[1], x[0]))],
            } for noc, keys in awarded.items()]
            return sorted(rows, key=lambda r: (-r["count"], r["noc"]))

        return self._run("medals_by_nation", params, body)

    def event_series(self, event_contains: str, sport: str = "", season: str = "") -> QueryResult:
        params = {"event_contains": event_contains, "sport": sport, "season": season}

        def body() -> list[dict[str, Any]]:
            needle = normalize_answer(event_contains)
            by_edition: dict[tuple[int, str], Event] = {}
            for e in sorted(self._select(sport, 0, season, event_contains), key=self._event_key):
                exact = e.event_norm == needle or e.title_norm.endswith(f" {needle}")
                key = (e.year, e.season)
                held = by_edition.get(key)
                if held is None or (exact and not (held.event_norm == needle)):
                    by_edition[key] = e
            return [{
                "year": e.year, "season": e.season, "event_id": e.event_id, "title": e.title,
                "doc_id": e.doc_id, "event_name": e.event_name, "nations": e.nations,
                "competitors": e.competitors, "gold": medallist_rows(e.medallists)["gold"],
            } for _, e in sorted(by_edition.items())]

        return self._run("event_series", params, body)

    def athlete_medals(self, name: str) -> QueryResult:
        params = {"name": name}

        def body() -> list[dict[str, Any]]:
            needle = normalize_answer(name)
            ids = [needle] if needle in self.model.athletes else [
                a for a in sorted(self.model.athletes) if contains_norm(a, needle)] if needle else []
            rows = []
            for edge in self.model.won:
                if edge.athlete_id not in ids:
                    continue
                e = self._events[edge.event_id]
                rows.append({
                    "athlete": self.model.athletes[edge.athlete_id].name, "athlete_id": edge.athlete_id,
                    "medal": edge.medal, "noc": edge.noc, "event": e.title, "event_name": e.event_name,
                    "sport": e.sport, "year": e.year, "doc_id": e.doc_id,
                })
            return sorted(rows, key=lambda r: (r["year"], r["event"], r["medal"]))

        return self._run("athlete_medals", params, body)

    def repeat_winners(self, sport: str = "", medal: str = "gold", season: str = "") -> QueryResult:
        params = {"sport": sport, "medal": medal, "season": season}

        def body() -> list[dict[str, Any]]:
            wanted = medal.strip().lower()
            groups: dict[tuple, dict[int, tuple[Event, str]]] = {}
            for e in self._select(sport, 0, season):
                for m in e.medallists:
                    if wanted and m.medal != wanted:
                        continue
                    key = (m.athlete_id, e.sport.lower(), e.event_key, m.medal)
                    groups.setdefault(key, {}).setdefault(e.year, (e, m.name))
            rows = []
            for (_, _, _, kind), by_year in groups.items():
                if len(by_year) < 2:
                    continue
                # Shown as the latest edition names it (infobox names drift between years).
                latest, name = by_year[max(by_year)]
                rows.append({
                    "athlete": name, "event_name": latest.event_name, "sport": latest.sport, "medal": kind,
                    "years": sorted(by_year), "doc_ids": [by_year[y][0].doc_id for y in sorted(by_year)],
                })
            return sorted(rows, key=lambda r: (r["athlete"], r["sport"], r["event_name"], r["medal"]))

        return self._run("repeat_winners", params, body)

    def _entity_row(self, entity: Any) -> dict[str, Any]:
        facts, numeric = {}, {}
        for f in sorted(self._facts_by_entity.get(entity.entity_id, []), key=lambda f: f.predicate):
            facts[f.predicate] = f.value_text
            if f.value_num is not None:
                numeric[f.predicate] = {"value": f.value_num, "note": f.note}
        return {"entity_id": entity.entity_id, "name": entity.name, "entity_type": entity.entity_type,
                "doc_id": entity.doc_id, "facts": facts, "numeric": numeric}

    def entity_facts(self, name_contains: str, entity_type: str = "") -> QueryResult:
        params = {"name_contains": name_contains, "entity_type": entity_type}

        def body() -> list[dict[str, Any]]:
            needle = normalize_answer(name_contains)
            rows = [
                self._entity_row(en) for en in self.model.entities
                if (not entity_type or en.entity_type.lower() == entity_type.strip().lower())
                and contains_norm(normalize_answer(en.name), needle)
            ]
            return sorted(rows, key=lambda r: (r["name"], r["doc_id"]))

        return self._run("entity_facts", params, body)

    def find_entities(self, entity_type: str = "", predicate: str = "",
                      value_contains: str = "") -> QueryResult:
        params = {"entity_type": entity_type, "predicate": predicate, "value_contains": value_contains}

        def body() -> list[dict[str, Any]]:
            wanted_pred = predicate.strip().lower()
            needle = normalize_answer(value_contains)
            rows = []
            for en in self.model.entities:
                if entity_type and en.entity_type.lower() != entity_type.strip().lower():
                    continue
                for f in self._facts_by_entity.get(en.entity_id, []):
                    key = f.predicate.lower()
                    # `predecessor` also finds `predecessor1`, `predecessor2`, ...
                    if wanted_pred and key != wanted_pred and key.rstrip("0123456789") != wanted_pred:
                        continue
                    if needle and needle not in normalize_answer(f.value_text):
                        continue
                    rows.append(self._entity_row(en))
                    break
            return sorted(rows, key=lambda r: (r["name"], r["doc_id"]))[:MAX_ENTITY_ROWS]

        return self._run("find_entities", params, body)

    def _name_matches(self, e: Event, needle: str) -> bool:
        return contains_norm(e.event_norm, needle) or contains_norm(e.title_norm, needle)

    def source_records(self, event_contains: str = "", year: int = 0) -> QueryResult:
        params = {"event_contains": event_contains, "year": int(year)}

        def body() -> list[dict[str, Any]]:
            needle = normalize_answer(event_contains)
            linked: dict[str, set[str]] = {}
            for link in self.model.links:
                e = self._events[link.event_id]
                if (year and e.year != year) or (needle and not self._name_matches(e, needle)):
                    continue
                linked.setdefault(link.record_id, set()).add(e.doc_id)
            rows = []
            for r in self.model.sources:
                # With no year, a record that itself contains the phrase also counts, so an
                # unlinked record is still found; with neither filter every record does.
                body_norm = normalize_answer(f"{r.title} {r.text}")
                textual = needle and not year and contains_norm(body_norm, needle)
                if not (r.doc_id in linked or textual or (not needle and not year)):
                    continue
                rows.append({
                    "doc_id": r.doc_id, "title": r.title, "source_name": r.source_name,
                    "authority": r.authority, "published_at": r.published_at,
                    "published_text": r.published_text, "text": r.text,
                    "events": sorted(linked.get(r.doc_id, set())),
                })
            return sorted(rows, key=lambda r: (instant_key(r["published_at"]), r["doc_id"]))

        return self._run("source_records", params, body)

    def text_search(self, terms: list[str], limit: int = 10) -> QueryResult:
        params = {"terms": list(terms), "limit": int(limit)}

        def body() -> list[dict[str, Any]]:
            wanted = [t.lower() for t in terms if t.strip()]
            if not wanted:
                return []
            hits = [c for c in self.model.chunks if all(t in c.text.lower() for t in wanted)]
            hits.sort(key=lambda c: (c.doc_id, c.seq))
            return [{
                "doc_id": c.doc_id, "title": self.model.titles.get(c.doc_id, ""), "chunk_id": c.chunk_id,
                "seq": c.seq, "text": trim_text(c.text),
            } for c in hits[:max(0, int(limit))]]

        return self._run("text_search", params, body)

    def read_document(self, doc_id: str, max_chars: int = 6000) -> QueryResult:
        params = {"doc_id": doc_id}

        def body() -> list[dict[str, Any]]:
            title = self.model.titles.get(doc_id, "")
            chunks = [{"doc_id": doc_id, "title": title, "chunk_id": c.chunk_id, "seq": c.seq, "text": c.text}
                      for c in self._chunks_by_doc.get(doc_id, [])]
            return chunk_rows_within_budget(chunks, max_chars)

        return self._run("read_document", params, body)
