"""LocalR2Graph: the ten tools' matching rules and row shapes on a small corpus
built to hit each rule (word-boundary matching, ties, teams, numbered keys,
sport/season/year filters)."""

from __future__ import annotations

from ogr.r2.graph_backend import QueryResult, series_extremes


def test_every_call_returns_a_query_result_with_name_params_rows_and_ms(mini):
    result = mini.find_events(sport="Athletics", year=2016)
    assert isinstance(result, QueryResult)
    assert result.query == "r2_find_events"
    assert result.params == {"sport": "Athletics", "year": 2016, "season": "", "event_contains": ""}
    assert result.row_count == len(result.rows) == 3 and result.ms >= 0


class TestFindEvents:
    def test_filters_are_case_insensitive_and_combine(self, mini):
        assert {r["doc_id"] for r in mini.find_events(sport="athletics").rows} == {"E1", "E2", "E3", "E4"}
        assert {r["doc_id"] for r in mini.find_events(year=2020).rows} == {"J1", "J2"}
        assert {r["doc_id"] for r in mini.find_events(season="winter").rows} == {"S1", "S2"}
        assert {r["doc_id"] for r in mini.find_events(sport="Judo", year=2024).rows} == {"J3"}
        assert len(mini.find_events().rows) == 11  # no filter = everything

    def test_event_contains_starts_at_a_word_boundary(self, mini):
        # "men's 800 metres" is not inside "women's 800 metres".
        assert {r["doc_id"] for r in mini.find_events(event_contains="men's 800 metres").rows} == {"E3"}
        assert {r["doc_id"] for r in mini.find_events(event_contains="Women's 800 metres").rows} == {"E1", "E2", "E4"}
        # The title also counts: the page title carries the event name too.
        assert {r["doc_id"] for r in mini.find_events(event_contains="2016 summer olympics").rows} == {
            "E2", "E3", "E4"}

    def test_rows_carry_medallists_with_nocs_and_sort_by_year(self, mini):
        rows = mini.find_events(sport="Judo").rows
        assert [r["year"] for r in rows] == [2020, 2020, 2024]
        j1 = next(r for r in rows if r["doc_id"] == "J1")
        assert j1["bronze"] == [{"name": "Lee Mu", "noc": "JPN"}, {"name": "Max Nu", "noc": "JPN"}]
        assert j1["gold"] == [{"name": "Jon Kappa", "noc": "JPN"}]
        assert (j1["games"], j1["venue"], j1["nations"], j1["competitors"], j1["synthetic"]) == (
            "2020-Summer", "Main Arena", 30, 0, False)

    def test_synthetic_flag_comes_from_the_record(self, mini):
        assert all(r["synthetic"] for r in mini.find_events(year=2028).rows)


class TestMedalsByNation:
    def test_a_medal_is_counted_once_per_event_kind_and_place(self, mini):
        rows = {r["noc"]: r for r in mini.medals_by_nation(sport="Judo", year=2020).rows}
        # JPN: gold J1, two bronzes J1 (both JPN, so two medals), one bronze J2 = 4.
        assert rows["JPN"]["count"] == 4
        # FRA's relay-style team gold has two athletes but is one medal.
        assert rows["FRA"]["count"] == 1
        assert [r["noc"] for r in mini.medals_by_nation(sport="Judo", year=2020).rows][0] == "JPN"

    def test_medal_filter_and_events_list(self, mini):
        rows = mini.medals_by_nation(sport="Judo", year=2020, medal="gold").rows
        assert [(r["noc"], r["count"]) for r in rows] == [("FRA", 1), ("JPN", 1)]
        assert rows[1]["events"] == [{"title": "Judo at the 2020 Summer Olympics – Men's 73 kg", "doc_id": "J1"}]

    def test_year_zero_and_no_sport_mean_any(self, mini):
        rows = mini.medals_by_nation(medal="gold").rows
        assert {r["noc"]: r["count"] for r in rows}["JPN"] == 2  # J1 and J3
        assert mini.medals_by_nation(sport="Nothing").rows == []


