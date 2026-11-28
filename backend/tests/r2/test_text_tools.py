"""Tests for prompt-based JSON tool calling (R2_TOOL_MODE=text)."""

from __future__ import annotations

import json
import re

from langchain_core.messages import AIMessage

from ogr.common.config import RunConfig
from ogr.r2.agent import answer_question
from ogr.r2.graph_backend import QueryResult
from ogr.r2.output import validate
from ogr.r2.querylog import QueryLog
from ogr.r2.text_tools import RETRY_MESSAGE, is_text_mode, parse_tool_call, render_tools_prompt
from ogr.r2.tools import TOOL_NAMES

CONFIG = RunConfig(llm_max_retries=2, llm_backoff_base_s=0.0)


def _msg(content, usage=(100, 10)):
    m = AIMessage(content=content)
    if usage:
        m.usage_metadata = {
            "input_tokens": usage[0],
            "output_tokens": usage[1],
            "total_tokens": sum(usage),
        }
    return m


class FakeTextModel:
    """Text-only model with NO bind_tools method (native path raises AttributeError)."""

    def __init__(self, script):
        self.script = list(script)
        self.sent: list[list] = []

    def invoke(self, messages, **_):
        self.sent.append(list(messages))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeNativeModel:
    """Minimal native model to verify default/native mode still calls bind_tools."""

    def __init__(self, script):
        self.script = list(script)
        self.bound_count = 0

    def bind_tools(self, specs, tool_choice=None, **_):
        self.bound_count += 1
        return self

    def invoke(self, messages, **_):
        return self.script.pop(0)


def test_render_tools_prompt_lists_all_tools_and_no_qids():
    prompt = render_tools_prompt()
    for name in [*TOOL_NAMES, "finish"]:
        assert name in prompt
    lower = prompt.lower()
    assert "r2-pub" not in lower and "r2-hid" not in lower
    assert not re.search(r"r2-[a-z]+-\d", lower)


def test_parse_tool_call_variants():
    assert parse_tool_call('{"tool": "find_events", "args": {"year": 2012}}') == (
        "find_events",
        {"year": 2012},
    )
    assert parse_tool_call('```json\n{"tool": "finish", "args": {"status": "answered"}}\n```') == (
        "finish",
        {"status": "answered"},
    )
    assert parse_tool_call('```\n{"tool": "read_document", "args": {"doc_id": "E1"}}\n```') == (
        "read_document",
        {"doc_id": "E1"},
    )
    assert parse_tool_call(
        'Thinking...\n{"tool": "event_series", "args": {"event_contains": "800"}}\nDone.'
    ) == ("event_series", {"event_contains": "800"})
    # Multiple objects: first valid tool object wins
    assert parse_tool_call(
        '{"tool": "first", "args": {"a": 1}} {"tool": "second", "args": {"b": 2}}'
    ) == ("first", {"a": 1})
    # Non-tool JSON skipped in favor of valid tool JSON
    assert parse_tool_call(
        '{"note": "ignore", "x": [1, 2]} then {"tool": "find_events", "args": {}}'
    ) == ("find_events", {})
    # Missing/null args defaults to {}
    assert parse_tool_call('{"tool": "repeat_winners"}') == ("repeat_winners", {})
    # Invalid text returns None
    assert parse_tool_call("not json at all {broken") is None
    assert parse_tool_call('{"tool": "", "args": {}}') is None
    assert parse_tool_call('{"tool": "find_events", "args": [1, 2]}') is None


def test_text_mode_valid_json_trace_tokens_and_citations(mini, monkeypatch, tmp_path):
    monkeypatch.setenv("R2_TOOL_MODE", "text")
    assert is_text_mode() is True
    model = FakeTextModel([
        _msg(json.dumps({"tool": "find_events", "args": {"sport": "Athletics", "event_contains": "800 metres"}})),
        _msg(
            json.dumps({
                "tool": "finish",
                "args": {
                    "status": "answered",
                    "answer": '{"winner": "Ann Alpha"}',
                    "explanation": "found in results",
                    "citations": ["E1", "NOPE", "E1"],
                },
            }),
            usage=(200, 20),
        ),
    ])
    log = QueryLog(tmp_path / "log.jsonl")
    rec = answer_question("q1", "Who won?", mini, model, CONFIG, querylog=log)
    assert rec.status == "answered"
    assert rec.answer == {"winner": "Ann Alpha"}
    assert rec.citations == ["E1"]
    assert (rec.input_tokens, rec.output_tokens) == (300, 30)
    assert [s["tool"] for s in rec.trace] == ["plan", "find_events", "llm_step"]
    assert validate(rec)[0] == []
    assert not (tmp_path / "log.jsonl").exists()


def test_text_mode_fenced_json_with_prose(mini, monkeypatch):
    monkeypatch.setenv("R2_TOOL_MODE", "text")
    model = FakeTextModel([
        _msg('Let me search.\n```json\n{"tool": "find_events", "args": {"sport": "Athletics"}}\n```\nPlease.'),
        _msg(
            'Here is the answer:\n```\n{"tool": "finish", "args": '
            '{"status": "answered", "answer": "Ann Alpha", "explanation": "ok", "citations": ["E1"]}}\n```'
        ),
    ])
    rec = answer_question("q2", "Who won?", mini, model, CONFIG)
    assert rec.status == "answered" and rec.answer == "Ann Alpha" and rec.citations == ["E1"]
    assert [s["tool"] for s in rec.trace] == ["plan", "find_events", "llm_step"]


