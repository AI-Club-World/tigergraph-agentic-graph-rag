"""TigerGraphR2: parameters sent to the installed queries, and the mapping of
their rows (GSQL-shaped, nested lists as delimited strings) to the dicts
LocalR2Graph returns. A fake client stands in for `_run_query`."""

from __future__ import annotations

from ogr.r2.graph_backend import QUERY_NAMES, QueryResult, R2Graph, TigerGraphR2
from ogr.r2.local_graph import LocalR2Graph


class FakeClient:
    def __init__(self, rows=None, errors=None):
        self.rows = rows or {}
        self.calls: list[tuple[str, dict]] = []
        self.errors = list(errors or [])

    def _run_query(self, query, params):
        self.calls.append((query, params))
        return self.rows.get(query, [])

    def drain_errors(self):
        out, self.errors = self.errors, []
        return out


def test_both_implementations_satisfy_the_protocol_and_cover_ten_tools(mini):
    assert len(QUERY_NAMES) == 10 and set(QUERY_NAMES.values()) == {f"r2_{n}" for n in QUERY_NAMES}
    for impl in (TigerGraphR2(FakeClient()), mini):
        graph: R2Graph = impl
        for tool in QUERY_NAMES:
            assert callable(getattr(graph, tool))


def test_every_call_goes_through_one_query_and_returns_name_params_rows_ms():
    client = FakeClient({"r2_find_events": [{"event_id": "e1", "doc_id": "d1", "title": "T", "year": 2024}]})
    result = TigerGraphR2(client).find_events(sport="Judo", year=2024, event_contains="Men’s 73 kg")
    assert isinstance(result, QueryResult)
    assert client.calls == [("r2_find_events", {
        "sport": "Judo", "year": 2024, "season": "", "event_contains": "men's 73 kg"})]
    assert result.query == "r2_find_events" and result.params == client.calls[0][1]
    assert result.row_count == 1 and result.ms >= 0 and result.error == ""


def test_a_failed_query_reports_its_error_instead_of_looking_like_no_matches():
    client = FakeClient(errors=["r2_find_events: boom"])
    result = TigerGraphR2(client).find_events()
    assert result.rows == [] and result.error == "r2_find_events: boom"


def test_find_events_maps_missing_values_and_decodes_medallists(mini):
    raw = {"event_id": "e1", "doc_id": "d1", "title": "Judo at the 2020 Summer Olympics – Men's 73 kg",
           "event_name": "Men's 73 kg", "sport": "Judo", "games": "2020-Summer", "year": 2020,
           "season": "Summer", "date_text": "", "venue": None, "competitors": None, "nations": 30,
           "medallists": "bronze\tMax Nu\tJPN\t2\nbronze\tLee Mu\tJPN\t1\ngold\tJon Kappa\tJPN\t1\n",
           "synthetic": False}
    [row] = TigerGraphR2(FakeClient({"r2_find_events": [raw]})).find_events().rows
    assert row["venue"] == "" and row["competitors"] == 0 and row["nations"] == 30
    assert row["gold"] == [{"name": "Jon Kappa", "noc": "JPN"}]
    assert row["bronze"] == [{"name": "Lee Mu", "noc": "JPN"}, {"name": "Max Nu", "noc": "JPN"}]  # by place
    assert row["silver"] == [] and row["games"] == "2020-Summer"
    assert set(row) == set(mini.find_events(sport="Judo").rows[0])  # same row shape as the local tool


def test_event_year_without_a_games_edge_is_zero():
    [row] = TigerGraphR2(FakeClient({"r2_find_events": [{"event_id": "e", "year": 2147483647}]})).find_events().rows
    assert row["year"] == 0


