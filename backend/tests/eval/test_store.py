"""Tests for EVAL-04's BatchStore (append-only JSONL + secret guard)."""

from __future__ import annotations

import json

import pytest

from ogr.eval.store import BatchStore, SecretLeakError, read_written_qids


class TestBatchStore:
    def test_first_write_creates_a_run_config_header_line(self, tmp_path):
        path = tmp_path / "run.jsonl"
        BatchStore(path, {"llm_model": "gpt-4o-mini"})
        lines = path.read_text(encoding="utf-8").splitlines()
        assert json.loads(lines[0]) == {"run_config": {"llm_model": "gpt-4o-mini"}}

    def test_reopening_an_existing_file_does_not_rewrite_the_header(self, tmp_path):
        path = tmp_path / "run.jsonl"
        BatchStore(path, {"llm_model": "gpt-4o-mini"}).append({"question_id": "pub-001"})
        BatchStore(path, {"llm_model": "should-not-appear"})
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["run_config"]["llm_model"] == "gpt-4o-mini"

    def test_append_adds_one_line_per_record(self, tmp_path):
        path = tmp_path / "run.jsonl"
        store = BatchStore(path, {})
        store.append({"question_id": "pub-001"})
        store.append({"question_id": "pub-002"})
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3  # header + 2 records

    def test_refuses_to_persist_a_record_shaped_like_an_api_key(self, tmp_path):
        path = tmp_path / "run.jsonl"
        store = BatchStore(path, {})
        with pytest.raises(SecretLeakError):
            store.append({"note": "sk-abcdefghijklmnopqrstuvwxyz0123456789"})

    def test_refuses_a_run_config_header_shaped_like_an_api_key(self, tmp_path):
        path = tmp_path / "run.jsonl"
        with pytest.raises(SecretLeakError):
            BatchStore(path, {"llm_api_key": "sk-abcdefghijklmnopqrstuvwxyz0123456789"})


class TestReadWrittenQids:
    def test_missing_file_is_an_empty_set(self, tmp_path):
        assert read_written_qids(tmp_path / "absent.jsonl") == set()

    def test_header_only_file_is_an_empty_set(self, tmp_path):
        path = tmp_path / "run.jsonl"
        BatchStore(path, {})
        assert read_written_qids(path) == set()

    def test_collects_every_written_question_id(self, tmp_path):
        path = tmp_path / "run.jsonl"
        store = BatchStore(path, {})
        store.append({"question_id": "pub-001"})
        store.append({"question_id": "pub-002"})
        assert read_written_qids(path) == {"pub-001", "pub-002"}
