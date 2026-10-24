"""Entity linking agent for P3 Agentic GraphRAG pipeline.

Source spec: ARCHITECTURE-SPEC §4 · TECHNICAL-SPEC §2.2

Longest-match dictionary resolution against closed vocabularies:
  - 21 Games values (e.g. '2016-Summer', '2012-Summer')
  - 41 sports (derived from OlympicEvent title prefix)
  - 303 venues

Built once at startup from the graph (or a bundled vocabulary for offline testing).
Date anchors normalized via common/dates.py — the SAME normalizer ingestion uses.

Returns unresolved anchors explicitly (set to None) rather than guessing.
An unresolved venue is the eval-001 case that triggers the DP-2 fallback.

The ARCHITECTURE-SPEC §13 venue mitigation note: filtering venue+date by Games
year resolves nothing (23.0% → 22.9%). Real discriminators are sport and event
name. Where the question supplies neither, we return a disambiguation request.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from ogr.common.dates import normalize_date
from ogr.ingest.infobox import event_id_from_parts
from ogr.pipelines.p3_agentic.intent import IntentSchema

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bundled fallback vocabularies (populated from graph at startup)
# ---------------------------------------------------------------------------

# 21 distinct Games values matching AT_GAMES edge targets
DEFAULT_GAMES_VOCAB: list[str] = [
    "1896-Summer", "1900-Summer", "1904-Summer", "1906-Summer",
    "1908-Summer", "1912-Summer", "1920-Summer", "1924-Summer",
    "1928-Summer", "1932-Summer", "1936-Summer", "1948-Summer",
    "1952-Summer", "1956-Summer", "1960-Summer", "1964-Summer",
    "1968-Summer", "1972-Summer", "1976-Summer", "1980-Summer",
    "1984-Summer", "1988-Summer", "1992-Summer", "1996-Summer",
    "2000-Summer", "2004-Summer", "2008-Summer", "2012-Summer",
    "2016-Summer", "2020-Summer",
    # Winter
    "1924-Winter", "1928-Winter", "1932-Winter", "1936-Winter",
    "1948-Winter", "1952-Winter", "1956-Winter", "1960-Winter",
    "1964-Winter", "1968-Winter", "1972-Winter",
    "1976-Winter", "1980-Winter", "1984-Winter", "1988-Winter",
    "1992-Winter", "1994-Winter", "1998-Winter", "2002-Winter",
    "2006-Winter", "2010-Winter", "2014-Winter", "2018-Winter",
]


@dataclass
class ResolvedAnchors:
    """Anchor resolution result — unresolved fields remain None."""
    sport: str | None = None
    games: str | None = None
    venue: str | None = None
    title: str | None = None          # pass-through (no disambiguation needed)
    event_id: str | None = None       # pass-through
    date_year: int | None = None
    date_month: int | None = None
    date_day_start: int | None = None
    unresolved_fields: list[str] = field(default_factory=list)
    # Anchors the intent parse left out but the question states, linked from
    # the question text against the graph's own vocabularies ("venue=...").
    recovered: list[str] = field(default_factory=list)
    # The question as asked, for narrowing by a date written the way the
    # graph records it (narrow_to_date). Never used for routing.
    question: str | None = None
    disambiguation_candidates: dict[str, list[str]] = field(default_factory=dict)

    @property
    def derived_event_id(self) -> str | None:
        """The event_id ingest gives the page for this sport, Games and event
        (ingest/infobox.py derives it from the page title alone). Exact where
        an event_name match is not: infobox names vary ("Women’s relay" with
        a curly apostrophe) and one name exists in many editions."""
        if self.event_id or not (self.sport and self.games and self.title):
            return None
        return event_id_from_parts(self.sport, self.games, self.title)

    @property
    def needs_disambiguation(self) -> bool:
        """ARCHITECTURE-SPEC §13: sport and event name are the real
        discriminators for an ambiguous venue. With neither supplied there is
        nothing to narrow the candidates by, so a disambiguation request is
        returned instead of an answer (AD-15)."""
        return bool(self.disambiguation_candidates) and not (
            self.sport or self.title or self.event_id
        )


class EntityLinker:
    """Longest-match entity linker over closed Olympic vocabularies.

    Implements longest-match to handle substrings correctly:
      'Olympic Oval'  →  should NOT match when 'Richmond Olympic Oval' is present
      'Riocentro'     →  should NOT match when 'Riocentro – Pavilion 4' is present
    """

    def __init__(
        self,
        games_vocab: list[str] | None = None,
        sports_vocab: list[str] | None = None,
        venues_vocab: list[str] | None = None,
    ) -> None:
        self.games_vocab: list[str] = sorted(
            games_vocab or DEFAULT_GAMES_VOCAB, key=len, reverse=True
        )
        self.sports_vocab: list[str] = sorted(
            sports_vocab or [], key=len, reverse=True
        )
        self.venues_vocab: list[str] = sorted(
            venues_vocab or [], key=len, reverse=True
        )

    def resolve(self, intent: IntentSchema, question: str | None = None) -> ResolvedAnchors:
        """Resolve intent anchors to graph entity identifiers.

        With `question`, anchors the parse omitted are recovered from the
        question text (`_recover_from_question`)."""
        result = ResolvedAnchors(
            title=intent.anchor.title,
            event_id=intent.anchor.event_id,
        )

        # Resolve sport
        if intent.anchor.sport:
            resolved = self._longest_match(intent.anchor.sport, self.sports_vocab)
            if resolved:
                result.sport = resolved
            else:
                result.unresolved_fields.append("sport")
                logger.debug("Entity linking: sport '%s' not resolved", intent.anchor.sport)

        # Resolve games (also try matching year strings)
        if intent.anchor.games:
            resolved = self._resolve_games(intent.anchor.games)
            if resolved:
                result.games = resolved
            else:
                result.unresolved_fields.append("games")
                logger.debug("Entity linking: games '%s' not resolved", intent.anchor.games)

        # Resolve venue — explicitly returns None on no match (eval-001 case)
        if intent.anchor.venue:
            resolved, candidates = self._resolve_venue(intent.anchor.venue)
            if resolved:
                result.venue = resolved
            else:
                result.unresolved_fields.append("venue")
                if candidates:
                    result.disambiguation_candidates["venue"] = candidates
                logger.debug(
                    "Entity linking: venue '%s' not resolved (candidates: %s)",
                    intent.anchor.venue,
                    candidates,
                )

        # Normalize date constraints
        for constraint in intent.constraints:
            if constraint.field in ("date", "dates", "date_text") and isinstance(constraint.value, str):
                nd = normalize_date(constraint.value)
                if nd.year:
                    result.date_year = nd.year
                if nd.month:
                    result.date_month = nd.month
                if nd.day_start:
                    result.date_day_start = nd.day_start

        if question:
            result.question = question
            self._recover_from_question(result, question)
        return result

    def _recover_from_question(self, result: ResolvedAnchors, question: str) -> None:
        """Fill anchors the intent parse left out but the question states.

        The same LLM at temperature 0 sometimes parses "the event held at
        Carioca Arena 3 on 6 August 2016" with no anchor at all (SCORE-AUDIT,
        decision 14), and the agent then searches text instead of the graph.
        This is gazetteer linking, not a question template: a venue, sport or
        Games is recovered only when one of the graph's own vocabulary
        entries appears verbatim (whole words, case-insensitive) in the
        question; a date only when the question states a full day. A field
        the parse did give is never overridden, and one the parse gave but
        could not resolve is left unresolved.
        """
        text = question.lower()

        def verbatim(entry: str) -> bool:
            return re.search(rf"(?<!\w){re.escape(entry.lower())}(?!\w)", text) is not None

        # A Games id parsed into the event-title slot ("2016-Summer") is the
        # Games anchor, not an event name.
        if result.title and not result.event_id:
            as_games = self._resolve_games(result.title) if re.fullmatch(
                r"\s*\d{4}[\s-]*(summer|winter)?(\s+olympics)?\s*", result.title, re.IGNORECASE
            ) else None
            if as_games:
                result.recovered.append(f"games={as_games} (parsed as an event title)")
                result.games = result.games or as_games
                result.title = None
        # A venue parsed into the event-title slot ("the event held at North
        # Greenwich Arena", r5 pub-067) is the venue anchor, not an event name.
        if result.title and not result.event_id:
            as_venue = next(
                (v for v in self.venues_vocab if v.lower() == result.title.strip().lower()), None
            )
            if as_venue:
                result.recovered.append(f"venue={as_venue} (parsed as an event title)")
                result.venue = result.venue or as_venue
                result.title = None
        # A parsed venue that the question names more fully ("Kvitfjell" in
        # "held at Kvitfjell and Hafjell") becomes the fuller graph venue.
        if result.venue:
            fuller = next(
                (v for v in self.venues_vocab
                 if len(v) > len(result.venue) and result.venue.lower() in v.lower() and verbatim(v)),
                None,
            )
            if fuller:
                result.recovered.append(f"venue={fuller} (question names it in full)")
                result.venue = fuller

        if not result.venue and "venue" not in result.unresolved_fields:
            # Longest first (vocab is sorted by length), so "Riocentro – Pavilion 6"
            # wins over "Riocentro"; very short names are too ambiguous to trust.
            venue = next((v for v in self.venues_vocab if len(v) >= 6 and verbatim(v)), None)
            if venue:
                result.venue = venue
                result.recovered.append(f"venue={venue}")
        if not result.sport and "sport" not in result.unresolved_fields:
            sport = next((sp for sp in self.sports_vocab if verbatim(sp)), None)
            if sport:
                result.sport = sport
                result.recovered.append(f"sport={sport}")
        if not result.games and "games" not in result.unresolved_fields:
            games = re.search(r"\b(\d{4})\s+(summer|winter)\b", text)
            candidate = f"{games.group(1)}-{games.group(2).capitalize()}" if games else None
            if candidate and candidate in self.games_vocab:
                result.games = candidate
                result.recovered.append(f"games={candidate}")
        if not (result.date_month or result.date_day_start):
            day = re.search(
                r"\b(\d{1,2}(?:\s*[–-]\s*\d{1,2})?\s+[a-z]+\s+\d{4}"
                r"|[a-z]+\s+\d{1,2}(?:\s*[–-]\s*\d{1,2})?,?\s+\d{4})\b",
                text,
            )
            nd = normalize_date(day.group(1)) if day else None
            if not day and result.games:
                # "on 4 August at the 2012 Summer Olympics": the year is the Games'.
                bare = re.search(
                    r"\b(\d{1,2})\s+(january|february|march|april|may|june|july|august"
                    r"|september|october|november|december)\b",
                    text,
                )
                if bare:
                    nd = normalize_date(f"{bare.group(1)} {bare.group(2)} {result.games[:4]}")
            if nd and nd.month and nd.day_start:
                result.date_year = result.date_year or nd.year
                result.date_month, result.date_day_start = nd.month, nd.day_start
                result.recovered.append(f"date={nd.year}-{nd.month:02d}-{nd.day_start:02d}")

    def _longest_match(self, query: str, vocab: list[str]) -> str | None:
        """Vocabulary lookup (vocab pre-sorted by length descending).

        An exact (case-insensitive) match wins; then the longest entry the
        query contains ("Athletics" in "athletics events"); then an entry
        that contains the query, only when exactly one does. Checking
        "contains the query" first linked "speed skating" to "Short-track
        speed skating" and "swimming" to "Synchronized swimming" (r2).
        """
        def norm(text: str) -> str:
            # "Short-track" / "short track", "2016-Summer" / "2016 Summer".
            return " ".join(re.sub(r"[-–—_]", " ", text.lower()).split())

        q_norm = norm(query)
        if not q_norm:
            return None
        for entry in vocab:
            if norm(entry) == q_norm:
                return entry
        for entry in vocab:
            if norm(entry) in q_norm:
                return entry
        wider = [entry for entry in vocab if q_norm in norm(entry)]
        return wider[0] if len(wider) == 1 else None

    def _resolve_games(self, query: str) -> str | None:
        """Resolve games string — handles year-only inputs like '2016' → '2016-Summer'."""
        q_lower = query.lower().strip()

        # Direct match against vocab
        match = self._longest_match(query, self.games_vocab)
        if match:
            return match

        # Year-only: '2016' → find Summer entry for that year
        year_match = re.search(r"\b(\d{4})\b", query)
        if year_match:
            year = year_match.group(1)
            season = "Winter" if "winter" in q_lower else "Summer"
            candidate = f"{year}-{season}"
            if candidate in self.games_vocab:
                return candidate

        return None

    def _resolve_venue(self, query: str) -> tuple[str | None, list[str]]:
        """Longest-match venue resolution, returning candidates on ambiguity."""
        q_lower = query.lower().strip()
        candidates = []
        for v in self.venues_vocab:
            v_lower = v.lower()
            if q_lower in v_lower or v_lower in q_lower:
                candidates.append(v)

        if not candidates:
            return None, []
        if len(candidates) == 1:
            return candidates[0], []
        # If query exactly matches one, prefer that
        exact = [c for c in candidates if c.lower() == q_lower]
        if exact:
            return exact[0], []
        # AD-15: several venues match and none exactly — surface them, never
        # substitute a best guess.
        return None, candidates


def _date_words(text: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", (text or "").lower()).split())


def narrow_to_date(rows: list[dict], anchors: ResolvedAnchors) -> list[dict]:
    """Keep the rows whose event date matches the question's.

    First, rows whose recorded date text appears in the question as written
    ("3 to 4 August", "13, 14 February 2022"): the question states the date
    the way the graph records it, which also separates events that merely
    overlap a day. Otherwise, rows whose date covers the anchored day: same
    month, day within [date_day_start, date_day_end]; year-only or month-only
    anchors narrow by what they give. Falls back to all rows when none match,
    like narrow_to_games."""
    if not rows:
        return rows
    question = f" {_date_words(anchors.question or '')} "
    stated = [
        r for r in rows
        if len(_date_words(str(r.get("date_text") or ""))) >= 5
        and f" {_date_words(str(r.get('date_text')))} " in question
    ]
    if stated:
        return stated
    if not (anchors.date_year or anchors.date_month):
        return rows
    kept = [r for r in rows if _covers(r, anchors)]
    return kept or rows


def _covers(r: dict, anchors: ResolvedAnchors) -> bool:
    """The row's date is consistent with the anchored year, month and day."""
    if anchors.date_year and r.get("date_year") and int(r["date_year"]) != anchors.date_year:
        return False
    if anchors.date_month and r.get("date_month") and int(r["date_month"]) != anchors.date_month:
        return False
    if anchors.date_day_start and r.get("date_day_start"):
        start = int(r["date_day_start"])
        end = int(r.get("date_day_end") or 0) or start
        return start <= anchors.date_day_start <= end
    return True


