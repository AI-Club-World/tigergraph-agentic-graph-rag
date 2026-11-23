"""Dev checks: LocalR2Graph, run on the real Round-2 corpus, reproduces the
public gold answers at the tool level (the tools return the data; an agent
decides which rows answer a question).

Gold answers come from questions_public.jsonl, never the hidden file. Where the
corpus holds more than the gold answer lists, the test says what the extra rows
are instead of loosening the comparison."""

from __future__ import annotations

import json

import pytest

from ogr.r2.graph_backend import series_extremes
from tests.r2.conftest import REAL_CORPUS, needs_corpus

pytestmark = needs_corpus

PUBLIC = REAL_CORPUS.parent / "questions_public.jsonl"


@pytest.fixture(scope="module")
def gold():
    return {q["qid"]: q for q in map(json.loads, PUBLIC.read_text(encoding="utf-8").splitlines())}


def _top(rows):
    return rows[0]["noc"], rows[0]["count"]


class TestMedalsByNation:
    def test_wrestling_2024_gold_japan_8(self, real, gold):
        rows = real.medals_by_nation("Wrestling", 2024, "", "gold").rows
        assert _top(rows) == ("JPN", 8) == (gold["r2-pub-006"]["answer"]["noc"], gold["r2-pub-006"]["answer"]["golds"])
        assert rows[1]["count"] < 8  # no tie for the top

    def test_japan_wrestling_golds_are_the_gold_answer_events(self, real, gold):
        [jpn] = [r for r in real.medals_by_nation("Wrestling", 2024, "", "gold").rows if r["noc"] == "JPN"]
        expected = {a["event"] for a in gold["r2-pub-003"]["answer"]}
        assert {e["title"].split(" – ")[1] for e in jpn["events"]} == expected

    def test_rowing_2024_gold_netherlands_4(self, real, gold):
        assert _top(real.medals_by_nation("Rowing", 2024, "", "gold").rows) == ("NED", 4)
        assert gold["r2-pub-033"]["answer"] == {"noc": "NED", "golds": 4}

    def test_judo_2020_gold_japan_9(self, real, gold):
        assert _top(real.medals_by_nation("Judo", 2020, "", "gold").rows) == ("JPN", 9)
        assert gold["r2-pub-007"]["answer"] == {"noc": "JPN", "golds": 9}


class TestFindEvents:
    def test_canoeing_is_one_sport_name_covering_sprint_and_slalom(self, real):
        rows = real.find_events("Canoeing", 2024).rows
        assert len(rows) == 16  # 10 sprint + 6 slalom events; no separate sport names exist
        assert real.find_events("Canoe sprint", 2024).rows == []

    def test_canoeing_2024_gold_nations(self, real, gold):
        rows = real.find_events("Canoeing", 2024).rows
        nocs = sorted({m["noc"] for r in rows for m in r["gold"]})
        assert nocs == sorted(gold["r2-pub-008"]["answer"]["nations"]) and len(nocs) == 8

    @pytest.mark.parametrize("sport,qid", [("Athletics", "025"), ("Cycling", "026"), ("Shooting", "027"),
                                           ("Swimming", "035")])
    def test_superlatives_over_events_with_nations(self, real, gold, sport, qid):
        rows = [r for r in real.find_events(sport, 2024).rows if r["nations"]]
        answer = gold[f"r2-pub-{qid}"]["answer"]
        pick = max if qid in ("026", "035") else min
        best = pick(rows, key=lambda r: r["nations"])
        assert (best["event_name"], best["nations"]) == (answer["event"], answer["nations"])

    def test_decathlon_competitors(self, real, gold):
        [row] = real.find_events("Athletics", 2024, event_contains="men's decathlon").rows
        assert row["competitors"] == int(gold["r2-pub-038"]["answer"])

    def test_events_are_synthetic_only_for_la_2028(self, real):
        assert all(r["synthetic"] for r in real.find_events(year=2028).rows)
        assert len(real.find_events(year=2028).rows) == 127
        assert not any(r["synthetic"] for r in real.find_events(year=2024).rows)


class TestEventSeries:
    @pytest.mark.parametrize("qid,event,sport", [
        ("009", "women's 800 metres", "Athletics"),
        ("010", "men's 80 kg", "Taekwondo"),
        ("011", "women's cross-country", "Cycling"),
        ("012", "men's hammer throw", "Athletics"),
    ])
    def test_nations_per_edition_with_max_and_min(self, real, gold, qid, event, sport):
        answer = gold[f"r2-pub-{qid}"]["answer"]
        result = real.event_series(event, sport, "Summer")
        assert [{"year": r["year"], "nations": r["nations"]} for r in result.rows] == answer["rows"]
        extremes = series_extremes(result.rows)
        assert (extremes["max_year"], extremes["min_year"]) == (answer["max_year"], answer["min_year"])


