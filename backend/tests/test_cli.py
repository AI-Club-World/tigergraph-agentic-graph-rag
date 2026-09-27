"""`ogr.cli ask` isolates pipeline failures like the dispatcher does."""

from __future__ import annotations

from ogr import cli
from ogr.common.contracts import PipelineRecord


def test_one_failing_pipeline_does_not_discard_the_others(monkeypatch, capsys):
    def _boom(**_kwargs):
        raise RuntimeError("tigergraph down")

    ok = PipelineRecord(pipeline="graphrag", answer="26", explanation="e")
    monkeypatch.setattr(cli, "run_p1_rag", _boom)
    monkeypatch.setattr("ogr.pipelines.p2_graphrag.run_p2_graphrag", lambda **_kwargs: ok)

    assert cli.main(["ask", "How many?", "--pipelines", "rag,graphrag"]) == 0
    out = capsys.readouterr().out
    assert "Pipeline: rag" in out and "Status: error" in out
    assert "Pipeline: graphrag" in out and "Answer: 26" in out


def test_batch_timing_mode_runs_with_pool_one(monkeypatch, tmp_path):
    from ogr.eval import batch_runner

    seen = {}

    def fake_run_batch_sync(**kwargs):
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(batch_runner, "run_batch_sync", fake_run_batch_sync)
    monkeypatch.setattr(batch_runner, "embedding_backend", lambda _m: "sentence-transformers")
    assert cli.main(["batch", "q.jsonl", "--out", str(tmp_path / "o.jsonl"), "--mode", "timing"]) == 0
    assert seen["pool_size"] == 1
    assert seen["run_config"]["latency_mode"] == "timing"
    assert seen["max_total_tokens"] > 0


def test_build_refuses_without_tigergraph(monkeypatch, capsys):
    monkeypatch.setattr(cli.TigerGraphClient, "_ensure_connection", lambda self: None)
    assert cli.main(["build"]) == 1
    assert "TigerGraph unreachable" in capsys.readouterr().err
