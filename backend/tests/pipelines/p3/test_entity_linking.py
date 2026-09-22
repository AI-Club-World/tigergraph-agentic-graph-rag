"""Tests for Group 2: Entity linking.

Verification Plan Group 2:
- test_longest_match_venue: Richmond Olympic Oval, not Olympic Oval
- test_unresolved_venue_returns_none: the eval-001 shape
"""

from __future__ import annotations

import pytest

from ogr.pipelines.p3_agentic.agents.entity_linking import EntityLinker
from ogr.pipelines.p3_agentic.intent import Anchor, AnchorConstraint, IntentSchema


def _make_linker(
    games=None,
    sports=None,
    venues=None,
) -> EntityLinker:
    return EntityLinker(
        games_vocab=games or ["2016-Summer", "2012-Summer", "2008-Summer", "2004-Summer"],
        sports_vocab=sports or ["Sailing", "Swimming", "Athletics", "Cycling", "Boxing", "Gymnastics"],
        venues_vocab=venues or [
            "Olympic Oval",
            "Richmond Olympic Oval",
            "Olympic Stadium",
            "Riocentro",
            "Riocentro – Pavilion 4",
            "Aquatics Centre",
            "Olympic Tennis Centre",  # NOT present as a venue field in corpus (eval-001 case)
        ],
    )


def _make_intent(operation="LOOKUP", **anchor_kwargs) -> IntentSchema:
    return IntentSchema(
        operation=operation,
        anchor=Anchor(**anchor_kwargs),
    )


class TestLongestMatchVenue:
    def test_longest_match_venue_richmond_not_olympic_oval(self):
        """test_longest_match_venue: 'Richmond Olympic Oval' wins over 'Olympic Oval' substring.

        ARCHITECTURE-SPEC §13 Research finding:
          'Olympic Oval' is a substring of 'Richmond Olympic Oval'.
          Longest-match must return the more specific entry.
        """
        linker = _make_linker()
        intent = _make_intent("LOOKUP", venue="Richmond Olympic Oval")
        result = linker.resolve(intent)
        assert result.venue == "Richmond Olympic Oval"
        assert "venue" not in result.unresolved_fields

    def test_longest_match_riocentro_pavilion(self):
        """'Riocentro' substring of 'Riocentro – Pavilion 4': longer match wins."""
        linker = _make_linker()
        intent = _make_intent("LOOKUP", venue="Riocentro – Pavilion 4")
        result = linker.resolve(intent)
        assert result.venue == "Riocentro – Pavilion 4"

    def test_exact_venue_match(self):
        linker = _make_linker()
        intent = _make_intent("LOOKUP", venue="Aquatics Centre")
        result = linker.resolve(intent)
        assert result.venue == "Aquatics Centre"

    def test_case_insensitive_venue_match(self):
        linker = _make_linker()
        intent = _make_intent("LOOKUP", venue="aquatics centre")
        result = linker.resolve(intent)
        assert result.venue == "Aquatics Centre"

    def test_sport_resolution(self):
        linker = _make_linker()
        intent = _make_intent("COUNT", sport="Sailing")
        result = linker.resolve(intent)
        assert result.sport == "Sailing"

    def test_games_resolution_from_year_only(self):
        """Games resolution accepts bare year strings like '2016'."""
        linker = _make_linker()
        intent = _make_intent("COUNT", games="2016")
        result = linker.resolve(intent)
        assert result.games == "2016-Summer"

    def test_games_resolution_full_id(self):
        linker = _make_linker()
        intent = _make_intent("COUNT", games="2016-Summer")
        result = linker.resolve(intent)
        assert result.games == "2016-Summer"


class TestUnresolvedVenueReturnsNone:
    def test_unresolved_venue_returns_none_eval001_shape(self):
        """test_unresolved_venue_returns_none: The eval-001 case.

        'Olympic Tennis Centre' appears in zero venue fields across the corpus.
        The entity linker must return None (not guess), so the DP-2 fallback fires.
        """
        linker = _make_linker(venues=["Olympic Stadium", "Aquatics Centre", "Velodrome"])
        intent = _make_intent("LOOKUP", venue="Olympic Tennis Centre")
        result = linker.resolve(intent)

        # Must return None — not a guess
        assert result.venue is None
        assert "venue" in result.unresolved_fields

    def test_unresolved_venue_provides_candidates_when_partial(self):
        """Partial matches return candidates for disambiguation."""
        linker = _make_linker(venues=["Olympic Oval", "Olympic Stadium", "Olympic Aquatic Centre"])
        intent = _make_intent("LOOKUP", venue="Olympic")
        result = linker.resolve(intent)
        # May or may not resolve fully, but if ambiguous returns candidates
        if result.venue is None:
            # Disambiguation candidates available for surfacing
            assert len(result.disambiguation_candidates.get("venue", [])) >= 1

    def test_unresolved_sport_returns_none(self):
        linker = _make_linker(sports=["Sailing", "Swimming"])
        intent = _make_intent("LOOKUP", sport="Competitive Eating")
        result = linker.resolve(intent)
        assert result.sport is None
        assert "sport" in result.unresolved_fields

    def test_title_and_event_id_are_passed_through(self):
        """title and event_id are not resolved — they are passed through directly."""
        linker = _make_linker()
        intent = _make_intent(
            "LOOKUP",
            title="Athletics at the 2016 Summer Olympics – Men's marathon",
            event_id="Q123456",
        )
        result = linker.resolve(intent)
        assert result.title == "Athletics at the 2016 Summer Olympics – Men's marathon"
        assert result.event_id == "Q123456"