class TestAthletes:
    def test_teddy_riner_matches_gold_plus_the_team_gold(self, real, gold):
        rows = real.athlete_medals("Teddy Riner").rows
        individual = [(r["year"], r["event_name"].replace("+100kg", "+100 kg"), r["medal"])
                      for r in rows if r["event_name"] != "Mixed team"]
        assert individual == [(a["year"], a["event"], a["medal"]) for a in gold["r2-pub-015"]["answer"]]
        # The corpus also records the 2020 mixed team gold; the gold answer asks for the "category".
        assert [(r["year"], r["event_name"], r["medal"]) for r in rows if r["event_name"] == "Mixed team"] == [
            (2020, "Mixed team", "gold")]

    @pytest.mark.parametrize("qid,name,skip", [
        ("013", "Simone Biles", "team"), ("014", "Kaori Icho", None), ("016", "Usain Bolt", None),
        ("034", "Xinyi Gu", None),
    ])
    def test_career_rows(self, real, gold, qid, name, skip):
        rows = real.athlete_medals(name).rows
        got = [(r["year"], r["event_name"], r["medal"]) for r in rows if not (skip and skip in r["event_name"])]
        assert got == [(a["year"], a["event"], a["medal"]) for a in gold[f"r2-pub-{qid}"]["answer"]]
        if skip:  # the corpus also lists her team events, which the gold answer leaves out
            assert any(skip in r["event_name"] for r in rows)


class TestRepeatWinners:
    def test_fencing_has_vezzali_and_szilagyi(self, real, gold):
        rows = real.repeat_winners("Fencing").rows
        found = {(r["athlete"], r["event_name"], tuple(r["years"])) for r in rows}
        for a in gold["r2-pub-002"]["answer"]:
            assert (a["athlete"], a["event"], tuple(a["years"])) in found
        # The gold question asks for individual events; the other rows are team sabre medals.
        assert {r["athlete"] for r in rows} - {a["athlete"] for a in gold["r2-pub-002"]["answer"]} == {
            "Gu Bon-gil", "Olga Kharlan"}

    @pytest.mark.parametrize("qid,sport,season", [("001", "Judo", ""), ("032", "Snowboarding", "Winter")])
    def test_same_event_two_games(self, real, gold, qid, sport, season):
        rows = real.repeat_winners(sport, "gold", season).rows
        got = [(r["athlete"], r["event_name"], r["years"]) for r in rows]
        assert got == [(a["athlete"], a["event"], a["years"]) for a in gold[f"r2-pub-{qid}"]["answer"]]


class TestEntities:
    def test_ron_howard_films(self, real, gold):
        rows = real.find_entities("film", "director", "Ron Howard").rows
        titles = {r["name"].removesuffix(" (film)") for r in rows}
        for answer in gold["r2-pub-005"]["answer"]:
            assert answer["film"] in titles
        early = {r["name"].removesuffix(" (film)") for r in rows if r["facts"]["released"][:4] < "1995"}
        assert early == {a["film"] for a in gold["r2-pub-005"]["answer"]}

    def test_angus_king_governorship_facts(self, real, gold):
        [row] = real.entity_facts("Angus King", "officeholder").rows
        assert row["facts"]["order1"] == "72nd Governor of Maine"
        assert (row["facts"]["predecessor1"], row["facts"]["successor1"]) == ("John R. McKernan Jr.", "John Baldacci")
        assert gold["r2-pub-019"]["answer"] == ["John Baldacci", "John R. McKernan Jr."]
        # His Senate predecessor comes first, as the gold note says.
        assert row["facts"]["predecessor"] == "Olympia Snowe"

    def test_blunt_predecessors(self, real, gold):
        [blunt] = real.entity_facts("Matt Blunt").rows
        assert blunt["facts"]["predecessor"] == gold["r2-pub-018"]["answer"][0]
        [holden] = real.entity_facts("Bob Holden").rows
        assert holden["facts"]["predecessor"] == gold["r2-pub-018"]["answer"][1]

    def test_spielberg_budget_and_gross_are_numbers_in_units(self, real, gold):
        rows = real.find_entities("film", "director", "Steven Spielberg").rows
        under_twice = [r["name"] for r in rows
                       if {"budget", "gross"} <= set(r["numeric"])
                       and r["numeric"]["gross"]["value"] < 2 * r["numeric"]["budget"]["value"]]
        assert under_twice == [f"{gold['r2-pub-017']['answer']} (film)"]


class TestSourceRecordTools:
    def test_omnium_records_in_time_order_with_authority(self, real):
        rows = real.source_records("women's omnium").rows
        assert [(r["doc_id"], r["authority"]) for r in rows[:2]] == [
            ("SYN-LA28-S037", "operational"), ("SYN-LA28-S030", "official")]  # draft v0.7, then signed v1.0
        assert [r["published_at"][:10] for r in rows][:2] == ["2028-06-15", "2028-07-01"]

    def test_100m_records(self, real):
        rows = real.source_records("men's 100 metres", 2028).rows
        by_id = {r["doc_id"]: r for r in rows}
        assert by_id["SYN-LA28-S031"]["authority"] == "official"
        assert by_id["SYN-LA28-S031"]["published_at"] == "2028-07-23T22:15:00-07:00"
        assert by_id["SYN-LA28-S011"]["published_at"] < by_id["SYN-LA28-S031"]["published_at"]

    def test_pistol_registration_numbers_are_in_the_record_text(self, real):
        rows = real.source_records("women's 10 metre air pistol").rows
        assert any("42" in r["text"] for r in rows)


class TestTextTools:
    def test_text_search_finds_the_cocoon_director_and_reads_it(self, real):
        rows = real.text_search(["cocoon", "ron howard"], limit=5).rows
        assert rows and all("cocoon" in r["text"].lower() for r in rows)
        doc = real.read_document(rows[0]["doc_id"], max_chars=3000).rows
        assert doc and sum(len(r["text"]) for r in doc) <= 3100 and doc[0]["seq"] == 0
