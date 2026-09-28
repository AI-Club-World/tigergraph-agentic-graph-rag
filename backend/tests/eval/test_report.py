"""Tests for eval/report.py — the run report and the hidden-set export."""

from __future__ import annotations

import json

from ogr.cli import main
from ogr.eval.report import build_report, export_run


def _pipeline(name: str, answer: str, tokens: int, **extra) -> dict:
    return {
        "pipeline": name,
        "answer": answer,
        "explanation": "because",
        "citations": [{"source_id": "Q1", "chunk_id": "c1", "ref_type": "chunk", "snippet": answer}],
        "tokens": {"input": tokens - 10, "output": 10, "total": tokens},
        "token_source": "provider",
        "latency_ms": 2000,
        "chunks_returned": 3,
        "status": "done",
        **extra,
    }


def _step(agent: str, tool: str) -> dict:
    return {"agent_type": agent, "tool_called": tool, "tokens": {"total": 100}, "latency_ms": 50}


def _record(qid: str, qtype: str, gold: list[str], rag: str, agentic: str, stop: str) -> dict:
    trace = [] if stop == "direct_route" else [_step("graph_traversal", "q4_traverse")]
    return {
        "run_id": "r",
        "question_id": qid,
        "question_text": f"question {qid}",
        "qtype": qtype,
        "ground_truth": gold,
        "gold_doc_ids": ["Q1"],
        "record": {
            "pipelines": {
                "rag": _pipeline("rag", rag, 1000),
                "graphrag": _pipeline("graphrag", rag, 1500),
                "agentic_graphrag": _pipeline(
                    "agentic_graphrag", agentic, 1200 if stop == "direct_route" else 4000,
                    trace=trace, strategy_changed=stop != "direct_route", stop_reason=stop,
                ),
            },
        },
    }


def _run(tmp_path):
    path = tmp_path / "run1.jsonl"
    config = {"llm_provider": "nvidia", "llm_model": "m", "embedding_model": "bge-large-en-v1.5"}
    records = [
        _record("pub-1", "lookup", ["Paris"], "Paris", "Paris", "direct_route"),
        _record("pub-2", "multi_hop", ["26"], "12", "26", "evidence_sufficient"),
        _record("h-1", "temporal", [], "x", "y", "evidence_sufficient"),
    ]
    lines = [json.dumps({"run_config": config})] + [json.dumps(r) for r in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_report_has_every_section_and_the_per_type_verdicts(tmp_path):
    text = build_report(_run(tmp_path))
    for heading in ("## Headline", "## Where the agent pays for itself", "## Necessity routing",
                    "## Agents and tools"):
        assert heading in text
    assert "`nvidia/m`" in text
    assert "| lookup | 1 | 1.00 | 1.00 | 1.00 | 0.00 | 1.20× | Overkill |" in text
    assert "| multi_hop | 1 | 0.00 | 0.00 | 1.00 | 1.00 | 4.00× | Worth it |" in text
    assert "Agentic right where RAG was wrong: **1** (pub-2)" in text
    # One direct route at 1,200 vs a loop median of 4,000 tokens.
    assert "| direct | 1 | 1,200 |" in text
    assert "about **2,800** more tokens" in text
    assert "`q4_traverse` ×2" in text


def test_export_carries_answers_tokens_citations_and_the_agentic_trace(tmp_path):
    data = export_run(_run(tmp_path))
    assert data["run_id"] == "run1"
    assert [q["qid"] for q in data["questions"]] == ["pub-1", "pub-2", "h-1"]
    q = data["questions"][1]["pipelines"]
    assert set(q) == {"rag", "graphrag", "agentic_graphrag"}
    assert q["rag"]["tokens"]["total"] == 1000
    assert q["rag"]["citations"][0]["snippet"] == "12"
    assert "trace" not in q["rag"]
    assert q["agentic_graphrag"]["trace"][0]["tool_called"] == "q4_traverse"
    assert q["agentic_graphrag"]["stop_reason"] == "evidence_sufficient"


def test_cli_report_and_export(tmp_path, capsys):
    run = _run(tmp_path)
    assert main(["report", str(run)]) == 0
    assert "## Headline" in capsys.readouterr().out
    out = tmp_path / "sub" / "export.json"
    assert main(["export", str(run), "--out", str(out)]) == 0
    assert len(json.loads(out.read_text())["questions"]) == 3


def test_token_ratio_is_the_mean_of_per_question_ratios_like_the_dashboard(tmp_path):
    """UI-SPEC: a mean of ratios, not a median (ratios 1, 2 and 6 give 3.00, not 2.00)."""
    path = tmp_path / "ratios.jsonl"
    records = [_record(f"q{i}", "lookup", ["Paris"], "Paris", "Paris", "direct_route") for i in range(3)]
    for record, agentic in zip(records, (1000, 2000, 6000), strict=True):
        record["record"]["pipelines"]["agentic_graphrag"]["tokens"]["total"] = agentic
    lines = [json.dumps({"run_config": {}})] + [json.dumps(r) for r in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert "| lookup | 3 | 1.00 | 1.00 | 1.00 | 0.00 | 3.00× | Overkill |" in build_report(path)
