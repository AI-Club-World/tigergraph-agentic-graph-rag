"""Static checks on the Round-2 answer-layer GSQL (it cannot run here): the
schema job adds only what the queries use and never drops; every query has the
parameters TigerGraphR2 sends, prints its rows under one key, and installs."""

from __future__ import annotations

import re

import pytest

from ogr.graph.schema import QUERIES_DIR, R2_ANSWER_SCHEMA_PATH, R2_QUERY_FILES, ROUND2_SCHEMA_PATH
from ogr.r2.graph_backend import QUERY_NAMES, TigerGraphR2

TOOL_CALLS = {
    "find_events": dict(sport="Judo", year=2020, season="Summer", event_contains="x"),
    "medals_by_nation": dict(sport="Judo", year=2020, season="Summer", medal="gold"),
    "event_series": dict(event_contains="x", sport="Judo", season="Summer"),
    "athlete_medals": dict(name="x"),
    "repeat_winners": dict(sport="Judo", medal="gold", season="Summer"),
    "entity_facts": dict(name_contains="x", entity_type="film"),
    "find_entities": dict(entity_type="film", predicate="director", value_contains="x"),
    "source_records": dict(event_contains="x", year=2028),
    "text_search": dict(terms=["a", "b"], limit=5),
    "read_document": dict(doc_id="d"),
}
# Required by the spec's tool table (§3), under the names the tools use.
SPEC_PARAMS = {
    "r2_find_events": {"sport", "year", "season", "event_contains"},
    "r2_medals_by_nation": {"sport", "year", "season", "medal"},
    "r2_event_series": {"event_contains", "sport", "season"},
    "r2_athlete_medals": {"name"},
    "r2_repeat_winners": {"sport", "medal", "season"},
    "r2_entity_facts": {"name_contains", "entity_type"},
    "r2_find_entities": {"entity_type", "predicate", "value_contains"},
    "r2_source_records": {"event_contains", "year"},
    "r2_text_search": {"terms"},
    "r2_read_document": {"doc_id"},
}
KNOWN_EDGES = {
    "IN_SPORT", "AT_GAMES", "HELD_AT", "HAS_CHUNK", "reverse_DESCRIBES", "WON", "reverse_WON",
    "reverse_REPORTS_ON", "reverse_ABOUT",
}
KNOWN_VERTICES = {"OlympicEvent", "Sport", "Games", "Venue", "Document", "Chunk", "Athlete", "SourceRecord",
                  "Entity", "Claim"}


def _text(name: str) -> str:
    return (QUERIES_DIR / f"{name}.gsql").read_text(encoding="utf-8")


def _declared_params(text: str) -> dict[str, bool]:
    """name -> has a default, from `CREATE OR REPLACE QUERY name(...) FOR GRAPH`."""
    head = re.search(r"CREATE OR REPLACE QUERY \w+\((.*?)\)\s*FOR GRAPH", text, re.S).group(1)
    params = {}
    for part in re.split(r",(?![^<]*>)", head):
        match = re.match(r"\s*(?:(?:SET|LIST)<\w+>|\w+)\s+(\w+)\s*(=.*)?$", part.strip(), re.S)
        params[match.group(1)] = match.group(2) is not None
    return params


def test_ten_query_files_for_ten_tools():
    assert len(R2_QUERY_FILES) == 10
    assert {f.removesuffix(".gsql") for f in R2_QUERY_FILES} == set(QUERY_NAMES.values())


