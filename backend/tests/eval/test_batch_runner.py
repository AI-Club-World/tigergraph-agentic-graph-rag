"""Tests for EVAL-04's batch runner: the piece that turns the already-tested
dispatcher/aggregator/scorer into actual per-question, per-pipeline records
over a JSONL question set.

No live LLM or TigerGraph is used anywhere here — pipelines are stub
callables, same pattern as test_dispatcher.py.
"""

from __future__ import annotations

import json

from ogr.common.contracts import Citation, PipelineRecord, TokenUsage
import pytest

from ogr.eval import store as store_module
from ogr.eval.batch_runner import BatchIncompleteError, load_questions, run_batch_sync
from ogr.eval.store import read_written_qids


def _record(pipeline: str, answer: str, total: int = 100) -> PipelineRecord:
    return PipelineRecord(
        pipeline=pipeline,  # type: ignore[arg-type]
        answer=answer,
        explanation="e",
        citations=[Citation(source_id="Q1", chunk_id=None, ref_type="entity")],
        chunks_returned=1,
        citations_count=1,
        tokens=TokenUsage(input=total - 10, output=10, total=total),
    )


def _stub_pipelines(rag_answer="5", graphrag_answer="5", agentic_answer="5"):
    return {
        "rag": lambda _q: _record("rag", rag_answer, total=100),
        "graphrag": lambda _q: _record("graphrag", graphrag_answer, total=200),
        "agentic_graphrag": lambda _q: _record("agentic_graphrag", agentic_answer, total=400),
    }