def test_medals_by_nation_decodes_events_and_sorts_most_first():
    rows = [
        {"noc": "FRA", "medal_count": 1, "events": "Judo – Mixed team\tJ2\n"},
        {"noc": "JPN", "medal_count": 4, "events": "B title\tJ3\nA title\tJ1\n"},
        {"noc": "GEO", "medal_count": 1, "events": ""},
    ]
    result = TigerGraphR2(FakeClient({"r2_medals_by_nation": rows})).medals_by_nation("Judo", 2020, "", "Gold")
    assert result.params == {"sport": "Judo", "year": 2020, "season": "", "medal": "gold"}
    assert [(r["noc"], r["count"]) for r in result.rows] == [("JPN", 4), ("FRA", 1), ("GEO", 1)]
    assert result.rows[0]["events"] == [{"title": "A title", "doc_id": "J1"}, {"title": "B title", "doc_id": "J3"}]


def test_event_series_keeps_one_row_per_edition_preferring_the_exact_name():
    base = {"season": "Summer", "competitors": 0, "medallists": "gold\tAnn Alpha\tGER\t1\n"}
    rows = [
        {**base, "year": 2016, "event_id": "x", "title": "T hurdles", "doc_id": "E4", "event_name": "h",
         "nations": 20, "exact": False},
        {**base, "year": 2016, "event_id": "y", "title": "T", "doc_id": "E2", "event_name": "n", "nations": 35,
         "exact": True},
        {**base, "year": 2012, "event_id": "z", "title": "T", "doc_id": "E1", "event_name": "n", "nations": 30,
         "exact": True},
    ]
    result = TigerGraphR2(FakeClient({"r2_event_series": rows})).event_series("Women’s 800 metres", "Athletics")
    assert result.params["event_contains"] == "women's 800 metres"
    assert [(r["year"], r["doc_id"], r["nations"]) for r in result.rows] == [(2012, "E1", 30), (2016, "E2", 35)]
    assert result.rows[0]["gold"] == [{"name": "Ann Alpha", "noc": "GER"}] and "exact" not in result.rows[0]


def test_athlete_name_is_normalized_before_the_call():
    client = FakeClient({"r2_athlete_medals": [
        {"athlete": "Áron Szilágyi", "athlete_id": "aron szilagyi", "medal": "gold", "noc": "HUN",
         "title": "Fencing – Men's sabre", "event_name": "Men's sabre", "sport": "Fencing", "year": 2016,
         "doc_id": "D2"},
        {"athlete": "Áron Szilágyi", "athlete_id": "aron szilagyi", "medal": "gold", "noc": "HUN",
         "title": "Fencing – Men's sabre", "event_name": "Men's sabre", "sport": "Fencing", "year": 2012,
         "doc_id": "D1"},
    ]})
    result = TigerGraphR2(client).athlete_medals("Áron  Szilágyi")
    assert client.calls[0][1] == {"name": "aron szilagyi"}
    assert [r["year"] for r in result.rows] == [2012, 2016] and result.rows[0]["event"].endswith("sabre")


def test_repeat_winners_rows_fold_into_years_and_doc_ids():
    rows = [
        {"athlete": "Kayla Harrison", "event_name": "Women's 78 kg", "event_key": "womens 78 kg",
         "sport": "Judo", "medal": "gold", "year": 2016, "doc_id": "B"},
        {"athlete": "Kayla Harrison", "event_name": "Women's judo 78 kg category", "event_key": "womens 78 kg",
         "sport": "Judo", "medal": "gold", "year": 2012, "doc_id": "A"},
        {"athlete": "Solo Winner", "event_name": "Men's 60 kg", "event_key": "mens 60 kg", "sport": "Judo",
         "medal": "gold", "year": 2012, "doc_id": "C"},
    ]
    result = TigerGraphR2(FakeClient({"r2_repeat_winners": rows})).repeat_winners("Judo", "Gold", "")
    assert result.params == {"sport": "Judo", "medal": "gold", "season": ""}
    assert result.rows == [{"athlete": "Kayla Harrison", "event_name": "Women's 78 kg", "sport": "Judo",
                            "medal": "gold", "years": [2012, 2016], "doc_ids": ["A", "B"]}]


