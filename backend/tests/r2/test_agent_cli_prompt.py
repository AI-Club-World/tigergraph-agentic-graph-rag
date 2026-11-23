"""r2-run (local backend, injected model), resume, and prompt/tool-description hygiene."""

from __future__ import annotations

import json
import re
from pathlib import Path

from langchain_core.messages import AIMessage

from ogr.cli import main
from ogr.r2 import run as r2_run
from ogr.r2.agent import PROMPT_VERSION, SYSTEM_PROMPT
from ogr.r2.output import read_answers, validate
from ogr.r2.tools import FINISH_SPEC, TOOL_SPECS
from tests.r2.conftest import MINI

PUBLIC = Path(__file__).resolve().parents[3] / "docs" / "round-2" / "data" / "questions_public.jsonl"


class AlwaysFinish:
    """Searches once, then finishes; stateless per call so every question gets the same script."""

    def bind_tools(self, specs, tool_choice=None, **_):
        return self

    def invoke(self, messages, **_):
        done = any(m.type == "tool" for m in messages) or (
            messages and getattr(messages[-1], "content", "").startswith("The tool budget"))
        if done:
            call = {"name": "finish", "id": "f", "type": "tool_call", "args": {
                "status": "answered", "answer": "Ann Alpha", "explanation": "from results",
                "citations": ["E1", "ghost"]}}
        else:
            call = {"name": "find_events", "id": "t", "type": "tool_call",
                    "args": {"sport": "Athletics", "year": 2012}}
        m = AIMessage(content="", tool_calls=[call])
        m.usage_metadata = {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}
        return m


def _setup(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text("\n".join(json.dumps(r) for r in MINI) + "\n")
    questions = tmp_path / "q.jsonl"
    questions.write_text("\n".join(json.dumps({"qid": f"q{i}", "question": f"Question {i}?"})
                                   for i in range(1, 4)) + "\n")
    monkeypatch.setattr(r2_run, "make_model", lambda config: AlwaysFinish())
    monkeypatch.setenv("R2_QUERY_LOG", str(tmp_path / "tg.jsonl"))
    return corpus, questions


def test_r2_run_local_backend_resume_and_validation(tmp_path, monkeypatch, capsys):
    corpus, questions = _setup(tmp_path, monkeypatch)
    out = tmp_path / "answers.jsonl"
    base = ["r2-run", "--questions", str(questions), "--out", str(out), "--backend", "local",
            "--corpus", str(corpus)]
    assert main([*base, "--limit", "2"]) == 0
    first = capsys.readouterr()
    assert "LOCAL BACKEND" in first.err and "2 answered" in first.out
    assert [r.qid for r in read_answers(out)] == ["q1", "q2"]
    # resume: q1 and q2 are skipped, q3 is added; nothing is rewritten
    before = out.read_text().splitlines()
    assert main(base) == 0
    assert "1 answered, 2 skipped" in capsys.readouterr().out
    after = out.read_text().splitlines()
    assert after[:2] == before and len(after) == 3
    for rec in read_answers(out):
        assert validate(rec)[0] == [] and rec.citations == ["E1"]
        assert (rec.input_tokens, rec.output_tokens) == (20, 4)
        assert not any(s["tigergraph"] for s in rec.trace)  # a local run can never pass as TigerGraph
    assert not (tmp_path / "tg.jsonl").exists()


def test_r2_run_qids_filter_and_workers(tmp_path, monkeypatch, capsys):
    corpus, questions = _setup(tmp_path, monkeypatch)
    out = tmp_path / "a.jsonl"
    assert main(["r2-run", "--questions", str(questions), "--out", str(out), "--backend", "local",
                 "--corpus", str(corpus), "--qids", "q3,q1", "--workers", "2"]) == 0
    assert sorted(r.qid for r in read_answers(out)) == ["q1", "q3"]


def test_run_questions_survives_a_failing_question(tmp_path, mini):
    class Flaky(AlwaysFinish):
        def invoke(self, messages, **kw):
            if "boom" in str(messages[1].content):
                raise RuntimeError("provider exploded")
            return super().invoke(messages, **kw)

    out = tmp_path / "a.jsonl"
    qs = [{"qid": "a", "question": "boom"}, {"qid": "b", "question": "fine"}]
    from ogr.common.config import RunConfig
    s = r2_run.run_questions(qs, out, mini, Flaky(), RunConfig(llm_max_retries=0))
    recs = {r.qid: r for r in read_answers(out)}
    # The failed question is not written (no crash is submitted as an answer)...
    assert set(recs) == {"b"} and recs["b"].status == "answered"
    assert s["statuses"] == {"answered": 1} and s["failed"][0].startswith("a: RuntimeError")
    # ...and a re-run retries only it.
    s2 = r2_run.run_questions(qs, out, mini, AlwaysFinish(), RunConfig(llm_max_retries=0))
    assert s2["skipped"] == 1 and s2["answered_now"] == 1
    assert {r.qid for r in read_answers(out)} == {"a", "b"}


# --- hygiene: no question-specific content in the prompt or tool descriptions ---------

STOP_PHRASES = {"according to the corpus", "in the corpus", "of the corpus", "at the same",
                "the corpus does not", "what is the", "which of the"}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def _fourgrams(text: str) -> set[str]:
    w = _words(text)
    return {" ".join(w[i:i + 4]) for i in range(len(w) - 3)}


def _agent_text() -> str:
    parts = [SYSTEM_PROMPT, PROMPT_VERSION]
    for spec in [*TOOL_SPECS, {"function": FINISH_SPEC}]:
        fn = spec["function"]
        parts += [fn["name"], fn["description"], json.dumps(fn["parameters"])]
    return "\n".join(parts)


def test_prompt_and_tool_text_have_no_qids():
    text = _agent_text().lower()
    assert "r2-pub" not in text and "r2-hid" not in text and not re.search(r"r2-[a-z]+-\d", text)


def test_prompt_and_tool_text_do_not_copy_public_questions():
    if not PUBLIC.exists():
        return
    ours = _fourgrams(_agent_text())
    shared: dict[str, str] = {}
    for line in PUBLIC.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        q = json.loads(line)
        for gram in _fourgrams(q["question"]) & ours:
            if not any(p in gram or gram in p for p in STOP_PHRASES):
                shared[gram] = q["qid"]
    assert not shared, f"4-word sequences copied from public questions: {sorted(shared)}"
