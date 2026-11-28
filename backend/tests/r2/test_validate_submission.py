import importlib.util
import json
import sys
from pathlib import Path

from ogr.r2.metrics import Prices, compute_set_metrics
from ogr.r2.output import AnswerRecord


def _load_validator():
    root = Path(__file__).resolve().parents[3]
    script_path = root / "scripts" / "validate_submission.py"
    spec = importlib.util.spec_from_file_location("validate_submission", script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


VAL = _load_validator()


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n",
        encoding="utf-8",
    )


def _make_valid_fixture(tmp_path: Path) -> dict[str, Path]:
    pub_q = [{"qid": "pub-1"}, {"qid": "pub-2"}]
    hid_q = [{"qid": "hid-1"}, {"qid": "hid-2"}]

    pub_a = [
        {
            "qid": "pub-1",
            "status": "answered",
            "answer": "42",
            "explanation": "Found in graph.",
            "citations": ["doc-1"],
            "input_tokens": 300,
            "output_tokens": 50,
            "latency_ms": 1000,
            "trace": [
                {
                    "step": 1,
                    "tool": "plan",
                    "tigergraph": False,
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "ms": 300,
                },
                {
                    "step": 2,
                    "tool": "tg_query",
                    "tigergraph": True,
                    "query": "get_fact",
                    "params": {"id": "1"},
                    "rows": 3,
                    "ms": 100,
                },
                {
                    "step": 3,
                    "tool": "rank_rows",
                    "tigergraph": False,
                    "ms": 50,
                },
                {
                    "step": 4,
                    "tool": "llm_answer",
                    "tigergraph": False,
                    "input_tokens": 200,
                    "output_tokens": 30,
                    "ms": 550,
                },
            ],
        },
        {
            "qid": "pub-2",
            "status": "not_in_corpus",
            "answer": None,
            "explanation": "Not found.",
            "citations": [],
            "input_tokens": 150,
            "output_tokens": 25,
            "latency_ms": 500,
            "trace": [
                {
                    "step": 1,
                    "tool": "tg_query",
                    "tigergraph": True,
                    "query": "search_docs",
                    "params": {"q": "missing"},
                    "rows": 0,
                    "ms": 100,
                },
                {
                    "step": 2,
                    "tool": "llm_answer",
                    "tigergraph": False,
                    "input_tokens": 150,
                    "output_tokens": 25,
                    "ms": 400,
                },
            ],
        },
    ]

    hid_a = [
        {
            "qid": "hid-1",
            "status": "partial",
            "answer": {"value": "partial"},
            "explanation": "Partial evidence.",
            "citations": ["doc-2"],
            "input_tokens": 120,
            "output_tokens": 30,
            "latency_ms": 600,
            "trace": [
                {
                    "step": 1,
                    "tool": "tg_query",
                    "tigergraph": True,
                    "query": "get_fact",
                    "params": {"id": "2"},
                    "rows": 1,
                    "ms": 100,
                },
                {
                    "step": 2,
                    "tool": "llm_step",
                    "tigergraph": False,
                    "input_tokens": 120,
                    "output_tokens": 30,
                    "ms": 500,
                },
            ],
        },
        {
            "qid": "hid-2",
            "status": "answered",
            "answer": "Paris",
            "explanation": "Direct match.",
            "citations": ["doc-3"],
            "input_tokens": 100,
            "output_tokens": 20,
            "latency_ms": 400,
            "trace": [
                {
                    "step": 1,
                    "tool": "tg_query",
                    "tigergraph": True,
                    "query": "get_city",
                    "params": {},
                    "rows": 1,
                    "ms": 80,
                },
                {
                    "step": 2,
                    "tool": "llm_answer",
                    "tigergraph": False,
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "ms": 320,
                },
            ],
        },
    ]

    qlog = [
        {
            "ts": "2026-11-28T10:00:01.000Z",
            "run_id": "r2-20261128T100000Z",
            "qid": "pub-1",
            "step": 2,
            "query": "get_fact",
            "params": {"id": "1"},
            "rows": 3,
            "ms": 100,
            "ok": True,
            "error": None,
        },
        {
            "ts": "2026-11-28T10:00:05.000Z",
            "run_id": "r2-20261128T100000Z",
            "qid": "pub-2",
            "step": 1,
            "query": "search_docs",
            "params": {"q": "missing"},
            "rows": 0,
            "ms": 100,
            "ok": True,
            "error": None,
        },
        {
            "ts": "2026-11-28T10:05:01.000Z",
            "run_id": "r2-20261128T100500Z",
            "qid": "hid-1",
            "step": 1,
            "query": "get_fact",
            "params": {"id": "2"},
            "rows": 1,
            "ms": 100,
            "ok": True,
            "error": None,
        },
        {
            "ts": "2026-11-28T10:05:05.000Z",
            "run_id": "r2-20261128T100500Z",
            "qid": "hid-2",
            "step": 1,
            "query": "get_city",
            "params": {},
            "rows": 1,
            "ms": 80,
            "ok": True,
            "error": None,
        },
    ]

    pub_recs = [AnswerRecord.from_dict(r) for r in pub_a]
    hid_recs = [AnswerRecord.from_dict(r) for r in hid_a]
    metrics = {
        "public": compute_set_metrics(
            pub_recs, 10.0, prices=Prices.from_env(), accuracy_pct=50.0, accuracy_method="exact"
        ),
        "hidden": compute_set_metrics(
            hid_recs, 10.0, prices=Prices.from_env(), accuracy_pct=None
        ),
    }

    graph_counts = {"vertices": {"Document": 10, "Entity": 20}, "edges": {"MENTIONS": 30}}

    paths = {
        "public_questions": tmp_path / "questions_public.jsonl",
        "hidden_questions": tmp_path / "questions_hidden.jsonl",
        "public_answers": tmp_path / "answers_public.jsonl",
        "hidden_answers": tmp_path / "answers_hidden.jsonl",
        "query_log": tmp_path / "tg_query_log.jsonl",
        "metrics": tmp_path / "metrics.json",
        "graph_counts": tmp_path / "graph_counts.json",
    }
    _write_jsonl(paths["public_questions"], pub_q)
    _write_jsonl(paths["hidden_questions"], hid_q)
    _write_jsonl(paths["public_answers"], pub_a)
    _write_jsonl(paths["hidden_answers"], hid_a)
    _write_jsonl(paths["query_log"], qlog)
    paths["metrics"].write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    paths["graph_counts"].write_text(json.dumps(graph_counts, indent=2), encoding="utf-8")
    return paths