def test_entity_rows_decode_facts_and_numbers_and_find_entities_sends_numbered_predicates():
    facts = ("director\tRon Howard\t0\t0.0\t\nbudget\t$8 million\t1\t8000000.0\tUSD\npredecessor1\tOld\t0\t0.0\t\n")
    row = {"entity_id": "ent:F1", "name": "Splash (film)", "entity_type": "film", "doc_id": "F1", "facts": facts}
    client = FakeClient({"r2_find_entities": [row], "r2_entity_facts": [row]})
    graph = TigerGraphR2(client)
    [found] = graph.find_entities("Film", "Director", "Ron Howard").rows
    assert found["facts"]["director"] == "Ron Howard" and found["numeric"] == {
        "budget": {"value": 8e6, "note": "USD"}}
    params = client.calls[0][1]
    assert params["entity_type"] == "film" and params["predicate"] == "director"
    assert "director" in params["predicate_variants"] and "director2" in params["predicate_variants"]
    assert graph.find_entities().rows[0]["name"] == "Splash (film)"
    assert client.calls[1][1]["predicate_variants"] == []
    graph.entity_facts("Angus King")
    assert client.calls[2][1] == {"name_contains": "angus king", "entity_type": ""}


def test_source_records_sort_by_instant_and_decode_events():
    rows = [
        {"doc_id": "B", "title": "late", "source_name": "S", "authority": "official",
         "published_at": "2029-01-20T10:00:00+01:00", "published_text": "x", "text": "t", "events": "E2\nE1\n"},
        {"doc_id": "A", "title": "early", "source_name": "S", "authority": "operational",
         "published_at": "2028-07-23T21:09:00-07:00", "published_text": "y", "text": "t", "events": ""},
    ]
    result = TigerGraphR2(FakeClient({"r2_source_records": rows})).source_records("Women's omnium", 2028)
    assert [r["doc_id"] for r in result.rows] == ["A", "B"]
    assert result.rows[1]["events"] == ["E1", "E2"] and result.rows[0]["events"] == []


def test_text_search_passes_limit_as_max_rows_trims_and_limits():
    long_text = "word " * 1000
    rows = [{"doc_id": "B", "title": "b", "chunk_id": "B_c0", "seq": 0, "text": long_text},
            {"doc_id": "A", "title": "a", "chunk_id": "A_c1", "seq": 1, "text": "short"},
            {"doc_id": "A", "title": "a", "chunk_id": "A_c0", "seq": 0, "text": "short"}]
    client = FakeClient({"r2_text_search": rows})
    result = TigerGraphR2(client).text_search(["Ron Howard", " "], limit=2)
    assert client.calls[0][1] == {"terms": ["ron howard"], "max_rows": 2}
    assert [r["chunk_id"] for r in result.rows] == ["A_c0", "A_c1"]
    assert len(TigerGraphR2(client).text_search(["x"], limit=5).rows[-1]["text"]) < 2600


def test_read_document_applies_the_budget_and_drops_the_chunk_overlap():
    words = [f"w{i}" for i in range(700)]
    chunks = [(0, words[:300]), (1, words[250:550]), (2, words[500:])]
    raw = [{"doc_id": "D", "title": "t", "chunk_id": f"D_c{i}", "seq": i, "text": " ".join(w)}
           for i, w in reversed(chunks)]
    result = TigerGraphR2(FakeClient({"r2_read_document": raw})).read_document("D", max_chars=100000)
    assert [r["seq"] for r in result.rows] == [0, 1, 2]
    assert " ".join(r["text"] for r in result.rows).split() == words
    short = TigerGraphR2(FakeClient({"r2_read_document": raw})).read_document("D", max_chars=50)
    assert len(short.rows) == 1 and short.rows[0]["truncated"]
