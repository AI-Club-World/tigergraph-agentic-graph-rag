"""Round 2: the agent weighs claims when they matter, and only then.

A fake graph with the fact layer: claims for one event that changed over
time or disagree. Round-1 behaviour (no fact layer, or one firm value) is
unchanged; that is pinned here as well as by the rest of the suite."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from ogr.common.config import RunConfig
from ogr.datasets.base import ClaimRecord, claim_id
from ogr.pipelines.p2_graphrag import run_p2_graphrag
from ogr.pipelines.p3_agentic.agents.entity_linking import EntityLinker
from ogr.pipelines.p3_agentic.orchestrator import run_p3_agentic

pytestmark = pytest.mark.usefixtures("fake_embedder")

TITLE = "Athletics at the 2012 Summer Olympics – Men's 800 metres"
EVENT = "athletics-2012-Summer-men-s-800-metres"


def claim(value, source, observed=None, *, revision=False, hedged=False, num=None):
    return ClaimRecord(
        claim_id=claim_id(source, value, observed), doc_id=f"D-{source}-{observed}", dataset_id="t",
        subject_id=EVENT, subject_name=TITLE, predicate="gold", value_text=value, value_num=num,
        observed_at=observed, source_id=source, hedged=hedged,
        hedge_terms=["reportedly"] if hedged else [], revision=revision,
    )


ORIGINAL = claim("Runner A", "src:wikipedia.org")
REVISED = claim("Runner B", "src:results-office", "2018-05-07", revision=True)


class FakeGraph:
    def __init__(self, claims, enabled=True, reliability=None):
        self._claims = claims
        self.enabled = enabled
        self.reliability = reliability or {}
        self.queries: list[str] = []

    def has_claims(self):
        return self.enabled

    def claims(self, subject_ids, predicate="", dataset_ids=None):
        self.queries.append("q6_claims")
        return [c for c in self._claims if c.subject_id in subject_ids and (not predicate or c.predicate == predicate)]

    def source_reliability(self):
        return self.reliability

    def _run_query(self, name, params):
        self.queries.append(name)
        if name == "q1_lookup":
            return [{"event_id": EVENT, "event_name": "Men's 800 metres", "title": TITLE, "doc_id": "Q800",
                     "gold": "Runner A"}]
        return []

    def hybrid_search(self, query_vector, k=10, vtype="Chunk", candidate_set=None, embedding_model=None,
                      dataset_ids=None):
        self.queries.append("q5_hybrid_search")
        return [{"chunk_id": "c1", "doc_id": "D1", "text": "Some prose about the 800 metres.", "score": 0.5}]


def _model(answer: str):
    model = MagicMock()
    intent = MagicMock()
    intent.content = json.dumps({"operation": "LOOKUP", "anchor": {"title": TITLE}, "target_field": "gold"})
    intent.tool_calls = []
    intent.usage_metadata = {"input_tokens": 40, "output_tokens": 10, "total_tokens": 50}
    intent.response_metadata = {}
    reply = MagicMock()
    reply.content = json.dumps({"answer": answer, "explanation": "From the evidence."})
    reply.tool_calls = []
    reply.usage_metadata = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
    reply.response_metadata = {}
    model.invoke.side_effect = [intent] + [reply] * 6
    model.bind_tools.return_value = model
    return model


def _linker():
    return EntityLinker(games_vocab=["2012-Summer"], sports_vocab=["Athletics"], venues_vocab=[])


def _p3(question, graph, answer):
    model = _model(answer)
    record = run_p3_agentic(question, llm_model=model, tg_client=graph, entity_linker=_linker(),
                            config=RunConfig(llm_supports_tool_calling="false"))
    return record, model


class TestP3:
    def test_a_revised_result_is_resolved_and_the_model_is_overruled(self):
        graph = FakeGraph([ORIGINAL, REVISED])
        record, model = _p3(f"Who is currently credited with the gold medal in {TITLE}?", graph, "Runner A")
        assert record.answer == "Runner B"
        assert record.stop_reason == "conflict_resolved"
        assert record.temporal_scope["mode"] == "latest"
        assert 0 < record.confidence <= 1
        [conflict] = record.conflicts
        assert conflict["chosen"]["value"] == "Runner B" and conflict["superseded"][0]["value"] == "Runner A"
        steps = {s.agent_type: s for s in record.trace}
        assert steps["conflict_resolution"].details["chosen"]["value"] == "Runner B"
        assert "answer set to the resolved value" in steps["answer_verification"].notes
        assert model.invoke.call_count == 2  # intent parse + answer; no groundedness call for claims
        assert sum(s.tokens.total for s in record.trace) == record.tokens.total

    def test_original_asks_for_the_first_statement(self):
        graph = FakeGraph([ORIGINAL, REVISED])
        record, _ = _p3(f"Who was originally awarded the gold medal in {TITLE}?", graph, "Runner A")
        assert record.answer == "Runner A" and record.temporal_scope["mode"] == "original"

    def test_a_narrow_margin_earns_one_corroborating_search(self):
        tied = [claim("Runner A", "src:a", "2013-01-01"), claim("Runner C", "src:b", "2013-01-01")]
        graph = FakeGraph(tied, reliability={"src:a": 0.6, "src:b": 0.6})
        record, _ = _p3(f"Who won the gold medal in {TITLE}?", graph, "Runner A")
        assert graph.queries.count("q5_hybrid_search") == 1
        assert record.stop_reason == "conflict_resolved"
        assert record.confidence is not None and record.confidence < 0.6

    def test_one_firm_value_keeps_the_round1_route(self):
        graph = FakeGraph([ORIGINAL])
        record, _ = _p3(f"Who won the gold medal in {TITLE}?", graph, "Runner A")
        assert not any(s.agent_type == "conflict_resolution" for s in record.trace)
        assert record.confidence is None and record.conflicts is None and record.temporal_scope is None
        assert record.stop_reason == "direct_route"

    def test_a_graph_without_the_fact_layer_is_never_asked_for_claims(self):
        graph = FakeGraph([ORIGINAL, REVISED], enabled=False)
        record, _ = _p3(f"Who is currently credited with the gold medal in {TITLE}?", graph, "Runner A")
        assert "q6_claims" not in graph.queries
        assert record.confidence is None and record.conflicts is None


def test_p2_takes_the_claims_as_its_one_query_and_reports_no_confidence():
    graph = FakeGraph([ORIGINAL, REVISED])
    record = run_p2_graphrag(f"Who is currently credited with the gold medal in {TITLE}?", client=graph,
                             config=RunConfig(llm_supports_tool_calling="false"),
                             model=_model("Runner B"), entity_linker=_linker())
    assert "q6_claims" in graph.queries and "q5_hybrid_search" not in graph.queries
    assert record.answer == "Runner B"
    assert record.confidence is None and record.conflicts is None
