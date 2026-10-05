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


class TestSportLinking:
    """r2: "speed skating" linked to Short-track, "swimming" to Synchronized swimming."""

    LINKER = EntityLinker(sports_vocab=["Short-track speed skating", "Speed skating", "Synchronized swimming", "Swimming"])

    def test_an_exact_name_beats_a_longer_one_containing_it(self):
        assert self.LINKER._longest_match("speed skating", self.LINKER.sports_vocab) == "Speed skating"
        assert self.LINKER._longest_match("Swimming", self.LINKER.sports_vocab) == "Swimming"

    def test_hyphens_and_spaces_are_the_same_name(self):
        assert self.LINKER._longest_match("short track speed skating", self.LINKER.sports_vocab) == (
            "Short-track speed skating"
        )

    def test_a_partial_name_links_only_when_unambiguous(self):
        assert self.LINKER._longest_match("synchronized", self.LINKER.sports_vocab) == "Synchronized swimming"
        assert self.LINKER._longest_match("skating", self.LINKER.sports_vocab) is None


class TestParsedAnchorRepair:
    LINKER = EntityLinker(
        games_vocab=["2016-Summer", "1994-Winter"],
        sports_vocab=["Biathlon"],
        venues_vocab=["Kvitfjell and Hafjell", "Kvitfjell", "Carioca Arena 3"],
    )

    def test_a_games_id_parsed_as_an_event_title_becomes_the_games(self):
        a = self.LINKER.resolve(
            IntentSchema(operation="TRAVERSE", anchor=Anchor(title="2016-Summer", venue="Carioca Arena 3")),
            "Who won the gold medal in the event held at Carioca Arena 3 on 6 August 2016?",
        )
        assert a.title is None and a.games == "2016-Summer"

    def test_a_venue_parsed_as_an_event_title_becomes_the_venue(self):
        # r5 pub-067: the parse put the venue in the title slot and dropped the day.
        a = self.LINKER.resolve(
            IntentSchema(operation="TRAVERSE", anchor=Anchor(title="Carioca Arena 3")),
            "Who won the gold medal in the event held at Carioca Arena 3 on 6 August at the 2016 Summer Olympics?",
        )
        assert a.title is None and a.venue == "Carioca Arena 3" and a.games == "2016-Summer"
        assert (a.date_year, a.date_month, a.date_day_start) == (2016, 8, 6)

    def test_a_day_without_a_year_needs_the_games(self):
        a = self.LINKER.resolve(IntentSchema(operation="TRAVERSE"), "Who won at Carioca Arena 3 on 6 August?")
        assert a.date_month is None

    def test_a_real_event_title_is_left_alone(self):
        a = self.LINKER.resolve(IntentSchema(operation="LOOKUP", anchor=Anchor(title="Women's relay")), "x")
        assert a.title == "Women's relay"

    def test_a_venue_the_question_names_in_full_is_upgraded(self):
        a = self.LINKER.resolve(
            IntentSchema(operation="TRAVERSE", anchor=Anchor(venue="Kvitfjell")),
            "Who won the gold medal in the event held at Kvitfjell and Hafjell on February 20–21, 1994?",
        )
        assert a.venue == "Kvitfjell and Hafjell"


class TestDateAsWritten:
    """The question states the date as the graph records it: that beats day coverage."""

    ROWS = [
        {"event_id": "pursuit", "date_text": "3 to 4 August", "date_month": 8, "date_day_start": 3, "date_day_end": 4},
        {"event_id": "sprint", "date_text": "2 to 3 August", "date_month": 8, "date_day_start": 2, "date_day_end": 3},
        {"event_id": "keirin", "date_text": "7 August", "date_month": 8, "date_day_start": 7, "date_day_end": 0},
    ]

    def test_the_date_text_the_question_quotes_selects_the_event(self):
        from ogr.pipelines.p3_agentic.agents.entity_linking import ResolvedAnchors, narrow_to_date

        anchors = ResolvedAnchors(question="Who won the event held at London Velopark on 3 to 4 August at the 2012 Games?",
                                  date_month=8, date_day_start=3)
        assert [r["event_id"] for r in narrow_to_date(self.ROWS, anchors)] == ["pursuit"]

    def test_without_a_quoted_date_the_day_coverage_rule_applies(self):
        from ogr.pipelines.p3_agentic.agents.entity_linking import ResolvedAnchors, narrow_to_date

        anchors = ResolvedAnchors(question="Who won on 3 August?", date_month=8, date_day_start=3)
        assert [r["event_id"] for r in narrow_to_date(self.ROWS, anchors)] == ["pursuit", "sprint"]


def test_venue_events_are_narrowed_by_sport_before_the_cap():
    from ogr.pipelines.p3_agentic.agents.entity_linking import ResolvedAnchors
    from ogr.pipelines.p3_agentic.agents.multi_hop import run_venue_events

    class Client:
        def __init__(self):
            self.q1 = []

        def _run_query(self, name, params):
            if name == "q4_traverse":
                return [{"event_id": "cross-country-skiing-2014-Winter-women-s-30-km"},
                        {"event_id": "biathlon-2014-Winter-men-s-relay"}]
            self.q1.append(params["event_id"])
            return [{"event_id": params["event_id"], "doc_id": "Q1", "gold": "x"}]

    client = Client()
    run_venue_events(client, IntentSchema(operation="TRAVERSE", target_field="gold"),
                     ResolvedAnchors(venue="Laura Biathlon & Ski Complex", sport="Biathlon", games="2014-Winter"))
    assert client.q1 == ["biathlon-2014-Winter-men-s-relay"]
