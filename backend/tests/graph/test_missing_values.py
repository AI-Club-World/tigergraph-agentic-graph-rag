"""A value the infobox does not record is not a count (backlog: missing values
stored as 0). TigerGraph INT attributes have no null, so the graph stores
"not recorded" as 0; Q2/Q3 skip it and rows read back carry None."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from ogr.common.config import RunConfig
from ogr.common.contracts import format_evidence_item
from ogr.graph.client import MISSING_INT, TigerGraphClient
from ogr.pipelines.p3_agentic.agents.aggregation import run_aggregation
from ogr.pipelines.p3_agentic.agents.entity_linking import ResolvedAnchors
from ogr.pipelines.p3_agentic.intent import IntentSchema

QUERIES = Path(__file__).resolve().parents[2] / "src" / "ogr" / "graph" / "queries"


def _client(raw) -> TigerGraphClient:
    conn = MagicMock()
    conn.runInstalledQuery.return_value = raw
    return TigerGraphClient(config=RunConfig(), conn=conn)


def test_rows_read_back_carry_none_for_values_not_recorded():
    client = _client([{"results": [{
        "event_id": "e1", "competitors": MISSING_INT, "nations": 12,
        "date_year": 2012, "date_month": 8, "date_day_start": 6, "date_day_end": MISSING_INT,
        "gold": "A", "parse_confidence": 1.0,
    }]}])
    [row] = client._run_query("q1_lookup", {"event_id": "e1"})
    assert row["competitors"] is None and row["date_day_end"] is None
    assert row["nations"] == 12 and row["date_day_start"] == 6
    # The answer prompt never sees "competitors: 0".
    assert "competitors" not in format_evidence_item(row)


def test_a_count_says_how_many_events_had_no_value_to_check():
    client = _client([
        {"count_value": 3, "excluded_count": 0, "missing_count": 2},
        {"members": [{"event_id": "e1", "event_name": "A", "doc_id": "Q1", "title": "T",
                      "competitors": 12, "nations": 0, "date_year": 2012}]},
    ])
    intent = IntentSchema(
        operation="COUNT",
        constraints=[{"field": "competitors", "op": "<", "value": 20}],
        target_field="competitors",
    )
    result = run_aggregation(client, intent, ResolvedAnchors(games="2012-Summer"))
    assert result.evidence[0]["count"] == 3
    assert result.evidence[0]["not_counted_value_not_recorded"] == 2
    assert "not_counted_value_not_recorded=2" in result.notes
    assert "nations" not in result.evidence[1]  # 0 on a member is not shown either


def test_a_count_with_every_value_recorded_adds_nothing():
    client = _client([{"count_value": 3, "excluded_count": 0, "missing_count": 0}])
    intent = IntentSchema(operation="COUNT", constraints=[{"field": "nations", "op": ">", "value": 5}])
    result = run_aggregation(client, intent, ResolvedAnchors())
    assert "not_counted_value_not_recorded" not in result.evidence[0]


def test_q2_neither_counts_nor_rules_out_a_value_not_recorded():
    gsql = (QUERIES / "q2_count_where.gsql").read_text()
    for i in "01":
        guard = gsql.index(f"IF actual{i} <= 0 THEN")
        # The comparisons run only on a recorded value (the ELSE branch).
        assert gsql.index(f'IF op{i} == "<" AND NOT', guard) > gsql.index("ELSE", guard)
    assert "IF passes AND missing THEN" in gsql
    assert "IF passes AND NOT missing THEN" in gsql
    assert "@@missing_count AS missing_count" in gsql


def test_q3_does_not_rank_a_value_not_recorded():
    gsql = (QUERIES / "q3_argmax.gsql").read_text()
    assert "IF rankValue > 0 THEN" in gsql
