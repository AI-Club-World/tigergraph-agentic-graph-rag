"""`ogr.cli ask` isolates pipeline failures like the dispatcher does."""

from __future__ import annotations

import pytest

from ogr import cli
from ogr.common.contracts import PipelineRecord
from tests.conftest import make_embeddings_ready


@pytest.fixture(autouse=True)
def cli_out(monkeypatch, tmp_path):
    """CLI state (embedding store, registry) in a temporary out/, with the
    default model's embeddings complete so queries and runs may start."""
    out = tmp_path / "cli-out"
    monkeypatch.setattr(cli, "OUT_DIR", out)
    return make_embeddings_ready(out)


def test_a_model_without_complete_embeddings_is_refused(capsys):
    assert cli.main(["ask", "How many?", "--embedding-model", "qwen3-embedding-0.6b"]) == 1
    err = capsys.readouterr().err
    assert "no complete embeddings" in err and "bge-large-en-v1.5" in err
    assert cli.main(["batch", "q.jsonl", "--out", "o.jsonl", "--embedding-model", "gte-large-en-v1.5"]) == 1


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


def test_batch_run_shows_in_the_app_history(monkeypatch, capsys):
    from ogr.common.trials import TrialLog
    from ogr.eval import batch_runner

    monkeypatch.setattr(batch_runner, "run_batch_sync", lambda **_kwargs: 3)
    monkeypatch.setattr(batch_runner, "embedding_backend", lambda _m: "sentence-transformers")
    out = cli.OUT_DIR / "r1.jsonl"
    assert cli.main(["batch", "data/questions/eval_public.jsonl", "--out", str(out), "--run-id", "r1"]) == 0
    assert "will not show there" not in capsys.readouterr().err
    [trial] = TrialLog(cli.OUT_DIR / "history.jsonl").read()
    assert trial["kind"] == "benchmark" and trial["status"] == "complete"
    assert trial["run_id"] == "r1" and trial["dataset"] == "eval_public" and trial["questions"] == 3


def test_failed_batch_is_logged_and_a_hidden_out_path_is_named(monkeypatch, tmp_path, capsys):
    from ogr.common.trials import TrialLog
    from ogr.eval import batch_runner

    def incomplete(**_kwargs):
        raise batch_runner.BatchIncompleteError("pub-7 not recorded")

    monkeypatch.setattr(batch_runner, "run_batch_sync", incomplete)
    monkeypatch.setattr(batch_runner, "embedding_backend", lambda _m: "sentence-transformers")
    assert cli.main(["batch", "q.jsonl", "--out", str(tmp_path / "elsewhere.jsonl"), "--run-id", "r2"]) == 1
    assert "will not show there" in capsys.readouterr().err
    [trial] = TrialLog(cli.OUT_DIR / "history.jsonl").read()
    assert trial["status"] == "error" and "pub-7" in trial["error"]


def test_build_refuses_without_tigergraph(monkeypatch, capsys):
    monkeypatch.setattr(cli.TigerGraphClient, "_ensure_connection", lambda self: None)
    assert cli.main(["build"]) == 1
    assert "TigerGraph unreachable" in capsys.readouterr().err