def _run_validate(paths: dict[str, Path]):
    return VAL.validate_submission(
        public_answers=paths["public_answers"],
        hidden_answers=paths["hidden_answers"],
        metrics_path=paths["metrics"],
        query_log_path=paths["query_log"],
        graph_counts_path=paths["graph_counts"],
        public_questions=paths["public_questions"],
        hidden_questions=paths["hidden_questions"],
    )


def _cli_args(paths: dict[str, Path]) -> list[str]:
    return [
        "--public-answers", str(paths["public_answers"]),
        "--hidden-answers", str(paths["hidden_answers"]),
        "--metrics", str(paths["metrics"]),
        "--query-log", str(paths["query_log"]),
        "--graph-counts", str(paths["graph_counts"]),
        "--public-questions", str(paths["public_questions"]),
        "--hidden-questions", str(paths["hidden_questions"]),
    ]


def test_valid_submission_passes(tmp_path, capsys):
    paths = _make_valid_fixture(tmp_path)
    report = _run_validate(paths)
    assert report.errors == []
    assert report.warnings == []
    assert report.summary["valid"] is True
    rc = VAL.main(_cli_args(paths))
    assert rc == 0
    assert "Validation PASSED" in capsys.readouterr().out


def test_check1_raw_field_types_and_malformed_json(tmp_path):
    paths = _make_valid_fixture(tmp_path)
    rows = [json.loads(line) for line in paths["public_answers"].read_text(encoding="utf-8").splitlines()]
    rows[0]["input_tokens"] = True  # bool is not valid int
    del rows[0]["answer"]
    _write_jsonl(paths["public_answers"], rows)
    report = _run_validate(paths)
    assert any("input_tokens" in e for e in report.errors)
    assert any("missing required key 'answer'" in e for e in report.errors)

    paths["hidden_answers"].write_text("{bad json\n", encoding="utf-8")
    report2 = _run_validate(paths)
    assert any("malformed JSON" in e for e in report2.errors)


def test_check2_status_and_null_rules(tmp_path):
    paths = _make_valid_fixture(tmp_path)
    rows = [json.loads(line) for line in paths["public_answers"].read_text(encoding="utf-8").splitlines()]
    rows[0]["status"] = "unknown_status"
    rows[1]["answer"] = "should be null"
    _write_jsonl(paths["public_answers"], rows)
    report = _run_validate(paths)
    assert any("not in" in e for e in report.errors)
    assert any("not_in_corpus requires answer to be null" in e for e in report.errors)


def test_check3_trace_step_schema(tmp_path):
    paths = _make_valid_fixture(tmp_path)
    rows = [json.loads(line) for line in paths["public_answers"].read_text(encoding="utf-8").splitlines()]
    del rows[0]["trace"][0]["output_tokens"]  # LLM step ("plan") missing output_tokens
    del rows[0]["trace"][1]["params"]  # TG step missing params
    rows[0]["trace"][2]["step"] = 99  # wrong step number
    _write_jsonl(paths["public_answers"], rows)
    report = _run_validate(paths)
    assert any("LLM step requires non-negative int output_tokens" in e for e in report.errors)
    assert any("TigerGraph step requires params dict" in e for e in report.errors)
    assert any("expected step=3, got 99" in e for e in report.errors)


