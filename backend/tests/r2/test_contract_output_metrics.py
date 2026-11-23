import json

import pytest

from ogr.r2.metrics import Prices, compute_set_metrics, percentile, update_metrics_file
from ogr.r2.output import AnswerRecord, read_answers, validate, write_answers


def rec(qid, status="answered", answer="x", steps=None, latency=None):
    steps = steps or []
    it = sum(s.get("input_tokens", 0) for s in steps)
    ot = sum(s.get("output_tokens", 0) for s in steps)
    lat = latency if latency is not None else sum(s["ms"] for s in steps)
    return AnswerRecord(qid, status, answer, "e", ["Q1"], it, ot, lat, steps)


def llm(n, i, o, ms):
    return {"step": n, "tool": "llm", "tigergraph": False, "input_tokens": i, "output_tokens": o, "ms": ms}


def tg(n, ms):
    return {"step": n, "tool": "t", "tigergraph": True, "query": "q", "params": {}, "rows": 2, "ms": ms}


def fixture():
    return [
        rec("a", steps=[llm(1, 1000, 100, 900), tg(2, 100), llm(3, 2000, 200, 1000)]),  # 2000 ms
        rec("b", "not_in_corpus", None, steps=[llm(1, 500, 50, 400), tg(2, 100)]),  # 500 ms
        rec("c", "partial", {"k": 1}, steps=[llm(1, 300, 30, 100)]),  # 100 ms, no TG
    ]


def test_validation_ok_and_errors():
    errors, warnings = validate(fixture()[0])
    assert errors == [] and warnings == []
    assert validate(fixture()[2])[1]  # no TigerGraph step warns
    bad = fixture()[1]
    bad.answer = "x"
    assert any("null" in e for e in validate(bad)[0])
    bad = fixture()[0]
    bad.input_tokens += 1
    assert any("token totals" in e for e in validate(bad)[0])
    bad = fixture()[0]
    bad.status = "maybe"
    bad.citations = [1]
    errs = validate(bad)[0]
    assert len(errs) == 2
    slow = fixture()[0]
    slow.latency_ms = 100
    assert validate(slow)[1]  # warns, does not fail
    assert validate(slow)[0] == []


def test_roundtrip(tmp_path):
    p = tmp_path / "a.jsonl"
    recs = fixture()
    recs[0].answer = "Áron"
    write_answers(p, recs)
    assert "Áron" in p.read_text(encoding="utf-8")
    assert [r.to_dict() for r in read_answers(p)] == [r.to_dict() for r in recs]


def test_percentile_nearest_rank():
    assert percentile([5, 1, 3, 2, 4], 50) == 3
    assert percentile(list(range(1, 21)), 95) == 19
    assert percentile([], 50) == 0


def test_metrics_numbers():
    m = compute_set_metrics(fixture(), 12.34, Prices(1.0, 2.0), 80.0, "method")
    assert m["questions"] == 3 and m["accuracy_pct"] == 80.0 and m["accuracy_method"] == "method"
    assert m["not_in_corpus_answers"] == 1
    assert m["input_tokens_total"] == 3800 and m["output_tokens_total"] == 380
    assert m["tokens_per_question_avg"] == round(4180 / 3, 1)
    assert m["latency_ms_avg"] == round(2600 / 3, 1)
    assert m["latency_ms_p50"] == 500 and m["latency_ms_p95"] == 2000
    assert m["llm_calls_per_question_avg"] == round(4 / 3, 2)
    assert m["tigergraph_queries_per_question_avg"] == round(2 / 3, 2)
    assert m["trace_steps_per_question_avg"] == round(6 / 3, 2)
    assert m["answers_with_tigergraph_step"] == 2
    assert m["total_run_time_s"] == 12.3
    assert m["cost_usd_total"] == pytest.approx(3800 / 1e6 + 760 / 1e6, abs=1e-4)
    hidden = compute_set_metrics(fixture(), 1, None, None)
    assert hidden["accuracy_pct"] is None and "accuracy_method" not in hidden and hidden["cost_usd_total"] == 0


def test_update_metrics_file_merges(tmp_path):
    p = tmp_path / "metrics.json"
    update_metrics_file(p, "hidden", {"questions": 1})
    update_metrics_file(p, "public", {"questions": 2}, notes=["n"])
    data = json.loads(p.read_text())
    assert list(data) == ["public", "hidden"] and data["hidden"]["questions"] == 1
    assert json.loads((tmp_path / "metrics_notes.json").read_text()) == {"public": ["n"]}
