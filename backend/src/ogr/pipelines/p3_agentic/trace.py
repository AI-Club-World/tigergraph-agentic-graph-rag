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
from collections.abc import Callable

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

    def __init__(
        self,
        route_initial: str = "loop",
        on_step: Callable[[TraceStep], None] | None = None,
    ) -> None:
        self.route_initial = route_initial
        self._steps: list[TraceStep] = []
        self._path_taken: list[str] = []
        self._cumulative_input_tokens: int = 0
        self._cumulative_output_tokens: int = 0
        # One emitter, two consumers (AD-1, AD-2): the collected trace array
        # below, and this subscriber for a live stream. Assembling the trace
        # twice is how the demo and the submitted metrics drift apart.
        self._on_step = on_step

    def _emit(self, step: TraceStep) -> None:
        self._steps.append(step)
        if self._on_step is not None:
            self._on_step(step)

    def record(
        self,
        agent_type: str,
        tool_called: str,
        result: AgentResult,
        path_name: str | None = None,
        extra_tokens_input: int = 0,
        extra_tokens_output: int = 0,
    ) -> TraceStep:
        """Record a single agent execution as a TraceStep.

        Args:
            agent_type: One of the TECHNICAL-SPEC §6.3 agent_type values.
            tool_called: The Q1-Q5 query name or agent name.
            result: The AgentResult from the agent.
            path_name: The tool name as it appears in the orchestrator's
                `path_taken` ("lookup", "traversal", …). Supplied for tool
                steps only. Route-based deviation is judged against this
                vocabulary, so bookkeeping steps — intent parse, evidence
                evaluation, generation — pass None and are never flagged as
                deviations merely for not being tools.
            extra_tokens_input: Any additional input tokens (e.g. from LLM calls within agent).
            extra_tokens_output: Any additional output tokens.
        """
        step_n = len(self._steps) + 1

        # A step deviates if the route-based detector says so, OR if the agent
        # itself declares it. The fallback agents (Q5 expansion, HAS_CHUNK
        # prose) always declare one: DP-2 specifies that each fallback sets
        # strategy_change, and they fire precisely because the evidence check
        # failed — the "re-query after evidence check fails" case in ARCH §3.
        route_changed = False
        if path_name is not None:
            self._path_taken.append(path_name)
            changes = annotate_steps_with_strategy_change(self.route_initial, self._path_taken)
            route_changed = changes[-1] if changes else False
        this_step_changed = bool(route_changed or result.strategy_change)

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
        self._emit(step)
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
    ) -> TraceStep:
        """Record the final generation call as a TraceStep of its own.

        It must be a step, not a loose addition to the totals: BUILD-PLAN §7
        requires Sum(TraceStep.tokens) == record total, and generation is
        usually the largest single cost in the run.
        """
        step_n = len(self._steps) + 1
        self._cumulative_input_tokens += tokens_input
        self._cumulative_output_tokens += tokens_output

        step = TraceStep(
            step_n=step_n,
            agent_type="answer_generation",
            tool_called="generate",
            tokens=TokenUsage(
                input=tokens_input,
                output=tokens_output,
                total=tokens_input + tokens_output,
            ),
            chunks_returned=0,
            citations_count=0,
            latency_ms=latency_ms,
            strategy_change=False,
            notes="Final answer generation (CORE-02 shared answer contract)",
        )
        self._emit(step)
        return step

    def finalize(self) -> list[TraceStep]:
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

    def trace_token_sum(self) -> int:
        """Sum of tokens across the emitted TraceSteps."""
        return sum(step.tokens.total for step in self._steps)

    def reconcile_assert(self, record_total_tokens: int) -> bool:
        """Check Sum(TraceStep.tokens) == record total (DP-5, BUILD-PLAN §7).

        This must compare the *step sum* against the record total. Comparing
        the recorder's own cumulative counter against a total derived from that
        same counter is a tautology, and a tautology cannot catch the failure
        this guard exists for: a silently-zero usage field reading as
        "the agentic path is free".

        Returns True when the two agree.
        """
        step_sum = self.trace_token_sum()
        if step_sum == record_total_tokens:
            return True
        logger.warning(
            "Token reconciliation FAILED: sum(TraceStep.tokens)=%d vs record_total=%d "
            "(difference %+d). A step's tokens were not captured or were double-counted.",
            step_sum,
            record_total_tokens,
            step_sum - record_total_tokens,
        )
        return False
