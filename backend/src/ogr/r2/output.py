"""Answer line (brief item 1/2): dataclass, validation, JSONL read/write."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

STATUSES = ("answered", "partial", "not_in_corpus")


@dataclass
class AnswerRecord:
    qid: str
    status: str
    answer: Any
    explanation: str = ""
    citations: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    trace: list[dict] = field(default_factory=list)
    # Set when the run failed on this question. Such a record is never
    # written to the answers file: a re-run retries it (resume), so no
    # crash is ever submitted as if it were an answer.
    error: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("error")
        return d

    @classmethod
    def from_dict(cls, d: dict) -> AnswerRecord:
        return cls(qid=d["qid"], status=d["status"], answer=d.get("answer"),
                   explanation=d.get("explanation", ""), citations=list(d.get("citations") or []),
                   input_tokens=int(d.get("input_tokens", 0)), output_tokens=int(d.get("output_tokens", 0)),
                   latency_ms=int(d.get("latency_ms", 0)), trace=list(d.get("trace") or []))


def validate(rec: AnswerRecord) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Errors break the brief's format; warnings are soft checks."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(rec.qid, str) or not rec.qid:
        errors.append("qid must be a non-empty string")
    if rec.status not in STATUSES:
        errors.append(f"status {rec.status!r} not in {STATUSES}")
    if rec.status == "not_in_corpus" and rec.answer is not None:
        errors.append("not_in_corpus requires answer null")
    if rec.status in ("answered", "partial") and rec.answer in (None, "", [], {}):
        errors.append(f"{rec.status} requires a non-empty answer")
    if not isinstance(rec.citations, list) or not all(isinstance(c, str) for c in rec.citations):
        errors.append("citations must be a list of strings")
    if not isinstance(rec.latency_ms, int) or isinstance(rec.latency_ms, bool) or rec.latency_ms < 0:
        errors.append("latency_ms must be an int >= 0")
    in_sum = out_sum = ms_sum = 0
    for i, step in enumerate(rec.trace, start=1):
        if step.get("step") != i:
            errors.append(f"trace step {i} is numbered {step.get('step')!r}")
        for key in ("tool", "tigergraph", "ms"):
            if key not in step:
                errors.append(f"trace step {i} lacks {key}")
        if step.get("tigergraph"):
            for key in ("query", "params", "rows"):
                if key not in step:
                    errors.append(f"TigerGraph step {i} lacks {key}")
        if "input_tokens" in step or "output_tokens" in step:
            in_sum += step.get("input_tokens", 0)
            out_sum += step.get("output_tokens", 0)
        ms_sum += step.get("ms", 0) or 0
    if not rec.trace:
        errors.append("trace is empty")
    if in_sum != rec.input_tokens or out_sum != rec.output_tokens:
        errors.append(f"token totals {rec.input_tokens}/{rec.output_tokens} != "
                      f"LLM step sums {in_sum}/{out_sum}")
    if rec.trace and not any(s.get("tigergraph") for s in rec.trace):
        warnings.append("no TigerGraph step in trace (will be checked closely)")
    if rec.latency_ms and (ms_sum > rec.latency_ms * 1.1 + 50 or ms_sum < rec.latency_ms * 0.5 - 50):
        warnings.append(f"step times sum {ms_sum} ms vs latency_ms {rec.latency_ms}")
    return errors, warnings


def write_answers(path: str | Path, records: list[AnswerRecord]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")


def read_answers(path: str | Path) -> list[AnswerRecord]:
    out = []
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                out.append(AnswerRecord.from_dict(json.loads(line)))
    return out
