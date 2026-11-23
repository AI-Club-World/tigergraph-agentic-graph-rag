"""Per-question trace recorder (brief 'Traces').

Steps are numbered from 1 in the order they are recorded and handed to `sink` (if any) the
moment they happen, so the trace is written by the running code, not reconstructed. LLM steps
carry tokens, TigerGraph steps carry query/params/rows, every step carries ms.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from ogr.r2.querylog import QueryLog


class Timer:
    """`with Timer() as t: ...` then `t.ms` (int) and `t.started_at` (UTC datetime)."""

    def __init__(self) -> None:
        self.started_at = datetime.now(UTC)
        self._t0 = time.perf_counter()
        self._elapsed: float | None = None

    def __enter__(self) -> Timer:
        self.started_at = datetime.now(UTC)
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        self._elapsed = time.perf_counter() - self._t0

    @property
    def ms(self) -> int:
        elapsed = self._elapsed if self._elapsed is not None else time.perf_counter() - self._t0
        return int(round(elapsed * 1000))


class TraceRecorder:
    def __init__(self, qid: str, querylog: QueryLog | None = None,
                 sink: Callable[[dict], None] | None = None) -> None:
        self.qid = qid
        self.querylog = querylog
        self.sink = sink
        self._steps: list[dict] = []

    def timer(self) -> Timer:
        return Timer()

    def _add(self, step: dict) -> dict:
        step = {"step": len(self._steps) + 1, **step}
        if step.get("note") is None:
            step.pop("note", None)
        self._steps.append(step)
        if self.sink is not None:
            self.sink(dict(step))
        return step

    def llm(self, tool: str, input_tokens: int, output_tokens: int, ms: int, note: str | None = None) -> dict:
        return self._add({"tool": tool, "tigergraph": False, "input_tokens": int(input_tokens),
                          "output_tokens": int(output_tokens), "ms": int(ms), "note": note})

    def tg(self, tool: str, query: str, params: Any, rows: int, ms: int, note: str | None = None, *,
           ok: bool = True, error: str | None = None, started_at: datetime | None = None) -> dict:
        step = self._add({"tool": tool, "tigergraph": True, "query": query, "params": params,
                          "rows": int(rows), "ms": int(ms), "note": note})
        if self.querylog is not None:
            started = started_at or datetime.now(UTC) - timedelta(milliseconds=int(ms))
            self.querylog.log(qid=self.qid, step=step["step"], query=query, params=params,
                              rows=int(rows), ms=int(ms), ok=ok, error=error, started_at=started)
        return step

    def local(self, tool: str, ms: int, note: str | None = None) -> dict:
        return self._add({"tool": tool, "tigergraph": False, "ms": int(ms), "note": note})

    def totals(self) -> dict[str, int]:
        llm = [s for s in self._steps if "input_tokens" in s]
        return {"input_tokens": sum(s["input_tokens"] for s in llm),
                "output_tokens": sum(s["output_tokens"] for s in llm)}

    def to_list(self) -> list[dict]:
        return [dict(s) for s in self._steps]
