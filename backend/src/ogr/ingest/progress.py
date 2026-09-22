"""Build-event emitter (GRAPH-09) for the three-column build view.

Source spec: implementation-plan-GRAPH.md Group 3 · implementation-plan-UI.md DP-6/DP-7
Requirement: new UI requirement, NFR-3 · Gate: G1

There are not three independent builds — chunk+embed feeds all three
pipelines, schema+parse+load feeds graphrag and agentic, query-library
install feeds all three (DP-6 Option A). `pipeline_affected` is a list for
exactly that reason: it is how one shared build can drive three honest
per-pipeline readiness columns without inventing three separate builds.

`tokens` is always 0. Ingestion is deterministic parsing plus a *local*
embedding model — there is no LLM call anywhere in this path (AD-6) — so the
build columns report wall-time, document/chunk/vertex counts and a stated
`tokens: 0`, never a fabricated or hidden figure (DP-7 Option A).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

__all__ = ["BuildEvent", "BuildProgress"]

BuildStatus = Literal["running", "done", "error", "ready"]


@dataclass
class BuildEvent:
    """One ingestion progress event (TECHNICAL-SPEC §4.6)."""

    stage: str
    pipeline_affected: list[str] = field(default_factory=list)
    status: BuildStatus = "running"
    items_done: int = 0
    items_total: int = 0
    elapsed_ms: float = 0.0
    tokens: int = 0
    note: str = ""


class BuildProgress:
    """Fire-and-forget emitter a build stage reports through.

    `on_event` is optional so ingestion can run headless (e.g. from the CLI)
    with no subscriber at all — the emitter never blocks or fails ingestion
    if nothing is listening.
    """

    def __init__(self, on_event: Callable[[BuildEvent], None] | None = None) -> None:
        self._on_event = on_event
        self._stage_started: dict[str, float] = {}

    def start(self, stage: str, pipeline_affected: list[str], items_total: int = 0) -> None:
        self._stage_started[stage] = time.perf_counter()
        self._emit(BuildEvent(
            stage=stage, pipeline_affected=pipeline_affected,
            status="running", items_total=items_total,
        ))

    def progress(self, stage: str, pipeline_affected: list[str], items_done: int, items_total: int) -> None:
        self._emit(BuildEvent(
            stage=stage, pipeline_affected=pipeline_affected, status="running",
            items_done=items_done, items_total=items_total,
            elapsed_ms=self._elapsed_ms(stage),
        ))

    def finish(
        self, stage: str, pipeline_affected: list[str], items_done: int, note: str = ""
    ) -> None:
        self._emit(BuildEvent(
            stage=stage, pipeline_affected=pipeline_affected, status="done",
            items_done=items_done, items_total=items_done,
            elapsed_ms=self._elapsed_ms(stage), note=note,
        ))

    def ready(self, pipeline_affected: list[str], note: str = "") -> None:
        """A pipeline has everything its build stages promised — flips its readiness badge."""
        self._emit(BuildEvent(stage="ready", pipeline_affected=pipeline_affected, status="ready", note=note))

    def error(self, stage: str, pipeline_affected: list[str], note: str) -> None:
        self._emit(BuildEvent(
            stage=stage, pipeline_affected=pipeline_affected, status="error",
            elapsed_ms=self._elapsed_ms(stage), note=note,
        ))

    def _elapsed_ms(self, stage: str) -> float:
        started = self._stage_started.get(stage)
        return (time.perf_counter() - started) * 1000.0 if started else 0.0

    def _emit(self, event: BuildEvent) -> None:
        if self._on_event is not None:
            self._on_event(event)
