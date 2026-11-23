"""Append-only JSONL log of every TigerGraph call (brief item 5).

One line per call: ts (ISO UTC, ms, taken when the call STARTS), run_id, qid, step, query,
params, rows, ms, ok, error. Thread-safe; the file is opened per write so a crash loses nothing.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_QUERY_LOG = "out/r2/tg_query_log.jsonl"


def default_log_path() -> Path:
    return Path(os.environ.get("R2_QUERY_LOG") or DEFAULT_QUERY_LOG)


def iso_ms(moment: datetime | None = None) -> str:
    moment = moment or datetime.now(UTC)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


class QueryLog:
    def __init__(self, path: str | Path | None = None, run_id: str = "") -> None:
        self.path = Path(path) if path else default_log_path()
        self.run_id = run_id
        self._lock = threading.Lock()

    def log(self, *, qid: str, step: int, query: str, params: Any, rows: int, ms: int,
            ok: bool = True, error: str | None = None, started_at: datetime | None = None) -> dict:
        entry = {
            "ts": iso_ms(started_at), "run_id": self.run_id, "qid": qid, "step": step,
            "query": query, "params": params, "rows": rows, "ms": ms, "ok": ok, "error": error,
        }
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        return entry
