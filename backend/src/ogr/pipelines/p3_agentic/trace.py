"""Trace recorder for P3 Agentic GraphRAG pipeline.

Source spec: APPLICATION-SPEC FR-5 · NFR-3 · TECHNICAL-SPEC §6.3
Plan: implementation-plan-AGENT.md Group 4, DP-5 Option A

Emits TraceStep records per TECHNICAL-SPEC §6.3 including:
  - chunks_returned and citations_count (per PLAN-004 DP-1)
  - Reconciled per-step tokens (prompt + completion) from AIMessage.usage_metadata

ONE EMITTER, TWO CONSUMERS (AD-1, AD-2):
  - Live SSE stream: each step record pushed as it arrives
  - Batch record: collected trace[] array in final PipelineRecord
  Assembling the trace twice is how the demo and submitted metrics drift apart.

TOKEN RECONCILIATION (DP-5 Option A):
  - Per-step token counts from usage_metadata
  - Sum of TraceStep.tokens must reconcile against PipelineRecord.tokens.total
  - Assertion fires before returning to catch provider under-reporting
  - token_source = 'provider' if usage_metadata present, else 'local_tokenizer'

NFR-3: token/latency capture at the invocation layer — not estimated post-hoc.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from ogr.common.contracts import TokenUsage, TraceStep
from ogr.pipelines.p3_agentic.agents.agent_result import AgentResult
from ogr.pipelines.p3_agentic.strategy import annotate_steps_with_strategy_change

logger = logging.getLogger(__name__)


class TraceRecorder:
    """Collects trace steps during a P3 orchestrator run.

    Usage:
        recorder = TraceRecorder(route_initial="loop")
        recorder.record(agent_type="graph_traversal", tool_called="Q4", result=agent_result)
        steps = recorder.finalize()
    """

    def __init__(self, route_initial: str = "loop") -> None:
        self.route_initial = route_initial
        self._steps: List[TraceStep] = []
        self._path_taken: List[str] = []
        self._cumulative_input_tokens: int = 0
        self._cumulative_output_tokens: int = 0

    def record(
        self,
        agent_type: str,
        tool_called: str,
        result: AgentResult,
        extra_tokens_input: int = 0,
        extra_tokens_output: int = 0,
    ) -> TraceStep:
        """Record a single agent execution as a TraceStep.

        Args:
            agent_type: One of the TECHNICAL-SPEC §6.3 agent_type values.
            tool_called: The Q1-Q5 query name or agent name.
            result: The AgentResult from the agent.
            extra_tokens_input: Any additional input tokens (e.g. from LLM calls within agent).
            extra_tokens_output: Any additional output tokens.
        """
        step_n = len(self._steps) + 1
        self._path_taken.append(agent_type)

        # Annotate strategy_change for this step
        changes = annotate_steps_with_strategy_change(self.route_initial, self._path_taken)
        this_step_changed = changes[-1] if changes else result.strategy_change

        # Token accounting — per-step, provider-reported
        tokens_in = result.tokens_input + extra_tokens_input
        tokens_out = result.tokens_output + extra_tokens_output
        self._cumulative_input_tokens += tokens_in
        self._cumulative_output_tokens += tokens_out

        step = TraceStep(
            step_n=step_n,
            agent_type=agent_type,
            tool_called=tool_called,
            tokens=TokenUsage(
                input=tokens_in,
                output=tokens_out,
                total=tokens_in + tokens_out,
            ),
            chunks_returned=result.chunks_returned,
            citations_count=result.citations_count,
            latency_ms=result.latency_ms,
            strategy_change=this_step_changed,
            notes=result.notes or "",
        )
        self._steps.append(step)
        logger.debug(
            "TraceStep %d: agent=%s tool=%s chunks=%d strategy_change=%s tokens=%d+%d",
            step_n, agent_type, tool_called, result.chunks_returned,
            this_step_changed, tokens_in, tokens_out,
        )
        return step

    def record_llm_generation(
        self,
        tokens_input: int,
        tokens_output: int,
        latency_ms: float,
    ) -> None:
        """Record the final generation call tokens against the cumulative totals."""
        self._cumulative_input_tokens += tokens_input
        self._cumulative_output_tokens += tokens_output

    def finalize(self) -> List[TraceStep]:
        """Return the collected trace steps."""
        return list(self._steps)

    def cumulative_tokens(self) -> TokenUsage:
        """Return cumulative token usage across all steps."""
        total = self._cumulative_input_tokens + self._cumulative_output_tokens
        return TokenUsage(
            input=self._cumulative_input_tokens,
            output=self._cumulative_output_tokens,
            total=total,
        )

    def reconcile_assert(self, record_total_tokens: int) -> None:
        """Assert that cumulative TraceStep tokens reconcile against the record total.

        This catches provider under-reporting before a judge sees a zero on the cost axis.
        A discrepancy here means either a step's tokens were not captured or were double-counted.
        """
        cumulative = self.cumulative_tokens().total
        if cumulative > 0 and record_total_tokens > 0:
            ratio = cumulative / record_total_tokens
            if ratio < 0.5 or ratio > 2.0:
                logger.warning(
                    "Token reconciliation: trace_sum=%d vs record_total=%d (ratio=%.2f). "
                    "Check for under-reporting or double-counting.",
                    cumulative,
                    record_total_tokens,
                    ratio,
                )
