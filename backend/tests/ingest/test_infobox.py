"""Tests for GRAPH-02, the infobox parser.

The fixtures below are real corpus rows, not invented shapes. Where a test
asserts a corpus-wide number it is marked `corpus` and skips when
data/corpus.jsonl is absent, so the suite still runs on a clone without data.

The corpus-wide assertions matter more than they look: they independently
reproduce figures the specs measured separately. **Corrected from the specs'
original numbers**: the parser used to take the first `[Infobox ...]` header
unconditionally, which silently dropped 25 real Olympic events whose complete
infobox is listed second (e.g. tennis-at-the-Olympics pages). After the fix:
2,187 Olympic infoboxes (was 2,162), 42 sports (was 41), 21 Games, 319 venues
(was 303), 24 non-integer competitors (was 23), prev 93.5% / next 97.7% (was
93.4% / 97.6%). Agreement between two independent parses is real evidence the
parser reads the corpus the way the specs assumed — this file's numbers are
now the more-correct pair.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ogr.ingest.infobox import (
    derive_sport,
    normalise_games_id,
    parse_corpus,
    parse_document,
    parse_infobox_fields,
    parse_infobox_header,
)

CORPUS = Path(__file__).resolve().parents[3] / "data" / "corpus.jsonl"
corpus_required = pytest.mark.skipif(not CORPUS.exists(), reason="data/corpus.jsonl not present")

# Adapted from data/corpus.jsonl (Q303623): same structure and concatenated
# names as the real row, with medallist names transliterated to ASCII.
CANOE = {
    "doc_id": "Q303623",
    "title": "Canoeing at the 2012 Summer Olympics – Men's K-2 1000 metres",
    "url": "https://en.wikipedia.org/wiki/Canoeing_at_the_2012_Summer_Olympics",
    "wikipedia_pageid": 35771859,
    "approx_tokens": 704,
    "text": """[Infobox Olympic event]
  event: Men's canoe sprint K-2 1,000 metres
  games: 2012 Summer
  venue: Eton Dorney
  date: 6 to 8 August
  competitors: 24
  nations: 12
  gold: Rudolf DombiRoland Kokeny
  goldNOC: HUN
  silver: Fernando PimentaEmanuel Silva
  bronze: Martin HollsteinAndreas Ihle
  win_value: 3:09.646
  prev: 2008
  next: 2016

