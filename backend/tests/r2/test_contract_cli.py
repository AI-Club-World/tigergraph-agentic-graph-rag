import json

from ogr.cli import main


def test_r2_score_and_metrics_smoke(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("R2_LLM_INPUT_USD_PER_M", raising=False)
    monkeypatch.delenv("R2_LLM_OUTPUT_USD_PER_M", raising=False)
    q = tmp_path / "questions_public.jsonl"
    q.write_text("\n".join(json.dumps(x) for x in [
        {"qid": "a", "question": "?", "status": "answered", "answer": "Amistad", "gold_doc_ids": []},
        {"qid": "b", "question": "?", "status": "not_in_corpus", "answer": None, "gold_doc_ids": []},
    ]) + "\n")
    trace = [{"step": 1, "tool": "plan", "tigergraph": False, "input_tokens": 10, "output_tokens": 5, "ms": 80},
             {"step": 2, "tool": "t", "tigergraph": True, "query": "q", "params": {}, "rows": 1, "ms": 20}]
    base = {"explanation": "", "citations": [], "input_tokens": 10, "output_tokens": 5, "latency_ms": 100,
            "trace": trace}
    a = tmp_path / "answers_public.jsonl"
    a.write_text("\n".join(json.dumps(x) for x in [
        {"qid": "a", "status": "answered", "answer": "It is Amistad", **base},
        {"qid": "b", "status": "answered", "answer": "invented", **base},
    ]) + "\n")
    scores = tmp_path / "score.json"
    assert main(["r2-score", "--questions", str(q), "--answers", str(a), "--out", str(scores)]) == 0
    assert json.loads(scores.read_text())["accuracy_pct"] == 50.0
    out = tmp_path / "out" / "metrics.json"
    assert main(["r2-metrics", "--set", "public", "--answers", str(a), "--questions", str(q),
                 "--run-time-s", "3.5", "--out", str(out)]) == 0
    assert main(["r2-metrics", "--set", "hidden", "--answers", str(a), "--out", str(out)]) == 0
    data = json.loads(out.read_text())
    assert data["public"]["accuracy_pct"] == 50.0 and data["public"]["total_run_time_s"] == 3.5
    assert data["public"]["questions"] == 2 and data["public"]["answers_with_tigergraph_step"] == 2
    assert data["hidden"]["accuracy_pct"] is None and data["hidden"]["total_run_time_s"] == 0.2
    assert (tmp_path / "out" / "metrics_notes.json").exists()


def test_r2_score_can_score_one_part_of_the_split(tmp_path):
    import json

    from ogr.cli import main

    qs = tmp_path / "q.jsonl"
    qs.write_text("\n".join(json.dumps({"qid": q, "question": "x", "status": "answered", "answer": "Paris",
                                        "gold_doc_ids": [], "note": ""}) for q in ("a", "b")), encoding="utf-8")
    ans = tmp_path / "a.jsonl"
    ans.write_text("\n".join(json.dumps({"qid": q, "status": "answered", "answer": a, "explanation": "",
                                         "citations": [], "input_tokens": 0, "output_tokens": 0,
                                         "latency_ms": 0, "trace": []}) for q, a in (("a", "Paris"), ("b", "Rome"))),
                   encoding="utf-8")
    split = tmp_path / "split.json"
    split.write_text(json.dumps({"a": "dev", "b": "check"}), encoding="utf-8")
    out = tmp_path / "s.json"
    assert main(["r2-score", "--questions", str(qs), "--answers", str(ans), "--split", "check",
                 "--split-file", str(split), "--out", str(out)]) == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    assert len(result["per_question"]) == 1 and result["accuracy_pct"] == 0.0
