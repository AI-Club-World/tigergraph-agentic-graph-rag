"""Venue expansion keeps the anchored edition and day (r2: pub-095)."""

from __future__ import annotations

from ogr.pipelines.p3_agentic.agents.entity_linking import ResolvedAnchors, edition_of, narrow_to_date
from ogr.pipelines.p3_agentic.agents.multi_hop import MAX_VENUE_EVENTS, run_venue_events
from ogr.pipelines.p3_agentic.intent import IntentSchema


def test_edition_of_reads_the_games_from_the_event_id():
    assert edition_of("athletics-2008-Summer-women-s-shot-put") == "2008-Summer"
    assert edition_of("Q12345") == ""


def test_narrow_to_date_keeps_events_covering_the_day():
    rows = [
        {"event_id": "a", "date_year": 2008, "date_month": 8, "date_day_start": 15, "date_day_end": 16},
        {"event_id": "b", "date_year": 2008, "date_month": 8, "date_day_start": 18, "date_day_end": 0},
        {"event_id": "c", "date_year": 2008, "date_month": 9, "date_day_start": 16, "date_day_end": 0},
    ]
    anchors = ResolvedAnchors(date_year=2008, date_month=8, date_day_start=16)
    assert [r["event_id"] for r in narrow_to_date(rows, anchors)] == ["a"]
    assert narrow_to_date(rows, ResolvedAnchors(date_year=1900)) == rows  # nothing matches: keep all
    assert narrow_to_date(rows, ResolvedAnchors()) == rows


class _Client:
    """A venue with events across many editions; Q1 returns each event's date."""

    def __init__(self):
        self.q1 = []
        self.events = [{"event_id": f"athletics-1996-Summer-e{i}"} for i in range(MAX_VENUE_EVENTS + 10)] + [
            {"event_id": "athletics-2008-Summer-women-s-shot-put"},
            {"event_id": "athletics-2008-Summer-men-s-100-m"},
        ]

    def _run_query(self, name, params):
        if name == "q4_traverse":
            return self.events
        self.q1.append(params["event_id"])
        day = 16 if "shot-put" in params["event_id"] else 20
        return [{"event_id": params["event_id"], "doc_id": "Q1", "date_year": 2008, "date_month": 8,
                 "date_day_start": day, "date_day_end": 0, "gold": "x"}]


def test_the_edition_is_kept_before_the_cap_and_the_day_after_q1():
    client = _Client()
    anchors = ResolvedAnchors(venue="Beijing National Stadium", date_year=2008, date_month=8, date_day_start=16)
    result = run_venue_events(client, IntentSchema(operation="TRAVERSE", target_field="gold"), anchors)
    assert len(client.events) > MAX_VENUE_EVENTS
    assert client.q1 == ["athletics-2008-Summer-women-s-shot-put", "athletics-2008-Summer-men-s-100-m"]
    assert [r["event_id"] for r in result.evidence] == ["athletics-2008-Summer-women-s-shot-put"]