class TestEventSeries:
    def test_one_row_per_edition_sorted_by_year_with_exact_name_preferred(self, mini):
        result = mini.event_series("women's 800 metres", sport="Athletics")
        # 2016 also has "Women's 800 metres hurdles", which contains the phrase; the exact name wins.
        assert [(r["year"], r["doc_id"], r["nations"]) for r in result.rows] == [(2012, "E1", 30), (2016, "E2", 35)]
        assert result.rows[0]["gold"] == [{"name": "Ann Alpha", "noc": "GER"}]
        assert series_extremes(result.rows) == {"max_year": 2016, "max": 35, "min_year": 2012, "min": 30}

    def test_season_and_sport_scope_the_series(self, mini):
        rows = mini.event_series("men's halfpipe", season="Winter").rows
        assert [r["year"] for r in rows] == [2018, 2022]
        assert mini.event_series("men's halfpipe", sport="Judo").rows == []

    def test_extremes_skip_unrecorded_values_and_break_ties_by_earliest_year(self):
        rows = [{"year": 2000, "nations": 20}, {"year": 2004, "nations": 20}, {"year": 2008, "nations": 0}]
        assert series_extremes(rows) == {"max_year": 2000, "max": 20, "min_year": 2000, "min": 20}


class TestAthleteMedals:
    def test_exact_name_lists_every_medal_sorted(self, mini):
        rows = mini.athlete_medals("ann alpha").rows
        assert [(r["year"], r["medal"], r["noc"], r["doc_id"]) for r in rows] == [
            (2012, "gold", "GER", "E1"), (2016, "gold", "GER", "E2")]
        assert rows[0]["event"].endswith("Women's 800 metres") and rows[0]["sport"] == "Athletics"

    def test_accents_case_and_a_surname_alone_are_found(self, mini):
        assert len(mini.athlete_medals("ANN ALPHA").rows) == 2
        assert len(mini.athlete_medals("Alpha").rows) == 2   # no exact id: word-boundary match
        assert mini.athlete_medals("Nobody Here").rows == []
        assert mini.athlete_medals("").rows == []

    def test_team_member_has_the_team_medal(self, mini):
        [row] = mini.athlete_medals("Eva Echo").rows
        assert (row["medal"], row["noc"], row["year"]) == ("gold", "FRA", 2020)


class TestRepeatWinners:
    def test_same_event_same_medal_two_games(self, mini):
        rows = mini.repeat_winners(sport="Athletics").rows
        assert [(r["athlete"], r["event_name"], r["years"], r["doc_ids"]) for r in rows] == [
            ("Ann Alpha", "Women's 800 metres", [2012, 2016], ["E1", "E2"])]

    def test_season_filter_and_medal(self, mini):
        assert [r["athlete"] for r in mini.repeat_winners(sport="Snowboarding", season="Winter").rows] == ["Qin Rho"]
        assert mini.repeat_winners(sport="Snowboarding", season="Summer").rows == []
        assert [r["athlete"] for r in mini.repeat_winners(sport="Judo", medal="gold").rows] == ["Jon Kappa"]
        # A different medal in the same event is not a repeat.
        assert mini.repeat_winners(sport="Judo", medal="silver").rows == []

    def test_no_sport_searches_all(self, mini):
        assert {r["athlete"] for r in mini.repeat_winners().rows} == {"Ann Alpha", "Jon Kappa", "Qin Rho"}