@pytest.mark.parametrize("name", sorted(QUERY_NAMES.values()))
class TestQueryFile:
    def test_header_install_and_no_drop(self, name):
        text = _text(name)
        assert text.startswith("USE GRAPH OlympicGraphRAG")
        assert f"CREATE OR REPLACE QUERY {name}(" in text
        assert "FOR GRAPH OlympicGraphRAG SYNTAX V2" in text
        assert text.rstrip().endswith(f"INSTALL QUERY {name}")
        code = "\n".join(line for line in text.splitlines() if not line.strip().startswith("//"))
        assert "DROP" not in code.upper()

    def test_rows_are_printed_as_one_list_under_one_key(self, name):
        text = _text(name)
        assert len(re.findall(r"^\s*PRINT ", text, re.M)) == 1  # client._run_query unwraps the first list
        assert re.search(r"PRINT @@rows AS results;", text)

    def test_declares_the_spec_parameters(self, name):
        declared = set(_declared_params(_text(name)))
        assert SPEC_PARAMS[name] <= declared

    def test_uses_only_edges_and_vertices_of_the_schema(self, name):
        text = _text(name)
        assert set(re.findall(r"\(([A-Za-z_]+)>", text)) <= KNOWN_EDGES
        # The vertex type at the far end of every traversed edge, and the types selected directly.
        targets = set(re.findall(r">(?::\w+)?\)-\s*([A-Z][A-Za-z]+):", text))
        direct = set(re.findall(r"FROM (OlympicEvent|Chunk|Document|Athlete|Entity|SourceRecord|Claim):", text))
        assert (targets | direct) <= KNOWN_VERTICES, (targets | direct) - KNOWN_VERTICES
        assert targets, "every query traverses at least one edge"


@pytest.mark.parametrize("tool", sorted(TOOL_CALLS))
def test_wrapper_sends_exactly_the_declared_parameters(tool):
    class Recorder:
        params = None

        def _run_query(self, query, params):
            self.query, self.params = query, params
            return []

    recorder = Recorder()
    getattr(TigerGraphR2(recorder), tool)(**TOOL_CALLS[tool])
    declared = _declared_params(_text(recorder.query))
    assert set(recorder.params) <= set(declared)
    assert {n for n, has_default in declared.items() if not has_default} <= set(recorder.params)


def test_text_search_limit_is_max_rows_because_limit_is_a_keyword():
    text = _text("r2_text_search")
    assert "INT max_rows" in text and not re.search(r"\bINT limit\b", text)
    assert "LIST<STRING> terms" in text and "lower(c.text) LIKE" in text


def test_answer_schema_job_adds_the_four_types_and_never_drops():
    text = R2_ANSWER_SCHEMA_PATH.read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.strip().startswith("//"))
    assert "DROP" not in code.upper()
    assert "CREATE SCHEMA_CHANGE JOB add_r2_answer_types FOR GRAPH OlympicGraphRAG" in text
    assert "RUN SCHEMA_CHANGE JOB add_r2_answer_types" in text
    assert "ADD VERTEX Athlete (" in text and "ADD VERTEX SourceRecord (" in text
    won = re.search(r"ADD DIRECTED EDGE WON \((.*?)\)\s*WITH REVERSE_EDGE=\"reverse_WON\"", text, re.S).group(1)
    assert "FROM Athlete, TO OlympicEvent" in won
    for attr in ("medal STRING", "noc STRING", "place INT", "event_key STRING"):
        assert attr in won
    assert re.search(r"ADD DIRECTED EDGE REPORTS_ON \(\s*FROM SourceRecord, TO OlympicEvent, score DOUBLE\s*\)"
                     r"\s*WITH REVERSE_EDGE=\"reverse_REPORTS_ON\"", text)
    for attr in ("source_name", "authority", "published_at", "published_text", "text"):
        assert f"{attr} STRING" in text
    assert "ALTER VERTEX" not in text


def test_claim_vertex_has_a_note_for_the_unit_of_value_num():
    assert "value_note STRING" in ROUND2_SCHEMA_PATH.read_text(encoding="utf-8")


def test_entity_queries_read_value_note_and_the_facts_encoding_matches_the_decoder():
    for name in ("r2_entity_facts", "r2_find_entities"):
        text = _text(name)
        assert "c.value_note" in text and "c.has_num" in text and 'ABOUT' in text
