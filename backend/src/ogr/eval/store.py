"""Batch output store — append-only JSONL per run, plus a run_config header.

Source spec: TECHNICAL-SPEC §14.3, §6.4
Requirement: NFR-4 · Gate: G5

DP-3 Option A: append-only JSONL, diffable and resumable, no migration cost.
The first line of the file is a header carrying `run_config`, so a result is
reproducible without a second file (NFR-4). A write-time assertion blocks
anything that looks like a credential from ever reaching disk —
TECHNICAL-SPEC §14.3: "No credential appears in ... a persisted record ...
enforced by a write-time assertion in the record store, not by reviewer
attention."
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from ogr.common.contracts import GRAPH_ERROR_PREFIX

__all__ = ["SecretLeakError", "BatchStore", "iter_lines", "read_written_qids", "repair_tail"]

# Two checks. (1) Known credential shapes: OpenAI/Anthropic (sk-), Groq,
# Google, Hugging Face, GitHub, and JWTs (TigerGraph Savanna TG_JWT_TOKEN).
# (2) The configured secrets themselves: TigerGraph secrets/tokens and
# passwords have no recognisable shape, so the actual values from the
# environment are searched for. Deliberately loose: a false positive here just
# blocks a write, which is the safe failure mode.
_SECRET_LIKE = re.compile(
    r"sk-[A-Za-z0-9_-]{16,}"
    r"|gsk_[A-Za-z0-9]{20,}"
    r"|AIza[0-9A-Za-z_-]{35}"
    r"|hf_[A-Za-z0-9]{30,}"
    r"|gh[pousr]_[A-Za-z0-9]{36,}"
    r"|eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+"
)
_SECRET_ENV_VARS = ("LLM_API_KEY", "TG_PASSWORD", "TG_SECRET", "TG_TOKEN", "TG_JWT_TOKEN", "OGR_API_KEY")
# Shorter configured values are too likely to occur in ordinary answer text.
_MIN_SECRET_LEN = 8


class SecretLeakError(ValueError):
    """Raised when a value that looks like a credential would be persisted."""


def _assert_no_secret(obj: Any) -> None:
    text = json.dumps(obj, default=str)
    if _SECRET_LIKE.search(text):
        raise SecretLeakError("Refusing to persist a record containing what looks like an API key")
    for name in _SECRET_ENV_VARS:
        value = os.environ.get(name, "")
        if len(value) >= _MIN_SECRET_LEN and value in text:
            raise SecretLeakError(f"Refusing to persist a record containing the value of {name}")


class BatchStore:
    """Append-only JSONL writer for one batch run.

    The output file's first line is `{"run_config": {...}}`; every line after
    that is one BatchRecord. Re-opening an existing path does not rewrite the
    header — resume (EVAL-04) depends on the file being appended to, not
    replaced.
    """

    def __init__(self, path: str | Path, run_config: dict[str, Any]) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _assert_no_secret(run_config)
        self.run_config = run_config
        # A run killed mid-write leaves a partial last line; appending after
        # it would bury a corrupt line mid-file, so it is cut first (that
        # question was never recorded and runs again).
        repair_tail(self.path)
        if not self.path.exists():
            with self.path.open("w", encoding="utf-8") as handle:
                handle.write(json.dumps({"run_config": run_config}) + "\n")

    def append(self, record: dict[str, Any]) -> None:
        _assert_no_secret(record)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")


def repair_tail(path: str | Path) -> bool:
    """Truncate a last line that was never finished (no trailing newline and
    not valid JSON). Returns whether anything was cut."""
    file_path = Path(path)
    if not file_path.exists() or file_path.stat().st_size == 0:
        return False
    data = file_path.read_bytes()
    if data.endswith(b"\n"):
        return False
    cut = data.rfind(b"\n") + 1
    try:
        json.loads(data[cut:])
        return False  # complete, just unterminated
    except ValueError:
        with file_path.open("r+b") as handle:
            handle.truncate(cut)
        return True


def iter_lines(path: str | Path):
    """Parsed JSON lines of a run file; an unfinished last line is skipped
    (a run still writing, or one killed mid-write)."""
    with Path(path).open(encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except ValueError:
                if raw.endswith("\n"):
                    raise
                return


def _has_error(record: dict[str, Any]) -> bool:
    """A pipeline errored, or a graph query failed while it answered (the
    answer then stood on missing evidence, e.g. a workspace mid-restart):
    either way the question is retried on resume."""
    pipelines = (record.get("record") or {}).get("pipelines") or {}
    return any(
        (p or {}).get("status") == "error"
        or str((p or {}).get("error_detail") or "").startswith(GRAPH_ERROR_PREFIX)
        for p in pipelines.values()
    )


def read_written_qids(path: str | Path) -> set[str]:
    """`question_id`s already recorded *successfully*, for resume-by-skip.

    A question whose latest record has a pipeline in error is not counted, so
    a resume retries it (its new record supersedes the old one — readers keep
    the last record per question). Missing or header-only files yield an
    empty set, so a fresh run and a not-yet-started resume behave identically.
    """
    file_path = Path(path)
    if not file_path.exists():
        return set()
    latest: dict[str, bool] = {}
    for data in iter_lines(file_path):
        question_id = data.get("question_id")
        if question_id:
            latest[question_id] = _has_error(data)
    return {qid for qid, errored in latest.items() if not errored}