class TestEntities:
    def test_entity_facts_by_name_with_all_facts(self, mini):
        [row] = mini.entity_facts("jane governor").rows
        assert row["entity_id"] == "ent:P1" and row["entity_type"] == "officeholder" and row["doc_id"] == "P1"
        assert row["facts"]["predecessor1"] == "Old Gov" and row["facts"]["successor1"] == "New Gov"
        assert row["facts"]["jr/sr"] == "United States Senator"
        assert mini.entity_facts("jane", entity_type="film").rows == []

    def test_numeric_facts_carry_value_and_currency(self, mini):
        [row] = mini.entity_facts("splash").rows
        assert row["numeric"]["budget"] == {"value": 8e6, "note": "USD"}
        assert row["numeric"]["gross"] == {"value": 69.8e6, "note": "USD"}
        assert "director" not in row["numeric"]

    def test_find_entities_by_type_predicate_and_value(self, mini):
        rows = mini.find_entities("film", "director", "Ron Howard").rows
        assert [r["name"] for r in rows] == ["Splash (film)"]
        assert [r["name"] for r in mini.find_entities("film").rows] == ["Cocoon (film)", "Splash (film)"]
        assert [r["name"] for r in mini.find_entities(value_contains="old gov").rows] == ["Jane Governor"]

    def test_a_predicate_also_matches_its_numbered_forms(self, mini):
        assert [r["name"] for r in mini.find_entities("officeholder", "predecessor", "Old Gov").rows] == [
            "Jane Governor"]
        assert mini.find_entities("officeholder", "successor", "Old Gov").rows == []


class TestSourceRecords:
    def test_linked_records_by_event_in_time_order(self, mini):
        rows = mini.source_records(event_contains="women's individual").rows
        assert [r["doc_id"] for r in rows] == ["SYN-A"]
        assert rows[0]["authority"] == "operational" and rows[0]["events"] == ["L1"]

    def test_all_records_sorted_by_instant_not_string(self, mini):
        rows = mini.source_records().rows
        # 2029-01-20T10:00+01:00 is later than 2028-07-23T21:09-07:00.
        assert [r["doc_id"] for r in rows] == ["SYN-A", "SYN-B"]
        assert rows[1]["published_at"] == "2029-01-20T10:00:00+01:00"

    def test_year_scopes_through_the_linked_events(self, mini):
        assert [r["doc_id"] for r in mini.source_records(year=2028).rows] == ["SYN-A", "SYN-B"]
        assert mini.source_records(year=2012).rows == []

    def test_a_phrase_found_only_in_the_text_still_finds_an_unlinked_record(self, mini):
        assert [r["doc_id"] for r in mini.source_records(event_contains="gold medallist").rows] == ["SYN-B"]


class TestTextTools:
    def test_all_terms_must_occur_case_insensitively(self, mini):
        rows = mini.text_search(["ron howard"]).rows
        assert [(r["doc_id"], r["chunk_id"]) for r in rows] == [("F1", "F1_c0")]
        assert mini.text_search(["Rae SIGMA", "lakeside"]).rows[0]["doc_id"] == "L1"
        assert mini.text_search(["ron howard", "zzzz"]).rows == []
        assert mini.text_search([]).rows == []

    def test_results_sort_by_doc_then_chunk_and_respect_limit(self, mini):
        all_rows = mini.text_search(["event"], limit=100).rows
        assert [r["doc_id"] for r in all_rows] == sorted(r["doc_id"] for r in all_rows)
        assert len(mini.text_search(["event"], limit=3).rows) == 3
        assert all_rows[0]["title"]

    def test_read_document_in_order_within_a_budget(self, mini):
        rows = mini.read_document("F1").rows
        assert [r["seq"] for r in rows] == [0] and "Splash" in rows[0]["text"] and not rows[0]["truncated"]
        cut = mini.read_document("F1", max_chars=40).rows
        assert len(cut) == 1 and cut[0]["truncated"] and len(cut[0]["text"]) <= 44
        assert mini.read_document("nope").rows == []

    def test_long_document_chunks_are_read_without_the_overlap(self, tmp_path):
        import json

        from ogr.r2.corpus_model import build_model
        from ogr.r2.local_graph import LocalR2Graph

        words = [f"w{i}" for i in range(700)]
        path = tmp_path / "long.jsonl"
        path.write_text(json.dumps({"doc_id": "L", "title": "Long", "url": "u", "text": " ".join(words)}) + "\n")
        rows = LocalR2Graph(build_model(path)).read_document("L", max_chars=100000).rows
        assert len(rows) == 3
        assert " ".join(r["text"] for r in rows).split() == words  # continuous, nothing repeated
