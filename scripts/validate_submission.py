"""Validate Round 2 submission artifacts against the hackathon contract."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    import ogr  # noqa: F401
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from ogr.r2.metrics import Prices, compute_set_metrics
from ogr.r2.output import STATUSES, AnswerRecord

LLM_TOOLS = frozenset({"plan", "llm_step", "llm_answer"})
RUN_ID_RE = re.compile(r"^r2-(\d{8}T\d{6}Z)$")


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


def _is_non_neg_int(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool) and val >= 0


def _is_non_neg_num(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and val >= 0


def _parse_iso_utc(ts: Any) -> datetime | None:
    if not isinstance(ts, str) or not ts.strip():
        return None
    raw = ts.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(UTC)


def _load_jsonl(path: Path, label: str, errors: list[str]) -> list[tuple[int, dict[str, Any]]]:
    if not path.exists():
        errors.append(f"{label}: file not found: {path}")
        return []
    rows: list[tuple[int, dict[str, Any]]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"{label}: failed to read file ({exc})")
        return []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{label}:{lineno}: malformed JSON ({exc.msg})")
            continue
        if not isinstance(obj, dict):
            errors.append(f"{label}:{lineno}: expected JSON object, got {type(obj).__name__}")
            continue
        rows.append((lineno, obj))
    return rows


def _load_json(path: Path, label: str, errors: list[str]) -> Any:
    if not path.exists():
        errors.append(f"{label}: file not found: {path}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{label}: failed to parse JSON ({exc})")
        return None


def _load_question_qids(path: Path, label: str, errors: list[str]) -> list[str]:
    rows = _load_jsonl(path, label, errors)
    qids: list[str] = []
    for lineno, row in rows:
        qid = row.get("qid")
        if not isinstance(qid, str) or not qid:
            errors.append(f"{label}:{lineno}: missing or invalid qid")
            continue
        qids.append(qid)
    return qids


def _validate_answer_row(
    set_name: str,
    lineno: int,
    row: dict[str, Any],
    errors: list[str],
    warnings: list[str],
) -> tuple[AnswerRecord | None, list[tuple[int, str]]]:
    prefix = f"{set_name}:{lineno}"
    qid = row.get("qid")
    if not isinstance(qid, str) or not qid:
        errors.append(f"{prefix}: qid must be a non-empty string")
    else:
        prefix = f"{set_name}:{lineno} ({qid})"

    status = row.get("status")
    if not isinstance(status, str):
        errors.append(f"{prefix}: status must be a string")
    elif status not in STATUSES:
        errors.append(f"{prefix}: status {status!r} not in {STATUSES}")

    if "answer" not in row:
        errors.append(f"{prefix}: missing required key 'answer'")
    elif status == "not_in_corpus" and row["answer"] is not None:
        errors.append(f"{prefix}: not_in_corpus requires answer to be null")
    elif status in ("answered", "partial"):
        ans = row["answer"]
        if ans in (None, "", [], {}) or (isinstance(ans, str) and ans.strip() == ""):
            errors.append(f"{prefix}: {status} requires a non-empty answer")

    if not isinstance(row.get("explanation"), str):
        errors.append(f"{prefix}: explanation must be a string")

    citations = row.get("citations")
    citations_ok = isinstance(citations, list) and all(isinstance(c, str) for c in citations)
    if not citations_ok:
        errors.append(f"{prefix}: citations must be a list of strings")

    in_tok = row.get("input_tokens")
    out_tok = row.get("output_tokens")
    lat_ms = row.get("latency_ms")
    if not _is_non_neg_int(in_tok):
        errors.append(f"{prefix}: input_tokens must be a non-negative int")
    if not _is_non_neg_int(out_tok):
        errors.append(f"{prefix}: output_tokens must be a non-negative int")
    if not _is_non_neg_int(lat_ms):
        errors.append(f"{prefix}: latency_ms must be a non-negative int")

    trace = row.get("trace")
    trace_ok = isinstance(trace, list) and len(trace) > 0 and all(isinstance(s, dict) for s in trace)
    if not isinstance(trace, list) or len(trace) == 0:
        errors.append(f"{prefix}: trace must be a non-empty list of dicts")
    elif not all(isinstance(s, dict) for s in trace):
        errors.append(f"{prefix}: every trace element must be a dict")

    llm_in_sum = 0
    llm_out_sum = 0
    ms_sum = 0
    has_tg = False
    tg_steps: list[tuple[int, str]] = []

    if isinstance(trace, list) and len(trace) > 0:
        for idx, step in enumerate(trace, start=1):
            if not isinstance(step, dict):
                continue
            step_num = step.get("step")
            if isinstance(step_num, bool) or not isinstance(step_num, int) or step_num != idx:
                errors.append(f"{prefix} step {idx}: expected step={idx}, got {step_num!r}")

            tool = step.get("tool")
            if not isinstance(tool, str) or not tool:
                errors.append(f"{prefix} step {idx}: tool must be a non-empty string")

            tg = step.get("tigergraph")
            if not isinstance(tg, bool):
                errors.append(f"{prefix} step {idx}: tigergraph must be a bool")

            ms = step.get("ms")
            if not _is_non_neg_int(ms):
                errors.append(f"{prefix} step {idx}: ms must be a non-negative int")
            else:
                ms_sum += ms

            if tg is True:
                has_tg = True
                query = step.get("query")
                if not isinstance(query, str) or not query:
                    errors.append(f"{prefix} step {idx}: TigerGraph step requires non-empty query")
                if not isinstance(step.get("params"), dict):
                    errors.append(f"{prefix} step {idx}: TigerGraph step requires params dict")
                if not _is_non_neg_int(step.get("rows")):
                    errors.append(f"{prefix} step {idx}: TigerGraph step requires non-negative int rows")
                if (
                    isinstance(step_num, int)
                    and not isinstance(step_num, bool)
                    and isinstance(query, str)
                    and query
                ):
                    tg_steps.append((step_num, query))

            tool_str = tool if isinstance(tool, str) else ""
            is_llm = (
                "input_tokens" in step
                or "output_tokens" in step
                or (
                    tg is False
                    and (tool_str in LLM_TOOLS or tool_str.lower().startswith("llm"))
                )
            )
            if is_llm:
                s_in = step.get("input_tokens")
                s_out = step.get("output_tokens")
                if not _is_non_neg_int(s_in):
                    errors.append(f"{prefix} step {idx}: LLM step requires non-negative int input_tokens")
                else:
                    llm_in_sum += s_in
                if not _is_non_neg_int(s_out):
                    errors.append(f"{prefix} step {idx}: LLM step requires non-negative int output_tokens")
                else:
                    llm_out_sum += s_out

        if not has_tg:
            warnings.append(f"{prefix}: no TigerGraph step in trace")

    if _is_non_neg_int(in_tok) and llm_in_sum != in_tok:
        errors.append(f"{prefix}: input_tokens {in_tok} != LLM step sum {llm_in_sum}")
    if _is_non_neg_int(out_tok) and llm_out_sum != out_tok:
        errors.append(f"{prefix}: output_tokens {out_tok} != LLM step sum {llm_out_sum}")
    if _is_non_neg_int(lat_ms) and ms_sum > lat_ms * 1.05:
        errors.append(f"{prefix}: step ms sum {ms_sum} exceeds latency_ms {lat_ms} by >5%")

    record: AnswerRecord | None = None
    if (
        isinstance(qid, str)
        and qid
        and isinstance(status, str)
        and "answer" in row
        and isinstance(row.get("explanation"), str)
        and citations_ok
        and _is_non_neg_int(in_tok)
        and _is_non_neg_int(out_tok)
        and _is_non_neg_int(lat_ms)
        and trace_ok
    ):
        record = AnswerRecord(
            qid=qid,
            status=status,
            answer=row["answer"],
            explanation=row["explanation"],
            citations=list(citations),
            input_tokens=in_tok,
            output_tokens=out_tok,
            latency_ms=lat_ms,
            trace=list(trace),
        )
    return record, tg_steps


def _parse_query_log(
    path: Path,
    errors: list[str],
) -> tuple[dict[tuple[str, int, str], list[tuple[datetime, str | None]]], int]:
    rows = _load_jsonl(path, "query_log", errors)
    index: dict[tuple[str, int, str], list[tuple[datetime, str | None]]] = {}
    for lineno, row in rows:
        ts = _parse_iso_utc(row.get("ts"))
        qid = row.get("qid")
        step = row.get("step")
        query = row.get("query")
        run_id = row.get("run_id")
        if ts is None:
            errors.append(f"query_log:{lineno}: invalid or missing ISO-8601 UTC ts")
        if not isinstance(qid, str) or not qid:
            errors.append(f"query_log:{lineno}: qid must be a non-empty string")
        if isinstance(step, bool) or not isinstance(step, int):
            errors.append(f"query_log:{lineno}: step must be an int")
        if not isinstance(query, str) or not query:
            errors.append(f"query_log:{lineno}: query must be a non-empty string")
        if (
            ts is not None
            and isinstance(qid, str)
            and qid
            and isinstance(step, int)
            and not isinstance(step, bool)
            and isinstance(query, str)
            and query
        ):
            rid = run_id if isinstance(run_id, str) else None
            index.setdefault((qid, step, query), []).append((ts, rid))
    return index, len(rows)


def _check_query_log_and_timestamps(
    set_name: str,
    parsed_items: list[tuple[str | None, int | None, list[tuple[int, str]]]],
    log_index: dict[tuple[str, int, str], list[tuple[datetime, str | None]]],
    total_run_time_s: float | None,
    errors: list[str],
) -> None:
    set_matched: list[tuple[datetime, str | None]] = []
    for qid, lat_ms, tg_steps in parsed_items:
        if not qid or not tg_steps:
            continue
        q_matched: list[tuple[int, datetime, str | None]] = []
        for step_num, query in tg_steps:
            matches = log_index.get((qid, step_num, query))
            if not matches:
                errors.append(
                    f"{set_name} ({qid}) step {step_num}: missing query log entry for query {query!r}"
                )
                continue
            ts, run_id = matches[-1]
            q_matched.append((step_num, ts, run_id))
            set_matched.append((ts, run_id))

        if len(q_matched) >= 2:
            for k in range(len(q_matched) - 1):
                if q_matched[k][1] > q_matched[k + 1][1]:
                    errors.append(
                        f"{set_name} ({qid}): TG log timestamps decrease between steps "
                        f"{q_matched[k][0]} and {q_matched[k + 1][0]}"
                    )
            q_times = [item[1] for item in q_matched]
            q_span = (max(q_times) - min(q_times)).total_seconds()
            if _is_non_neg_int(lat_ms):
                allowed_q = lat_ms / 1000.0 * 1.05 + 1.0
                if q_span > allowed_q:
                    errors.append(
                        f"{set_name} ({qid}): TG log timestamp span {q_span:.3f}s > allowed {allowed_q:.3f}s"
                    )

    if set_matched and total_run_time_s is not None:
        allowed_set = total_run_time_s + max(5.0, total_run_time_s * 0.05)
        set_times = [ts for ts, _ in set_matched]
        set_span = (max(set_times) - min(set_times)).total_seconds()
        if set_span > allowed_set:
            errors.append(
                f"{set_name}: TG log span {set_span:.3f}s exceeds allowed {allowed_set:.3f}s"
            )
        for ts, run_id in set_matched:
            if not run_id:
                continue
            m = RUN_ID_RE.match(run_id)
            if not m:
                continue
            run_start = datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
            lo = run_start - timedelta(seconds=1)
            hi = run_start + timedelta(seconds=allowed_set)
            if ts < lo or ts > hi:
                errors.append(
                    f"{set_name}: TG log timestamp {ts.isoformat()} outside run window "
                    f"[{lo.isoformat()}, {hi.isoformat()}] for run_id {run_id}"
                )


def _check_metrics(
    metrics_data: Any,
    records_by_set: dict[str, list[AnswerRecord]],
    errors: list[str],
) -> dict[str, float | None]:
    run_times: dict[str, float | None] = {"public": None, "hidden": None}
    if not isinstance(metrics_data, dict):
        if metrics_data is not None:
            errors.append("metrics.json: root must be a JSON object")
        return run_times

    prices = Prices.from_env()
    for set_name in ("public", "hidden"):
        sec = metrics_data.get(set_name)
        if not isinstance(sec, dict):
            errors.append(f"metrics.json: missing or non-dict '{set_name}' section")
            continue

        trt = sec.get("total_run_time_s")
        if not _is_non_neg_num(trt):
            errors.append(f"metrics.json[{set_name}]: total_run_time_s must be a non-negative number")
        else:
            run_times[set_name] = float(trt)

        acc_pct = sec.get("accuracy_pct")
        acc_method: str | None = None
        if set_name == "hidden":
            if "accuracy_pct" not in sec or acc_pct is not None:
                errors.append("metrics.json[hidden]: accuracy_pct must be null")
            acc_pct_arg = None
        else:
            if not _is_non_neg_num(acc_pct) or acc_pct > 100:
                errors.append("metrics.json[public]: accuracy_pct must be a number in [0, 100]")
                acc_pct_arg = None
            else:
                acc_pct_arg = float(acc_pct)
            raw_method = sec.get("accuracy_method")
            if not isinstance(raw_method, str) or not raw_method.strip():
                errors.append("metrics.json[public]: accuracy_method must be a non-empty string")
            else:
                acc_method = raw_method

        if not _is_non_neg_num(trt):
            continue
        if set_name == "public" and (acc_pct_arg is None or acc_method is None):
            continue

        recomputed = compute_set_metrics(
            records_by_set[set_name],
            float(trt),
            prices=prices,
            accuracy_pct=acc_pct_arg,
            accuracy_method=acc_method,
        )
        for key, expected in recomputed.items():
            if key not in sec:
                errors.append(f"metrics.json[{set_name}]: missing key '{key}'")
                continue
            actual = sec[key]
            if expected is None:
                if actual is not None:
                    errors.append(f"metrics.json[{set_name}].{key}: expected null, got {actual!r}")
            elif isinstance(expected, str):
                if actual != expected:
                    errors.append(f"metrics.json[{set_name}].{key}: expected {expected!r}, got {actual!r}")
            elif isinstance(expected, int) and not isinstance(expected, bool):
                if isinstance(actual, bool) or not isinstance(actual, int) or actual != expected:
                    errors.append(f"metrics.json[{set_name}].{key}: expected {expected!r}, got {actual!r}")
            elif _is_non_neg_num(expected):
                if not _is_non_neg_num(actual) or abs(float(actual) - float(expected)) > 1e-6:
                    errors.append(f"metrics.json[{set_name}].{key}: expected {expected!r}, got {actual!r}")

    return run_times


def _check_graph_counts(gc_data: Any, errors: list[str]) -> None:
    if gc_data is None:
        return
    if not isinstance(gc_data, dict) or not gc_data:
        errors.append("graph_counts.json: must be a non-empty JSON object")
        return

    def check_counts_dict(d: Any, label: str) -> None:
        if not isinstance(d, dict) or not d:
            errors.append(f"{label}: must be a non-empty JSON object")
            return
        total = 0
        for k, v in d.items():
            if not _is_non_neg_int(v):
                errors.append(f"{label}.{k}: count must be a non-negative int, got {v!r}")
            else:
                total += v
        if total <= 0:
            errors.append(f"{label}: total count must be > 0")

    if "vertices" in gc_data or "edges" in gc_data:
        if "vertices" not in gc_data or "edges" not in gc_data:
            errors.append("graph_counts.json: must contain both 'vertices' and 'edges'")
            return
        check_counts_dict(gc_data["vertices"], "graph_counts.json.vertices")
        check_counts_dict(gc_data["edges"], "graph_counts.json.edges")
    else:
        check_counts_dict(gc_data, "graph_counts.json")


def _check_qids(
    set_name: str,
    answer_qids: list[str],
    question_qids: list[str],
    errors: list[str],
) -> None:
    seen: set[str] = set()
    dups: list[str] = []
    for qid in answer_qids:
        if qid in seen and qid not in dups:
            dups.append(qid)
        seen.add(qid)
    if dups:
        errors.append(f"{set_name}: duplicate qids in answers: {dups}")

    q_set = set(question_qids)
    missing = sorted(q_set - seen)
    extra = sorted(seen - q_set)
    if missing:
        errors.append(f"{set_name}: missing qids from answers ({len(missing)}): {missing[:10]}")
    if extra:
        errors.append(f"{set_name}: extra qids not in questions ({len(extra)}): {extra[:10]}")


def validate_submission(
    public_answers: str | Path = "answers_public.jsonl",
    hidden_answers: str | Path = "answers_hidden.jsonl",
    metrics_path: str | Path = "out/r2/metrics.json",
    query_log_path: str | Path = "out/r2/tg_query_log.jsonl",
    graph_counts_path: str | Path = "out/r2/graph_counts.json",
    public_questions: str | Path = "docs/round-2/data/questions_public.jsonl",
    hidden_questions: str | Path = "docs/round-2/data/questions_hidden.jsonl",
) -> ValidationReport:
    errors: list[str] = []
    warnings: list[str] = []

    answer_paths = {"public": Path(public_answers), "hidden": Path(hidden_answers)}
    question_paths = {"public": Path(public_questions), "hidden": Path(hidden_questions)}

    records_by_set: dict[str, list[AnswerRecord]] = {"public": [], "hidden": []}
    answer_qids: dict[str, list[str]] = {"public": [], "hidden": []}
    parsed_tg_items: dict[str, list[tuple[str | None, int | None, list[tuple[int, str]]]]] = {
        "public": [],
        "hidden": [],
    }

    for set_name in ("public", "hidden"):
        rows = _load_jsonl(answer_paths[set_name], f"{set_name}_answers", errors)
        for lineno, row in rows:
            rec, tg_steps = _validate_answer_row(set_name, lineno, row, errors, warnings)
            qid = row.get("qid") if isinstance(row.get("qid"), str) and row.get("qid") else None
            if qid is not None:
                answer_qids[set_name].append(qid)
            lat = row.get("latency_ms") if _is_non_neg_int(row.get("latency_ms")) else None
            parsed_tg_items[set_name].append((qid, lat, tg_steps))
            if rec is not None:
                records_by_set[set_name].append(rec)

    question_qids = {
        set_name: _load_question_qids(question_paths[set_name], f"{set_name}_questions", errors)
        for set_name in ("public", "hidden")
    }
    for set_name in ("public", "hidden"):
        _check_qids(set_name, answer_qids[set_name], question_qids[set_name], errors)

    metrics_data = _load_json(Path(metrics_path), "metrics.json", errors)
    run_times = _check_metrics(metrics_data, records_by_set, errors)

    log_index, log_count = _parse_query_log(Path(query_log_path), errors)
    for set_name in ("public", "hidden"):
        _check_query_log_and_timestamps(
            set_name,
            parsed_tg_items[set_name],
            log_index,
            run_times[set_name],
            errors,
        )

    gc_data = _load_json(Path(graph_counts_path), "graph_counts.json", errors)
    _check_graph_counts(gc_data, errors)

    summary = {
        "public_answers": len(answer_qids["public"]),
        "hidden_answers": len(answer_qids["hidden"]),
        "public_questions": len(question_qids["public"]),
        "hidden_questions": len(question_qids["hidden"]),
        "query_log_entries": log_count,
        "errors": len(errors),
        "warnings": len(warnings),
        "valid": len(errors) == 0,
    }
    return ValidationReport(errors=errors, warnings=warnings, summary=summary)


def format_report(report: ValidationReport) -> str:
    lines = [
        f"Validation {'PASSED' if report.summary.get('valid', not report.errors) else 'FAILED'} "
        f"({len(report.errors)} errors, {len(report.warnings)} warnings)",
        f"Summary: {report.summary}",
    ]
    if report.errors:
        lines.append("Errors:")
        lines.extend(f"  - {err}" for err in report.errors)
    if report.warnings:
        lines.append("Warnings:")
        lines.extend(f"  - {warn}" for warn in report.warnings)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Round 2 submission artifacts.")
    parser.add_argument("--public-answers", default="answers_public.jsonl")
    parser.add_argument("--hidden-answers", default="answers_hidden.jsonl")
    parser.add_argument("--metrics", default="out/r2/metrics.json")
    parser.add_argument("--query-log", default="out/r2/tg_query_log.jsonl")
    parser.add_argument("--graph-counts", default="out/r2/graph_counts.json")
    parser.add_argument("--public-questions", default="docs/round-2/data/questions_public.jsonl")
    parser.add_argument("--hidden-questions", default="docs/round-2/data/questions_hidden.jsonl")
    args = parser.parse_args(argv)

    report = validate_submission(
        public_answers=args.public_answers,
        hidden_answers=args.hidden_answers,
        metrics_path=args.metrics,
        query_log_path=args.query_log,
        graph_counts_path=args.graph_counts,
        public_questions=args.public_questions,
        hidden_questions=args.hidden_questions,
    )
    print(format_report(report))
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