def narrow_to_named(rows: list[dict], anchors: ResolvedAnchors) -> list[dict]:
    """Keep the rows whose event name the question states in full ("the
    men's team pursuit held at London Velopark on 3 August"): the intent
    parse can leave the event name out, and the question still names it.
    Whole words, punctuation ignored; when several names appear ("singles"
    and "women's singles"), the longest wins. Falls back to all rows when
    the question names none of them."""
    question = f" {_date_words(anchors.question or '')} "
    named = [
        (len(name), r) for r in rows
        if (name := _date_words(str(r.get("event_name") or "")))
        and f" {name} " in question
    ]
    if not named:
        return rows
    longest = max(length for length, _ in named)
    return [r for length, r in named if length == longest]


# Fields that name the event rather than describe it: when the question asks
# for one of these, every event held that day is part of the answer.
NAMING_FIELDS = frozenset({"event_name", "event", "events", "title", "name", "event_id"})


def ambiguous_events(rows: list[dict], anchors: ResolvedAnchors, target_field: str) -> list[dict]:
    """The events a venue-and-day question could mean, when the answer depends
    on which one is meant; [] when it does not.

    After narrowing by Games, sport, day and stated event name, several
    events can still remain (a venue hosts several finals on one day). The
    agent used to pick one by the order the rows came back. Instead, when
    the question asks for an attribute of one event, every one of those
    events covers the anchored day, and they do not all agree on the
    attribute, the run asks which event was meant (AD-15). One row per
    event, in the order given."""
    if anchors.title or anchors.event_id or not anchors.date_day_start:
        return []
    if (target_field or "").strip().lower() in NAMING_FIELDS:
        return []
    by_event: dict[str, dict] = {}
    for r in rows:
        key = str(r.get("event_id") or r.get("title") or "")
        if key:
            by_event.setdefault(key, r)
    if len(by_event) < 2:
        return []
    # narrow_to_date keeps every row when none covers the day: those are not
    # candidates for that day, and the question is not asked.
    if not all(_covers(r, anchors) for r in by_event.values()):
        return []
    values = {_date_words(str(r.get("value") or "")) for r in by_event.values()}
    if len(values) == 1 and "" not in values:
        return []  # every candidate gives the same answer
    return list(by_event.values())