def test_check4_token_sum_mismatch(tmp_path):
    paths = _make_valid_fixture(tmp_path)
    rows = [json.loads(line) for line in paths["public_answers"].read_text(encoding="utf-8").splitlines()]
    rows[0]["input_tokens"] = 999
    _write_jsonl(paths["public_answers"], rows)
    report = _run_validate(paths)
    assert any("input_tokens 999 != LLM step sum 300" in e for e in report.errors)


def test_check5_step_timing_boundary_and_excess(tmp_path):
    paths = _make_valid_fixture(tmp_path)
    rows = [json.loads(line) for line in paths["hidden_answers"].read_text(encoding="utf-8").splitlines()]
    # Sum of ms in hid-2 is 80 + 320 = 400. Set latency_ms so 400 <= 381 * 1.05 (400.05) -> OK
    rows[1]["latency_ms"] = 381
    _write_jsonl(paths["hidden_answers"], rows)
    # Recompute metrics so metrics check stays clean
    metrics = json.loads(paths["metrics"].read_text(encoding="utf-8"))
    hid_recs = [AnswerRecord.from_dict(r) for r in rows]
    metrics["hidden"] = compute_set_metrics(hid_recs, 10.0, prices=Prices.from_env(), accuracy_pct=None)
    paths["metrics"].write_text(json.dumps(metrics), encoding="utf-8")

    ok_report = _run_validate(paths)
    assert not any("exceeds latency_ms" in e for e in ok_report.errors)

    # Now 400 > 380 * 1.05 (399.0) -> ERROR
    rows[1]["latency_ms"] = 380
    _write_jsonl(paths["hidden_answers"], rows)
    bad_report = _run_validate(paths)
    assert any("exceeds latency_ms" in e for e in bad_report.errors)


def test_check6_query_log_missing_and_out_of_run_timestamp(tmp_path):
    paths = _make_valid_fixture(tmp_path)
    qlog = [json.loads(line) for line in paths["query_log"].read_text(encoding="utf-8").splitlines()]
    # Move pub-1 timestamp outside run window and remove hid-2 log entry
    qlog[0]["ts"] = "2026-11-28T10:02:00.000Z"
    qlog = qlog[:-1]
    _write_jsonl(paths["query_log"], qlog)
    report = _run_validate(paths)
    assert any("outside run window" in e for e in report.errors)
    assert any("missing query log entry" in e for e in report.errors)


def test_check7_no_tg_step_warns_only_exit_zero(tmp_path):
    paths = _make_valid_fixture(tmp_path)
    rows = [json.loads(line) for line in paths["public_answers"].read_text(encoding="utf-8").splitlines()]
    rows[1]["trace"] = [
        {
            "step": 1,
            "tool": "llm_answer",
            "tigergraph": False,
            "input_tokens": 150,
            "output_tokens": 25,
            "ms": 500,
        }
    ]
    _write_jsonl(paths["public_answers"], rows)
    metrics = json.loads(paths["metrics"].read_text(encoding="utf-8"))
    pub_recs = [AnswerRecord.from_dict(r) for r in rows]
    metrics["public"] = compute_set_metrics(
        pub_recs, 10.0, prices=Prices.from_env(), accuracy_pct=50.0, accuracy_method="exact"
    )
    paths["metrics"].write_text(json.dumps(metrics), encoding="utf-8")

    report = _run_validate(paths)
    assert report.errors == []
    assert any("no TigerGraph step" in w for w in report.warnings)
    assert VAL.main(_cli_args(paths)) == 0


def test_check8_metrics_mismatch_and_non_null_hidden_accuracy(tmp_path):
    paths = _make_valid_fixture(tmp_path)
    metrics = json.loads(paths["metrics"].read_text(encoding="utf-8"))
    metrics["public"]["input_tokens_total"] += 1
    metrics["hidden"]["accuracy_pct"] = 75.0
    paths["metrics"].write_text(json.dumps(metrics), encoding="utf-8")

    report = _run_validate(paths)
    assert any("input_tokens_total" in e for e in report.errors)
    assert any("accuracy_pct must be null" in e for e in report.errors)
    assert VAL.main(_cli_args(paths)) == 1


def test_check9_graph_counts_missing_or_empty(tmp_path):
    paths = _make_valid_fixture(tmp_path)
    paths["graph_counts"].write_text("{}", encoding="utf-8")
    report = _run_validate(paths)
    assert any("graph_counts.json" in e for e in report.errors)

    paths["graph_counts"].unlink()
    report2 = _run_validate(paths)
    assert any("file not found" in e for e in report2.errors)


def test_check10_qid_mismatch_and_duplicates(tmp_path):
    paths = _make_valid_fixture(tmp_path)
    rows = [json.loads(line) for line in paths["public_answers"].read_text(encoding="utf-8").splitlines()]
    rows[1]["qid"] = "pub-1"  # duplicate pub-1, missing pub-2
    rows.append(dict(rows[0], qid="pub-extra"))
    _write_jsonl(paths["public_answers"], rows)
    report = _run_validate(paths)
    assert any("duplicate qids" in e for e in report.errors)
    assert any("missing qids" in e for e in report.errors)
    assert any("extra qids" in e for e in report.errors)