def _write_questions(path, questions: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for q in questions:
            handle.write(json.dumps(q) + "\n")


class TestLoadQuestions:
    def test_parses_every_line_into_a_question(self, tmp_path):
        path = tmp_path / "q.jsonl"
        _write_questions(path, [
            {"qid": "pub-001", "question": "How many?", "qtype": "aggregation", "answer": ["5"]},
            {"qid": "pub-002", "question": "Who won?", "qtype": "lookup", "answer": []},
        ])
        questions = load_questions(path)
        assert [q.qid for q in questions] == ["pub-001", "pub-002"]

    def test_skips_blank_lines(self, tmp_path):
        path = tmp_path / "q.jsonl"
        path.write_text(
            json.dumps({"qid": "pub-001", "question": "Q?"}) + "\n\n\n",
            encoding="utf-8",
        )
        assert len(load_questions(path)) == 1


class TestRunBatch:
    def test_writes_one_batch_record_per_question(self, tmp_path):
        questions_path = tmp_path / "q.jsonl"
        _write_questions(questions_path, [
            {"qid": "pub-001", "question": "How many?", "qtype": "aggregation", "answer": ["5"]},
            {"qid": "pub-002", "question": "Who won?", "qtype": "lookup", "answer": ["Bob"]},
        ])
        out_path = tmp_path / "run.jsonl"

        count = run_batch_sync(
            questions_path, out_path, _stub_pipelines(),
            run_id="test-run", run_config={"llm_model": "gpt-4o-mini"},
        )

        assert count == 2
        lines = out_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3  # header + 2 records
        header = json.loads(lines[0])
        assert header["run_config"]["llm_model"] == "gpt-4o-mini"
        records = [json.loads(line) for line in lines[1:]]
        assert {r["question_id"] for r in records} == {"pub-001", "pub-002"}
        # accuracy delta actually reaches the persisted record (EM: agentic
        # answered "5", matching gold "5" -> delta computed, not "n/a")
        pub_001 = next(r for r in records if r["question_id"] == "pub-001")
        assert pub_001["record"]["verdict"]["accuracy_delta_vs_rag"] != "n/a"

    def test_resume_skips_questions_already_in_the_output_file(self, tmp_path):
        questions_path = tmp_path / "q.jsonl"
        _write_questions(questions_path, [
            {"qid": "pub-001", "question": "Q1", "answer": ["5"]},
            {"qid": "pub-002", "question": "Q2", "answer": ["6"]},
        ])
        out_path = tmp_path / "run.jsonl"

        first = run_batch_sync(questions_path, out_path, _stub_pipelines(), "run-a", {})
        assert first == 2
        assert read_written_qids(out_path) == {"pub-001", "pub-002"}

        # A second invocation over the same questions must not re-run anything.
        second = run_batch_sync(questions_path, out_path, _stub_pipelines(), "run-a", {})
        assert second == 0
        lines = out_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3  # header + 2, unchanged

    def test_a_fresh_run_with_no_pending_questions_is_a_no_op(self, tmp_path):
        questions_path = tmp_path / "q.jsonl"
        _write_questions(questions_path, [])
        out_path = tmp_path / "run.jsonl"
        assert run_batch_sync(questions_path, out_path, _stub_pipelines(), "run-a", {}) == 0
        assert not out_path.exists()

    def test_one_pipeline_failure_does_not_drop_the_question(self, tmp_path):
        """NFR-2 must hold through the batch runner too, not just the dispatcher."""
        questions_path = tmp_path / "q.jsonl"
        _write_questions(questions_path, [{"qid": "pub-001", "question": "Q1", "answer": ["5"]}])
        out_path = tmp_path / "run.jsonl"

        def _boom(_q):
            raise RuntimeError("boom")

        pipelines = _stub_pipelines()
        pipelines["graphrag"] = _boom

        count = run_batch_sync(questions_path, out_path, pipelines, "run-a", {})
        assert count == 1
        record = json.loads(out_path.read_text(encoding="utf-8").splitlines()[1])
        assert record["record"]["pipelines"]["graphrag"]["status"] == "error"
        assert record["record"]["pipelines"]["rag"]["status"] == "done"


class TestPostDispatchFailureIsolation:
    """A failure after dispatch (record construction, the store's secret
    check) must not cancel the other in-flight questions, and must not be
    silent either."""

    def test_one_unrecordable_question_does_not_abort_the_run(self, tmp_path, monkeypatch):
        questions_path = tmp_path / "q.jsonl"
        _write_questions(questions_path, [
            {"qid": f"pub-00{i}", "question": f"Q{i}", "answer": ["5"]} for i in range(1, 5)
        ])
        out_path = tmp_path / "run.jsonl"

        real_append = store_module.BatchStore.append

        def _append(self, record):
            if record["question_id"] == "pub-002":
                raise store_module.SecretLeakError("simulated")
            real_append(self, record)

        monkeypatch.setattr(store_module.BatchStore, "append", _append)
        with pytest.raises(BatchIncompleteError, match="pub-002"):
            run_batch_sync(questions_path, out_path, _stub_pipelines(), "run-a", {}, pool_size=2)
        assert read_written_qids(out_path) == {"pub-001", "pub-003", "pub-004"}

        # Resume retries only the unrecorded question.
        monkeypatch.setattr(store_module.BatchStore, "append", real_append)
        assert run_batch_sync(questions_path, out_path, _stub_pipelines(), "run-a", {}) == 1
        assert read_written_qids(out_path) == {"pub-001", "pub-002", "pub-003", "pub-004"}


class TestRunLevelControls:
    def test_token_ceiling_stops_starting_questions_and_holds_across_resume(self, tmp_path):
        from ogr.eval.batch_runner import BatchIncompleteError

        questions_path = tmp_path / "q.jsonl"
        _write_questions(questions_path, [
            {"qid": f"pub-00{i}", "question": f"Q{i}", "answer": ["5"]} for i in range(1, 6)
        ])
        out_path = tmp_path / "run.jsonl"
        # Each question costs 100 + 200 + 400 = 700 tokens; serial pool.
        with pytest.raises(BatchIncompleteError, match="token ceiling"):
            run_batch_sync(questions_path, out_path, _stub_pipelines(), "run-a", {}, pool_size=1, max_total_tokens=1400)
        assert len(read_written_qids(out_path)) == 2
        # Resume under the same ceiling starts nothing: the file already spent it.
        with pytest.raises(BatchIncompleteError, match="5 pending|3 pending"):
            run_batch_sync(questions_path, out_path, _stub_pipelines(), "run-a", {}, pool_size=1, max_total_tokens=1400)
        assert len(read_written_qids(out_path)) == 2
        # Raising the ceiling finishes the run.
        assert run_batch_sync(questions_path, out_path, _stub_pipelines(), "run-a", {}, pool_size=1) == 3

    def test_timing_mode_runs_one_question_at_a_time(self):
        from ogr.common.config import RunConfig
        from ogr.eval.batch_runner import effective_pool_size, run_config_header

        assert effective_pool_size(RunConfig(pool_size=4, latency_mode="timing")) == 1
        assert effective_pool_size(RunConfig(pool_size=4, latency_mode="throughput")) == 4
        with pytest.raises(ValueError):
            effective_pool_size(RunConfig(latency_mode="fast"))

    def test_header_records_mode_seed_and_ceiling(self, monkeypatch):
        from ogr.common.config import RunConfig
        from ogr.eval import batch_runner

        monkeypatch.setattr(batch_runner, "embedding_backend", lambda _m: "sentence-transformers")
        header = batch_runner.run_config_header(
            RunConfig(latency_mode="timing", seed=7, max_total_tokens=99, pool_size=4)
        )
        assert header["latency_mode"] == "timing"
        assert header["pool_size"] == 1
        assert header["seed"] == 7
        assert header["max_total_tokens"] == 99
