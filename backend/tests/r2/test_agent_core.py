"""The Round-2 agent over LocalR2Graph with a scripted fake chat model."""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage

from ogr.common.config import RunConfig
from ogr.r2.agent import answer_question
from ogr.r2.output import validate
from ogr.r2.querylog import QueryLog
from ogr.r2.tools import MAX_ROWS, ToolContext, run_tool
from ogr.r2.trace import TraceRecorder

CONFIG = RunConfig(llm_max_retries=2, llm_backoff_base_s=0.0)


def call(name, cid="c1", **args):
    return {"name": name, "args": args, "id": cid, "type": "tool_call"}


def msg(*calls, content="", usage=(100, 10)):
    m = AIMessage(content=content, tool_calls=list(calls))
    if usage:
        m.usage_metadata = {"input_tokens": usage[0], "output_tokens": usage[1], "total_tokens": sum(usage)}
    return m


class FakeModel:
    """Returns the scripted responses in order; records what it was sent and how it was bound."""

    def __init__(self, script):
        self.script = list(script)
        self.sent: list[list] = []
        self.bindings: list[tuple[list[str], object]] = []
        self._pending = None

    def bind_tools(self, specs, tool_choice=None, **_):
        clone = FakeModel.__new__(FakeModel)
        clone.__dict__ = self.__dict__  # share the script and logs
        self._pending = ([s["function"]["name"] for s in specs], tool_choice)
        self.bindings.append(self._pending)
        return clone

    def invoke(self, messages, **_):
        self.sent.append(list(messages))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class RateLimitError(Exception):
    """Named like the providers' exception so common/llm treats it as a retryable 429."""


def finish(status="answered", answer="x", explanation="e", citations=(), cid="f1"):
    return call("finish", cid, status=status, answer=answer, explanation=explanation,
                citations=list(citations))


def test_tool_loop_trace_tokens_and_validation(mini, tmp_path):
    model = FakeModel([
        msg(call("find_events", sport="Athletics", event_contains="800 metres")),
        msg(call("event_series", "c2", event_contains="Women's 800 metres"), usage=(200, 20)),
        msg(finish(answer='{"winner": "Ann Alpha"}', citations=["E1", "E2", "NOPE", "E1"]), usage=(300, 30)),
    ])
    log = QueryLog(tmp_path / "log.jsonl")
    rec = answer_question("q1", "Who won?", mini, model, CONFIG, querylog=log)
    assert rec.status == "answered" and rec.answer == {"winner": "Ann Alpha"}
    assert rec.citations == ["E1", "E2"]  # only doc_ids the tools returned, deduped, in order
    assert (rec.input_tokens, rec.output_tokens) == (600, 60)
    tools = [s["tool"] for s in rec.trace]
    assert tools == ["plan", "find_events", "llm_step", "event_series", "llm_step"]
    tg = [s for s in rec.trace if s.get("query")]
    # LocalR2Graph steps are never TigerGraph steps and never reach the query log
    assert all(s["tigergraph"] is False for s in tg)
    assert tg[0]["query"] == "r2_find_events" and tg[0]["params"]["sport"] == "Athletics"
    assert tg[0]["rows"] >= 1 and isinstance(tg[0]["ms"], int)
    assert not (tmp_path / "log.jsonl").exists()
    errors, _ = validate(rec)
    assert errors == []
    assert [b[1] for b in model.bindings] == [None]


def test_tigergraph_steps_hit_query_log(tmp_path):
    class Fake:
        def find_events(self, **kw):
            from ogr.r2.graph_backend import QueryResult
            return QueryResult("r2_find_events", kw, [{"doc_id": "D1", "title": "T"}], 12.0)

    log = QueryLog(tmp_path / "log.jsonl")
    trace = TraceRecorder("q", log)
    out = json.loads(run_tool(Fake(), "find_events", {"sport": "X", "year": "2012"}, trace))
    assert out["total_rows"] == 1
    step = trace.to_list()[0]
    assert step["tigergraph"] is True and step["query"] == "r2_find_events" and step["params"]["year"] == 2012
    line = json.loads((tmp_path / "log.jsonl").read_text())
    assert line["qid"] == "q" and line["rows"] == 1 and line["step"] == 1


def test_not_in_corpus_answer_is_null_and_invalid_status_is_partial(mini):
    rec = answer_question("q", "?", mini, FakeModel([msg(finish("not_in_corpus", answer="a guess"))]), CONFIG)
    assert rec.status == "not_in_corpus" and rec.answer is None and validate(rec)[0] == []
    rec = answer_question("q", "?", mini, FakeModel([msg(finish("maybe", answer="a"))]), CONFIG)
    assert rec.status == "partial" and rec.answer == "a"
    rec = answer_question("q", "?", mini, FakeModel([msg(finish("answered", answer=""))]), CONFIG)
    assert rec.status == "not_in_corpus" and rec.answer is None


def test_forced_finish_at_max_steps(mini):
    model = FakeModel([
        msg(call("find_events", "a")), msg(call("find_events", "b")),
        msg(finish(answer="done"), usage=(50, 5)),
    ])
    rec = answer_question("q", "?", mini, model, CONFIG, max_steps=2)
    assert rec.answer == "done"
    assert [s["tool"] for s in rec.trace] == ["plan", "find_events", "llm_step", "find_events", "llm_answer"]
    assert model.bindings[-1] == (["finish"], "finish")
    assert "budget" in str(model.sent[-1][-1].content)


