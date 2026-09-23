"""`ogr.cli ask` isolates pipeline failures like the dispatcher does (AUDIT-03)."""

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