def test_text_mode_garbage_then_valid_retries_once(mini, monkeypatch):
    monkeypatch.setenv("R2_TOOL_MODE", "text")
    model = FakeTextModel([
        _msg("Sorry, I will search now without JSON.", usage=(10, 5)),
        _msg(json.dumps({"tool": "find_events", "args": {"sport": "Athletics"}}), usage=(20, 6)),
        _msg(
            json.dumps({
                "tool": "finish",
                "args": {"status": "answered", "answer": "ok", "explanation": "done", "citations": ["E1"]},
            }),
            usage=(30, 7),
        ),
    ])
    rec = answer_question("q3", "Who won?", mini, model, CONFIG)
    assert rec.status == "answered" and rec.answer == "ok"
    assert (rec.input_tokens, rec.output_tokens) == (60, 18)
    assert [s["tool"] for s in rec.trace] == ["plan", "llm_step", "find_events", "llm_step"]
    assert any(getattr(m, "content", "") == RETRY_MESSAGE for m in model.sent[1])


def test_text_mode_garbage_twice_triggers_forced_finish_json_and_fallback(mini, monkeypatch):
    monkeypatch.setenv("R2_TOOL_MODE", "text")
    # Case 1: forced finish returns valid JSON finish
    model_json = FakeTextModel([
        _msg("bad 1", usage=(10, 1)),
        _msg("bad 2", usage=(10, 2)),
        _msg(
            json.dumps({
                "tool": "finish",
                "args": {"status": "partial", "answer": "best effort", "explanation": "forced"},
            }),
            usage=(10, 3),
        ),
    ])
    rec1 = answer_question("q4a", "?", mini, model_json, CONFIG)
    assert rec1.status == "partial" and rec1.answer == "best effort"
    assert [s["tool"] for s in rec1.trace] == ["plan", "llm_step", "llm_answer"]
    assert (rec1.input_tokens, rec1.output_tokens) == (30, 6)
    assert any(getattr(m, "content", "") == RETRY_MESSAGE for m in model_json.sent[1])

    # Case 2: forced finish returns plain text fallback
    model_plain = FakeTextModel([
        _msg("bad 1"),
        _msg("bad 2"),
        _msg("Plain text fallback answer."),
    ])
    rec2 = answer_question("q4b", "?", mini, model_plain, CONFIG)
    assert rec2.status == "partial" and rec2.answer == "Plain text fallback answer."
    assert [s["tool"] for s in rec2.trace] == ["plan", "llm_step", "llm_answer"]


def test_text_mode_budget_exhaustion_triggers_forced_finish(mini, monkeypatch):
    monkeypatch.setenv("R2_TOOL_MODE", "text")
    model = FakeTextModel([
        _msg(json.dumps({"tool": "find_events", "args": {"sport": "Athletics"}})),
        _msg(
            json.dumps({
                "tool": "finish",
                "args": {"status": "answered", "answer": "done", "explanation": "at budget", "citations": ["E1"]},
            })
        ),
    ])
    rec = answer_question("q5", "?", mini, model, CONFIG, max_steps=1)
    assert rec.status == "answered" and rec.answer == "done"
    assert [s["tool"] for s in rec.trace] == ["plan", "find_events", "llm_answer"]
    assert "budget" in str(model.sent[-1][-1].content).lower()


def test_text_mode_tigergraph_writes_query_log(monkeypatch, tmp_path):
    monkeypatch.setenv("R2_TOOL_MODE", "text")

    class FakeTG:
        def find_events(self, **kw):
            return QueryResult("r2_find_events", kw, [{"doc_id": "TG1", "title": "T"}], 7.0)

    model = FakeTextModel([
        _msg(json.dumps({"tool": "find_events", "args": {"sport": "Athletics"}})),
        _msg(
            json.dumps({
                "tool": "finish",
                "args": {"status": "answered", "answer": "T", "explanation": "tg", "citations": ["TG1"]},
            })
        ),
    ])
    log = QueryLog(tmp_path / "tg_query_log.jsonl")
    rec = answer_question("q6", "?", FakeTG(), model, CONFIG, querylog=log)
    assert rec.citations == ["TG1"]
    tg_steps = [s for s in rec.trace if s.get("query")]
    assert len(tg_steps) == 1 and tg_steps[0]["tigergraph"] is True
    line = json.loads((tmp_path / "tg_query_log.jsonl").read_text())
    assert line["qid"] == "q6" and line["query"] == "r2_find_events" and line["rows"] == 1


def test_native_mode_still_uses_bind_tools(mini, monkeypatch):
    monkeypatch.delenv("R2_TOOL_MODE", raising=False)
    assert is_text_mode() is False
    finish_call = {
        "name": "finish",
        "id": "f1",
        "type": "tool_call",
        "args": {"status": "answered", "answer": "ok", "explanation": "native"},
    }
    m1 = AIMessage(content="", tool_calls=[finish_call])
    m1.usage_metadata = {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}
    model = FakeNativeModel([m1])
    rec = answer_question("q7", "?", mini, model, CONFIG)
    assert rec.status == "answered" and rec.answer == "ok" and model.bound_count == 1