def test_calls_beyond_budget_are_skipped_but_answered(mini):
    model = FakeModel([msg(call("find_events", "a"), call("find_events", "b")), msg(finish(answer="ok"))])
    rec = answer_question("q", "?", mini, model, CONFIG, max_steps=1)
    assert sum(1 for s in rec.trace if s.get("query")) == 1
    tool_msgs = [m for m in model.sent[-1] if m.type == "tool"]
    assert len(tool_msgs) == 2 and "budget" in tool_msgs[1].content


def test_error_isolation_and_rate_limit_retry(mini):
    boom = answer_question("q", "?", mini, FakeModel([RuntimeError("provider down")]), CONFIG)
    assert boom.status == "partial" and boom.answer is None and "provider down" in boom.explanation
    assert boom.trace and boom.input_tokens == 0
    # a transient 429 is retried; the successful call's tokens are the ones counted
    flaky = FakeModel([RateLimitError("slow down"), msg(finish(answer="fine"))])
    rec = answer_question("q", "?", mini, flaky, CONFIG)
    assert rec.answer == "fine" and rec.input_tokens == 100
    # bounded: after the retries the failure is recorded as a partial record, the run goes on
    dead = FakeModel([RateLimitError("slow down")] * 3)
    rec = answer_question("q", "?", mini, dead, CONFIG)
    assert rec.status == "partial" and rec.answer is None and "rate limit" in rec.explanation.lower()


def test_estimated_tokens_are_marked(mini):
    model = FakeModel([msg(finish(answer="a"), usage=None)])
    rec = answer_question("q", "?", mini, model, CONFIG)
    assert rec.trace[0]["note"].startswith("tokens estimated") and rec.input_tokens > 0


def test_tool_errors_and_unknown_tools_do_not_raise(mini):
    trace = TraceRecorder("q")
    assert "unknown tool" in run_tool(mini, "nope", {}, trace)
    assert "missing required" in run_tool(mini, "event_series", {}, trace)
    assert trace.to_list() == []


def test_compact_output_caps_rows_and_states_truncation():
    class Big:
        def find_events(self, **kw):
            from ogr.r2.graph_backend import QueryResult
            rows = [{"doc_id": f"D{i}", "title": "T", "empty": "", "none": None, "n": 0, "text": "x" * 5000}
                    for i in range(200)]
            return QueryResult("r2_find_events", kw, rows, 1.0)

    ctx = ToolContext()
    out = json.loads(run_tool(Big(), "find_events", {}, TraceRecorder("q"), ctx))
    assert out["total_rows"] == 200 and out["shown_rows"] < MAX_ROWS + 1 and "truncated" in out
    assert "empty" not in out["rows"][0] and "none" not in out["rows"][0] and "n" not in out["rows"][0]
    assert len(ctx.seen_doc_ids) == out["shown_rows"]  # only shown rows count as seen


def test_rank_rows_is_a_local_step(mini):
    trace = TraceRecorder("q")
    ctx = ToolContext()
    first = json.loads(run_tool(mini, "medals_by_nation", {"sport": "Athletics"}, trace, ctx))
    ranked = json.loads(run_tool(mini, "rank_rows", {"result_id": first["result_id"], "field": "count",
                                                     "order": "asc", "top_n": 1}, trace, ctx))
    counts = [r["count"] for r in ranked["rows"]]
    assert len(counts) == 1 and counts[0] == min(r["count"] for r in ctx.results[first["result_id"]])
    steps = trace.to_list()
    assert steps[1]["tool"] == "rank_rows" and steps[1]["tigergraph"] is False and "query" not in steps[1]
    assert "unknown result_id" in run_tool(mini, "rank_rows", {"result_id": "zz", "field": "x"}, trace, ctx)


def test_event_series_carries_extremes(mini):
    out = json.loads(run_tool(mini, "event_series", {"event_contains": "800 metres"}, TraceRecorder("q")))
    assert "extremes" in out and out["extremes"]["nations"]["max"]


@pytest.mark.parametrize("answer", ["[1, 2]", "not json {", "plain"])
def test_json_string_answers_are_parsed_when_valid(mini, answer):
    rec = answer_question("q", "?", mini, FakeModel([msg(finish(answer=answer))]), CONFIG)
    assert rec.answer == (json.loads(answer) if answer == "[1, 2]" else answer)


def test_compact_drops_fields_that_repeat_another_field():
    from ogr.r2.tools import compact_result

    row = {"event_id": "x", "title": "Sport at the Games - E", "event_name": "E", "games": "2024-Summer",
           "year": 2024, "athlete_id": "a b", "athlete": "A B", "doc_id": "Q1"}
    text, shown = compact_result([row], "r1")
    assert shown[0] == {"event_name": "E", "year": 2024, "athlete": "A B", "doc_id": "Q1"}
    entity = {"title": "Some Film", "doc_id": "Q2"}  # no event_name: the title is the identity
    assert compact_result([entity], "r2")[1][0]["title"] == "Some Film"


def test_truncation_note_points_to_rank_rows_over_all_rows():
    from ogr.r2.tools import compact_result

    text, _ = compact_result([{"n": i, "doc_id": f"D{i}"} for i in range(5)], "r7", max_rows=2)
    assert "rank_rows on r7" in text and "all 5 rows" in text
