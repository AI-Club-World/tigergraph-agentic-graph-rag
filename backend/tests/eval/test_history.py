"""Tests for eval/history.py — benchmark history over the JSONL run store."""

from __future__ import annotations

import json

import pytest

from ogr.eval.history import import_run, list_runs, read_run, summarize_run, view_record
from ogr.eval.store import SecretLeakError


def _pipeline(name: str, answer: str, tokens: int, status: str = "done") -> dict:
    return {
        "pipeline": name,
        "answer": answer,
        "citations": [{"source_id": "Q1", "chunk_id": None, "ref_type": "entity"}],
        "tokens": {"input": tokens - 10, "output": 10, "total": tokens},
        "latency_ms": 1000,
        "status": status,
    }


def _record(qid: str, gold: list[str], rag: str, agentic: str, timestamp: str = "") -> dict:
    return {
        "run_id": "r",
        "question_id": qid,
        "question_text": f"question {qid}",
        "qtype": "aggregation",
        "ground_truth": gold,
        "gold_doc_ids": ["Q1"],
        "record": {
            "timestamp": timestamp,
            "pipelines": {
                "rag": _pipeline("rag", rag, 1000),
                "agentic_graphrag": _pipeline("agentic_graphrag", agentic, 4000),
            },
        },
    }


def _write_run(path, run_config: dict, records: list[dict]) -> None:
    lines = [json.dumps({"run_config": run_config})] + [json.dumps(r) for r in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestViewRecord:
    def test_adds_dashboard_field_names_and_backend_scores(self):
        view = view_record(_record("pub-1", ["26"], rag="12", agentic="26"))
        assert view["qid"] == "pub-1"
        assert view["question"] == "question pub-1"
        assert view["scores"]["agentic_graphrag"]["em"] == 1.0
        assert view["scores"]["rag"]["em"] == 0.0
        assert view["scores"]["rag"]["recall"] == 1.0

    def test_no_ground_truth_means_null_scores(self):
        assert view_record(_record("h-1", [], rag="x", agentic="y"))["scores"] is None

    def test_existing_scores_are_kept_not_recomputed(self):
        record = {**_record("pub-1", ["26"], rag="12", agentic="26"), "scores": {"rag": {"em": 0.5}}}
        assert view_record(record)["scores"] == {"rag": {"em": 0.5}}


class TestSummarizeRun:
    def test_per_pipeline_accuracy_cost_and_efficiency(self):
        records = [
            _record("pub-1", ["26"], rag="12", agentic="26"),
            _record("pub-2", ["5"], rag="5", agentic="5"),
        ]
        summary = summarize_run("r1", {"llm_model": "m", "dataset": "eval_public"}, records)

        assert summary["n_questions"] == 2
        assert summary["scored"] is True
        assert summary["dataset"] == "eval_public"
        assert list(summary["pipelines"]) == ["rag", "agentic_graphrag"]
        agentic, rag = summary["pipelines"]["agentic_graphrag"], summary["pipelines"]["rag"]
        assert agentic["em"] == 1.0 and rag["em"] == 0.5
        assert agentic["median_tokens"] == 4000 and agentic["total_tokens"] == 8000
        # 1.0 F1 over 4k mean tokens -> 0.25 F1 per 1k tokens.
        assert agentic["f1_per_1k_tokens"] == pytest.approx(0.25)
        assert rag["f1_per_1k_tokens"] == pytest.approx(0.5)

    def test_unscored_run_keeps_cost_metrics_and_nulls_accuracy(self):
        summary = summarize_run("h", {}, [_record("h-1", [], rag="x", agentic="y")])
        rag = summary["pipelines"]["rag"]
        assert summary["scored"] is False
        assert rag["em"] is None and rag["f1_per_1k_tokens"] is None
        assert rag["mean_tokens"] == 1000

    def test_errors_are_counted(self):
        record = _record("pub-1", ["26"], rag="", agentic="26")
        record["record"]["pipelines"]["rag"]["status"] = "error"
        assert summarize_run("r", {}, [record])["pipelines"]["rag"]["errors"] == 1

    def test_started_at_falls_back_to_earliest_record_timestamp(self):
        records = [
            _record("a", ["1"], "1", "1", timestamp="2026-09-22T10:00:00Z"),
            _record("b", ["1"], "1", "1", timestamp="2026-09-22T09:00:00Z"),
        ]
        assert summarize_run("r", {}, records)["started_at"] == "2026-09-22T09:00:00Z"


class TestListRuns:
    def test_lists_runs_newest_first_and_skips_non_run_files(self, tmp_path):
        _write_run(tmp_path / "old.jsonl", {"started_at": "2026-09-01T00:00:00Z"}, [_record("a", ["1"], "1", "1")])
        _write_run(tmp_path / "new.jsonl", {"started_at": "2026-09-20T00:00:00Z"}, [_record("a", ["1"], "1", "1")])
        (tmp_path / "chunks.jsonl").write_text(json.dumps({"chunk_id": "c1"}) + "\n")

        runs = list_runs(tmp_path, {"new": "running"})
        assert [r["run_id"] for r in runs] == ["new", "old"]
        assert [r["status"] for r in runs] == ["running", "complete"]

    def test_half_written_last_line_of_a_running_run_is_skipped(self, tmp_path):
        path = tmp_path / "live.jsonl"
        _write_run(path, {}, [_record("a", ["1"], "1", "1")])
        with path.open("a", encoding="utf-8") as handle:
            handle.write('{"run_id": "live", "question_id": "b", "rec')
        assert list_runs(tmp_path)[0]["n_questions"] == 1

    def test_missing_directory_is_empty_history(self, tmp_path):
        assert list_runs(tmp_path / "absent") == []


class TestImportRun:
    def test_round_trips_the_export_shape(self, tmp_path):
        payload = {
            "run_id": "past-1",
            "run_config": {"llm_model": "m"},
            "records": [_record("pub-1", ["26"], "12", "26")],
        }
        assert import_run(tmp_path, payload) == "past-1"
        run_config, records = read_run(tmp_path / "past-1.jsonl")
        assert run_config["llm_model"] == "m" and "imported_at" in run_config
        assert records[0]["run_id"] == "past-1"

    def test_bare_record_list_takes_the_records_run_id(self, tmp_path):
        assert import_run(tmp_path, [_record("pub-1", ["26"], "12", "26")]) == "r"

    def test_refuses_to_overwrite_history(self, tmp_path):
        payload = {"run_id": "dup", "records": [_record("a", ["1"], "1", "1")]}
        import_run(tmp_path, payload)
        with pytest.raises(FileExistsError):
            import_run(tmp_path, payload)

    @pytest.mark.parametrize(
        "payload",
        [
            "not json object",
            {"records": []},
            {"records": [{"no": "record"}]},
            {"run_id": "../escape", "records": [{"record": {"pipelines": {}}}]},
        ],
    )
    def test_rejects_malformed_payloads_and_unsafe_ids(self, tmp_path, payload):
        with pytest.raises(ValueError):
            import_run(tmp_path, payload)
        assert list(tmp_path.iterdir()) == []

    def test_secret_in_payload_leaves_no_partial_file(self, tmp_path):
        payload = {"run_id": "leak", "run_config": {"key": "sk-" + "a" * 20}, "records": [_record("a", ["1"], "1", "1")]}
        with pytest.raises(SecretLeakError):
            import_run(tmp_path, payload)
        assert not (tmp_path / "leak.jsonl").exists()
