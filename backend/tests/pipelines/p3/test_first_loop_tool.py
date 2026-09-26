"""Loop routing picks the query that can answer (backend review B2-B4)."""

from __future__ import annotations

from ogr.common.config import RunConfig
from ogr.graph.client import TigerGraphClient
from ogr.pipelines.p3_agentic.agents.entity_linking import ResolvedAnchors
from ogr.pipelines.p3_agentic.agents.multi_hop import run_multi_hop, run_venue_events
from ogr.pipelines.p3_agentic.intent import IntentSchema
from ogr.pipelines.p3_agentic.router import first_loop_tool


class _Recording(TigerGraphClient):
    def __init__(self, answers):
        super().__init__(config=RunConfig(), mock_chunks=[])
        self.answers, self.calls = answers, []

    def _run_query(self, name, params):
        self.calls.append((name, dict(params)))
        return self.answers(name, params)


def test_first_loop_tool_cases():
    lookup = IntentSchema(operation="LOOKUP")
    traverse = IntentSchema(operation="TRAVERSE")
    assert first_loop_tool(lookup, ResolvedAnchors(title="Men's marathon")) == "lookup"
    assert first_loop_tool(traverse, ResolvedAnchors(title="Men's marathon")) == "multi_hop"
    assert first_loop_tool(lookup, ResolvedAnchors(venue="Richmond Olympic Oval")) == "venue"
    assert first_loop_tool(traverse, ResolvedAnchors(games="2016-Summer")) == "traversal"


def test_multi_hop_starts_from_the_anchor_edition_only():
    def answers(name, params):
        if name == "q1_lookup" and params.get("title"):
            return [{"event_id": "athletics-2012-Summer-m20kw", "date_year": 2012},
                    {"event_id": "athletics-2016-Summer-m20kw", "date_year": 2016}]
        if name == "q4_traverse":
            return [{"event_id": "athletics-2012-Summer-m20kw"}]
        return [{"event_id": params["event_id"], "gold": "Chen Ding", "doc_id": "Q5"}]

    client = _Recording(answers)
    intent = IntentSchema(operation="TRAVERSE", target_field="gold")
    result = run_multi_hop(client, intent, ResolvedAnchors(title="Men's 20 km walk", games="2016-Summer"))

    q4 = [p for n, p in client.calls if n == "q4_traverse"]
    assert q4 == [{"anchor": "athletics-2016-Summer-m20kw", "edge_type": "PREV_EDITION", "hops": 1}]
    assert result.evidence[0]["value"] == "Chen Ding" and result.evidence[0]["doc_id"] == "Q5"


def test_venue_expansion_uses_held_at_then_q1_narrowed_to_games():
    def answers(name, params):
        if name == "q4_traverse":
            return [{"event_id": "ss-2010-Winter-m500"}, {"event_id": "ss-2006-Winter-m500"}]
        year = 2010 if "2010" in params["event_id"] else 2006
        return [{"event_id": params["event_id"], "date_year": year, "gold": f"winner {year}", "doc_id": "Q7"}]

    client = _Recording(answers)
    result = run_venue_events(
        client, IntentSchema(operation="LOOKUP", target_field="gold"),
        ResolvedAnchors(venue="Richmond Olympic Oval", games="2010-Winter"),
    )
    assert client.calls[0] == ("q4_traverse", {"anchor": "Richmond Olympic Oval", "edge_type": "HELD_AT", "hops": 1})
    assert [e["value"] for e in result.evidence] == ["winner 2010"]
    assert result.evidence[0]["source"] == "multi_hop"
