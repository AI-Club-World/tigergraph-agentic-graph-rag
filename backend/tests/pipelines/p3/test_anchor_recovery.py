"""Anchors the intent parse omitted are recovered from the question text (r2 multi-hop losses)."""

from __future__ import annotations

from ogr.pipelines.p3_agentic.agents.entity_linking import EntityLinker
from ogr.pipelines.p3_agentic.intent import Anchor, IntentSchema

LINKER = EntityLinker(
    games_vocab=["2016-Summer", "2008-Summer", "1994-Winter"],
    sports_vocab=["Athletics", "Fencing"],
    venues_vocab=["Carioca Arena 3", "Carioca Arena 1", "Kvitfjell and Hafjell", "Kvitfjell", "Riocentro"],
)


def test_a_venue_and_a_day_the_parse_dropped_are_recovered():
    a = LINKER.resolve(IntentSchema(operation="TRAVERSE"),
                       "Who won the gold medal in the event held at Carioca Arena 3 on 6 August 2016?")
    assert (a.venue, a.date_year, a.date_month, a.date_day_start) == ("Carioca Arena 3", 2016, 8, 6)
    assert a.recovered == ["venue=Carioca Arena 3", "date=2016-08-06"]


def test_the_longest_venue_wins_and_a_day_range_gives_its_first_day():
    a = LINKER.resolve(IntentSchema(operation="TRAVERSE"),
                       "Who won the event held at Kvitfjell and Hafjell on February 20–21, 1994?")
    assert a.venue == "Kvitfjell and Hafjell" and (a.date_month, a.date_day_start) == (2, 20)


def test_sport_and_games_are_recovered_as_whole_words():
    a = LINKER.resolve(IntentSchema(operation="ARGMAX"),
                       "Which athletics event at the 2008 Summer Olympics had the most competitors?")
    assert (a.sport, a.games) == ("Athletics", "2008-Summer")


def test_parsed_anchors_are_never_overridden_or_unresolved_ones_replaced():
    parsed = IntentSchema(operation="TRAVERSE", anchor=Anchor(venue="Carioca Arena 1"))
    assert LINKER.resolve(parsed, "held at Carioca Arena 3").venue == "Carioca Arena 1"
    unresolved = IntentSchema(operation="TRAVERSE", anchor=Anchor(venue="Nowhere Hall"))
    assert LINKER.resolve(unresolved, "held at Carioca Arena 3").venue is None


def test_nothing_is_recovered_without_a_question_or_a_vocabulary_match():
    assert LINKER.resolve(IntentSchema(operation="TRAVERSE")).recovered == []
    assert LINKER.resolve(IntentSchema(operation="TRAVERSE"), "Who won the relay?").recovered == []
