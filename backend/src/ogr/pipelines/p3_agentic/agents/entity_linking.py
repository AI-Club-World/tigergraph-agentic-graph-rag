"""Entity linking agent for P3 Agentic GraphRAG pipeline.

Source spec: ARCHITECTURE-SPEC §4 · TECHNICAL-SPEC §2.2
Plan: implementation-plan-AGENT.md Group 2

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

from ogr.common.dates import normalize_date
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
    disambiguation_candidates: dict[str, list[str]] = field(default_factory=dict)

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

    def resolve(self, intent: IntentSchema) -> ResolvedAnchors:
        """Resolve intent anchors to graph entity identifiers."""
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

        return result

    def _longest_match(self, query: str, vocab: list[str]) -> str | None:
        """Longest-match lookup (vocab pre-sorted by length descending)."""
        q_lower = query.lower().strip()
        for entry in vocab:
            if entry.lower() in q_lower or q_lower in entry.lower():
                return entry
        return None

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