The men's canoe sprint K-2 1,000 metres competition at the 2012 Olympic Games.
""",
}

FILM = {
    "doc_id": "Q12345",
    "title": "Some Film",
    "url": "https://en.wikipedia.org/wiki/Some_Film",
    "text": "[Infobox film]\n  director: A Director\n\nA 1998 film.\n",
}


class TestHeaderAndFields:
    def test_reads_the_infobox_type(self):
        assert parse_infobox_header(CANOE["text"]) == "olympic event"
        assert parse_infobox_header(FILM["text"]) == "film"

    def test_no_infobox_is_none_not_an_error(self):
        assert parse_infobox_header("Just prose.\n") is None

    def test_reads_the_indented_block_and_stops_at_prose(self):
        fields = parse_infobox_fields(CANOE["text"])
        assert fields["games"] == "2012 Summer"
        assert fields["venue"] == "Eton Dorney"
        assert "The" not in fields, "prose leaked into the infobox block"


class TestSportAndGames:
    def test_sport_comes_from_the_title_prefix(self):
        """No infobox carries a sport field — the title is the only source."""
        assert derive_sport(CANOE["title"]) == "Canoeing"
        assert derive_sport("Speed skating at the 2010 Winter Olympics – Men's 5000 m") == "Speed skating"

    def test_untitled_shape_yields_none_rather_than_a_guess(self):
        assert derive_sport("Some Film") is None

    def test_games_id_normalisation(self):
        assert normalise_games_id("2012 Summer") == "2012-Summer"
        assert normalise_games_id("2010 Winter") == "2010-Winter"
        assert normalise_games_id("") is None
        assert normalise_games_id("no year here") is None


class TestOlympicEventParse:
    def test_parses_the_core_attributes(self):
        doc = parse_document(CANOE)
        assert doc.is_olympic_event
        assert doc.games_id == "2012-Summer"
        assert doc.sport_name == "Canoeing"
        assert doc.venue_name == "Eton Dorney"
        assert doc.event_name == "Men's canoe sprint K-2 1,000 metres"

    def test_competitors_and_nations_are_typed_ints(self):
        """WHERE competitors > 37 must be a native predicate, not a parse."""
        doc = parse_document(CANOE)
        assert doc.competitors == 24 and isinstance(doc.competitors, int)
        assert doc.nations == 12

    def test_concatenated_medallists_are_split(self):
        doc = parse_document(CANOE)
        assert doc.gold == ["Rudolf Dombi", "Roland Kokeny"]
        assert doc.silver == ["Fernando Pimenta", "Emanuel Silva"]

    def test_guarded_surname_is_not_torn_in_half(self):
        """The pub-067 failure, at ingest: gold is concatenated the same way."""
        record = dict(CANOE, text=CANOE["text"].replace(
            "gold: Rudolf DombiRoland Kokeny", "gold: Rosannagh MacLennan"))
        assert parse_document(record).gold == ["Rosannagh MacLennan"]

    def test_date_without_a_year_parses_what_it_can(self):
        """'6 to 8 August' has no year — the field is nullable by design."""
        doc = parse_document(CANOE)
        assert doc.date_text == "6 to 8 August"
        assert doc.date_month == 8
        assert doc.date_year is None

    def test_prev_and_next_are_years(self):
        doc = parse_document(CANOE)
        assert doc.prev_year == 2008
        assert doc.next_year == 2016

    def test_clean_parse_is_full_confidence(self):
        assert parse_document(CANOE).parse_confidence == 1.0

    def test_event_id_is_stable(self):
        assert parse_document(CANOE).event_id == parse_document(CANOE).event_id


class TestPartialParse:
    def test_non_integer_competitors_loads_with_reduced_confidence(self):
        """'23 teams' keeps the leading int, retains the text, drops confidence.

        The row must still load: a partial parse the agent can see beats a
        silently wrong count.
        """
        record = dict(CANOE, text=CANOE["text"].replace("competitors: 24", "competitors: 23 teams"))
        doc = parse_document(record)
        assert doc.competitors == 23
        assert doc.competitors_text == "23 teams"
        assert doc.parse_confidence < 1.0
        assert any("not an integer" in note for note in doc.parse_notes)

    def test_unparseable_competitors_is_none_not_zero(self):
        record = dict(CANOE, text=CANOE["text"].replace("competitors: 24", "competitors: unknown"))
        assert parse_document(record).competitors is None


class TestNonOlympicDocuments:
    def test_kept_but_not_treated_as_an_event(self):
        """AD-9: P1 embeds all 2,951 docs. Dropping these would type-filter it."""
        doc = parse_document(FILM)
        assert doc.is_olympic_event is False
        assert doc.infobox_type == "film"
        assert doc.doc_id == "Q12345"
        assert doc.games_id is None


class TestMultipleInfoboxes:
    def test_olympic_infobox_found_even_when_listed_second(self):
        """Real corpus docs (tennis-at-the-Olympics pages) carry a non-Olympic
        infobox first and the complete Olympic-event infobox second. Taking
        the first header unconditionally would drop a real OlympicEvent.
        """
        record = dict(
            CANOE,
            doc_id="Q26037158",
            text="[Infobox tennis tournament event]\n  champion: Someone\n\n"
            + CANOE["text"],
        )
        doc = parse_document(record)
        assert doc.infobox_type == "olympic event"
        assert doc.is_olympic_event
        assert doc.games_id == "2012-Summer"
        assert doc.competitors == 24

    def test_first_header_still_wins_when_neither_is_olympic(self):
        record = dict(FILM, text="[Infobox film]\n  director: A\n\n[Infobox book]\n  author: B\n")
        assert parse_infobox_header(record["text"]) == "film"


class TestTiedBronzeMedals:
    def test_bronze2_and_bronzeno_c2_are_both_captured(self):
        """bronze2/bronzeNOC2 (third-place ties) appear on ~13% of real events."""
        record = dict(
            CANOE,
            text=CANOE["text"].replace(
                "bronze: Martin HollsteinAndreas Ihle\n",
                "bronze: Martin HollsteinAndreas Ihle\n  bronze2: Someone ElseAnother Person\n",
            ),
        )
        doc = parse_document(record)
        assert doc.bronze == ["Martin Hollstein", "Andreas Ihle", "Someone Else", "Another Person"]


@corpus_required
class TestAgainstTheRealCorpus:
    """Reproduces, independently, the figures the specs measured."""

    @pytest.fixture(scope="class")
    @classmethod
    def parsed(cls):
        return parse_corpus(CORPUS)

    def test_every_document_is_kept(self, parsed):
        docs, report = parsed
        assert len(docs) == 2951
        assert report.total_documents == 2951

    def test_olympic_event_count(self, parsed):
        """2,187 = 2,162 + the 25 tennis-at-the-Olympics docs whose complete
        Olympic infobox is listed second, behind a non-Olympic header — the
        first-header bug this parser used to have. The spec's own reference
        count (2,162) shares the same blind spot; this number is the corrected
        one, not the originally documented one.
        """
        assert parsed[1].olympic_events == 2187

    def test_sport_derives_for_every_olympic_event(self, parsed):
        docs, report = parsed
        assert report.missing_sport == []
        assert len({d.sport_name for d in docs if d.is_olympic_event}) == 42

    def test_distinct_games_and_venues(self, parsed):
        docs, _ = parsed
        events = [d for d in docs if d.is_olympic_event]
        assert len({d.games_id for d in events}) == 21
        assert len({d.venue_name for d in events if d.venue_name}) == 319

    def test_non_integer_competitors(self, parsed):
        """24 of 2,154 — updated from TECHNICAL-SPEC §2.3's 23/2,130 by the 25
        recovered tennis events (24 of them carry a competitors field; one of
        those 24 is non-integer).
        """
        _, report = parsed
        assert report.field_present["competitors"] == 2154
        assert len(report.non_integer_competitors) == 24
        assert report.low_confidence == 24

    def test_prev_next_edge_coverage(self, parsed):
        """93.5% / 97.7% — updated from 93.4%/97.6% by the 25 recovered events."""
        _, report = parsed
        events = report.olympic_events
        assert round(report.field_present["prev_year"] / events * 100, 1) == 93.5
        assert round(report.field_present["next_year"] / events * 100, 1) == 97.7

    def test_most_dates_carry_a_year(self, parsed):
        """~82%, updated from ~81% by the 25 recovered events."""
        _, report = parsed
        with_date = report.field_present["date_text"]
        assert round((with_date - report.dates_without_year) / with_date * 100) == 82