def event_label(row: dict) -> str:
    """How a candidate event is named to the user: its page title, and the
    date the graph records for it."""
    name = row.get("title") or row.get("event_name") or row.get("event_id") or ""
    date = str(row.get("date_text") or "").strip()
    return f"{name} ({date})" if date else str(name)


def edition_of(event_id: str) -> str:
    """`athletics-2008-Summer-men-s-shot-put` -> `2008-Summer` ("" if none)."""
    match = re.search(r"-(\d{4}-(?:Summer|Winter))-", f"-{event_id}-")
    return match.group(1) if match else ""


def lookup_named_event(client: Any, anchors: ResolvedAnchors, target_field: str = "") -> list[dict]:
    """Q1 on the event the anchors name: by the derived event_id when there is
    one and it exists, else by title / event_id, narrowed to the Games anchor."""
    derived = anchors.derived_event_id
    if derived:
        params = {"title": "", "event_id": derived, "target_field": target_field}
        rows = client._run_query("q1_lookup", params)
        if rows:
            return rows
    params = {"title": anchors.title or "", "event_id": anchors.event_id or "", "target_field": target_field}
    return narrow_to_games(client._run_query("q1_lookup", params) or [], anchors.games)


def narrow_to_games(rows: list[dict], games: str | None) -> list[dict]:
    """Q1 matches an event name across every Games ("Women's RS:X" exists for
    2008, 2012 and 2016). With a resolved Games anchor, keep only that
    edition's rows — deterministic, no LLM needed to pick the year. Falls back
    to all rows when none match, so a wrong anchor never empties the result."""
    if not games or len(rows) < 2:
        return rows
    year = games.split("-")[0]
    by_id = [r for r in rows if f"-{games}-" in str(r.get("event_id", ""))]
    if by_id:
        return by_id
    by_year = [r for r in rows if str(r.get("date_year", "")) == year]
    return by_year or rows
