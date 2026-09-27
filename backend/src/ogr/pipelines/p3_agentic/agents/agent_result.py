"""Shared AgentResult contract for all P3 specialised agents.

Every tool agent returns an AgentResult so the orchestrator can
treat them uniformly when building TraceSteps and citations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentResult:
    """Uniform result type returned by every P3 tool agent.

    Each agent returns evidence, chunks_returned, citations_count,
    tokens and latency — all fields needed for a TraceStep.
    """
    evidence: list[dict[str, Any]] = field(default_factory=list)
    chunks_returned: int = 0
    citations_count: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    latency_ms: float = 0.0
    strategy_change: bool = False
    notes: str = ""
    error: str | None = None
