import json
from datetime import datetime

from ogr.r2.querylog import QueryLog
from ogr.r2.trace import TraceRecorder


def test_numbering_sums_and_fields(tmp_path):
    seen = []
    log = QueryLog(tmp_path / "q.jsonl", run_id="r1")
    rec = TraceRecorder("q1", log, sink=seen.append)
    rec.llm("plan", 100, 10, 50)
    rec.tg("count_golds", "golds_by_nation", {"sport": "Wrestling"}, 18, 140, note="x")
    rec.local("merge", 3)
    rec.llm("llm_answer", 200, 20, 70)
    steps = rec.to_list()
    assert [s["step"] for s in steps] == [1, 2, 3, 4]
    assert rec.totals() == {"input_tokens": 300, "output_tokens": 30}
    assert steps[0] == {"step": 1, "tool": "plan", "tigergraph": False, "input_tokens": 100,
                        "output_tokens": 10, "ms": 50}
    assert steps[1] == {"step": 2, "tool": "count_golds", "tigergraph": True, "query": "golds_by_nation",
                        "params": {"sport": "Wrestling"}, "rows": 18, "ms": 140, "note": "x"}
    assert steps[2] == {"step": 3, "tool": "merge", "tigergraph": False, "ms": 3}
    assert len(seen) == 4 and seen[1]["step"] == 2  # written as they happen


def test_query_log_lines(tmp_path):
    log = QueryLog(tmp_path / "sub" / "q.jsonl", run_id="r1")
    rec = TraceRecorder("q7", log)
    start = datetime(2026, 1, 2, 3, 4, 5, 678000)
    rec.llm("plan", 1, 1, 1)
    rec.tg("t", "qname", {"a": 1}, 4, 12, started_at=start.astimezone())
    rec.tg("t2", "qname2", {}, 0, 5, ok=False, error="boom")
    lines = [json.loads(x) for x in (tmp_path / "sub" / "q.jsonl").read_text().splitlines()]
    assert len(lines) == 2
    assert lines[0]["qid"] == "q7" and lines[0]["step"] == 2 and lines[0]["rows"] == 4
    assert lines[0]["run_id"] == "r1" and lines[0]["ok"] is True and lines[0]["error"] is None
    assert lines[0]["ts"].endswith("Z") and len(lines[0]["ts"]) == 24
    assert lines[1]["ok"] is False and lines[1]["error"] == "boom"


def test_timer():
    rec = TraceRecorder("q")
    with rec.timer() as t:
        pass
    assert isinstance(t.ms, int) and t.ms >= 0
