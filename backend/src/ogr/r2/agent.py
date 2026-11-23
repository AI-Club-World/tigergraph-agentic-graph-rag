"""The Round-2 answering agent (SOLUTION-DESIGN §4): a native tool-calling loop.

One question: system prompt + question -> model -> tool calls executed (each recorded in the trace
as it runs) -> tool results -> ... until the model calls `finish` or the tool budget is spent, then a
forced `finish`. Every model call is an `llm` trace step with provider-reported tokens (estimates are
marked in `note`). Deterministic guards shape the final record; a failure on one question yields a
valid record and never stops the run.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from ogr.common.config import RunConfig, get_default_config
from ogr.common.llm import invoke_and_count
from ogr.r2.graph_backend import R2Graph
from ogr.r2.output import STATUSES, AnswerRecord
from ogr.r2.querylog import QueryLog
from ogr.r2.tools import FINISH_SPEC, TOOL_SPECS, ToolContext, run_tool
from ogr.r2.trace import TraceRecorder

logger = logging.getLogger(__name__)

__all__ = ["SYSTEM_PROMPT", "PROMPT_VERSION", "answer_question", "default_max_steps"]

PROMPT_VERSION = "r2-agent-v1"

SYSTEM_PROMPT = "\n".join([
    "Answer the question using only what the tools return from the corpus. Plan briefly, call tools "
    "(several at once when independent), then call finish.",
    "Rules:",
    "- Lists must be complete: every item asked for, none extra. Give numbers exactly as stated.",
    "- If a question names several years or items, check every one of them.",
    "- Statuses: answered = fully supported; partial = some requested parts are not in the corpus (say "
    "which); not_in_corpus = nothing in the corpus answers it. Never guess or use outside knowledge.",
    "- Unknown is not negative: a missing record does not prove something did not happen.",
    "- Sources differ in authority: official > operational > secondary > unreliable. A later publication "
    "does not override a more authoritative one. Provisional displays are not final results; drafts are "
    "not final. Separate when something took effect from when it was published or happened. Registered "
    "is not the same as competed. Say what was provisional, superseded or unconfirmed.",
    "- For lists and records prefer a JSON answer; otherwise short plain text.",
    "- finish: status, answer, short explanation, citations = doc_ids that support each fact.",
])

FORCE_MESSAGE = "The tool budget is used up. Call finish now with the best answer the evidence supports."


def default_max_steps() -> int:
    try:
        return max(1, int(os.environ.get("R2_MAX_STEPS") or 8))
    except ValueError:
        return 8


def _bind(model: Any, specs: list[dict[str, Any]], choice: str | None = None) -> Any:
    if choice:
        try:
            return model.bind_tools(specs, tool_choice=choice)
        except Exception:
            logger.debug("tool_choice not supported; falling back to an instruction only")
    return model.bind_tools(specs)


def _call(bound: Any, messages: list, trace: TraceRecorder, config: RunConfig, label: str) -> Any:
    """One model call as one llm trace step. The tokens are the provider's; only when it reports
    none is the count estimated, and the step says so."""
    response, tokens, source, latency_ms = invoke_and_count(
        bound, messages, max_retries=config.llm_max_retries, backoff_base_s=config.llm_backoff_base_s)
    note = None if source == "provider" else f"tokens {source}: provider reported none"
    trace.llm(label, tokens.input, tokens.output, int(round(latency_ms)), note=note)
    return response


def _parse_answer(answer: Any) -> Any:
    if isinstance(answer, str):
        text = answer.strip()
        if text[:1] in ("{", "["):
            try:
                return json.loads(text)
            except ValueError:
                return answer
    return answer


def _empty(value: Any) -> bool:
    return value is None or (isinstance(value, str | list | dict) and not value) or \
        (isinstance(value, str) and not value.strip())


def _finalize(qid: str, args: dict[str, Any], ctx: ToolContext, trace: TraceRecorder,
              started: float) -> AnswerRecord:
    status = str(args.get("status") or "").strip().lower()
    explanation = str(args.get("explanation") or "")
    if status not in STATUSES:
        status = "partial"
    answer = _parse_answer(args.get("answer"))
    if status == "not_in_corpus":
        answer = None
    elif _empty(answer):
        status, answer = "not_in_corpus", None
        explanation = (explanation + " (no answer was given)").strip()
    raw = args.get("citations") or []
    raw = [raw] if isinstance(raw, str) else raw
    seen, citations = set(ctx.seen_doc_ids), []
    for c in raw if isinstance(raw, list) else []:
        if isinstance(c, str) and c in seen and c not in citations:
            citations.append(c)
    totals = trace.totals()
    return AnswerRecord(qid=qid, status=status, answer=answer, explanation=explanation,
                        citations=citations, input_tokens=totals["input_tokens"],
                        output_tokens=totals["output_tokens"],
                        latency_ms=int(round((time.perf_counter() - started) * 1000)), trace=trace.to_list())


def _failure(qid: str, error: Exception, trace: TraceRecorder, started: float) -> AnswerRecord:
    message = f"{type(error).__name__}: {error}"[:400]
    logger.warning("question %s failed: %s", qid, message)
    if not trace.to_list():
        trace.local("error", 0, note=message)
    totals = trace.totals()
    return AnswerRecord(qid=qid, status="partial", answer=None,
                        explanation=f"The run failed on this question ({message}).",
                        citations=[], input_tokens=totals["input_tokens"],
                        output_tokens=totals["output_tokens"],
                        latency_ms=int(round((time.perf_counter() - started) * 1000)), trace=trace.to_list(),
                        error=message)


def _finish_args(response: Any) -> dict[str, Any] | None:
    for call in getattr(response, "tool_calls", None) or []:
        if call.get("name") == "finish":
            args = call.get("args")
            return args if isinstance(args, dict) else {}
    return None


def answer_question(qid: str, question: str, graph: R2Graph, model: Any, config: RunConfig | None = None,
                    *, querylog: QueryLog | None = None, max_steps: int | None = None) -> AnswerRecord:
    """Answer one question. Always returns a record; never raises."""
    config = config or get_default_config()
    budget = max_steps if max_steps is not None else default_max_steps()
    started = time.perf_counter()
    trace = TraceRecorder(qid, querylog)
    ctx = ToolContext()
    try:
        messages: list[Any] = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=question)]
        bound = _bind(model, [*TOOL_SPECS, {"type": "function", "function": FINISH_SPEC}])
        used = 0
        finish: dict[str, Any] | None = None
        while finish is None and used < budget:
            response = _call(bound, messages, trace, config, "plan" if used == 0 else "llm_step")
            finish = _finish_args(response)
            calls = getattr(response, "tool_calls", None) or []
            if finish is not None or not calls:
                break
            messages.append(response)
            for call in calls:
                if used >= budget:
                    out = json.dumps({"error": "tool budget used up; call finish"})
                else:
                    used += 1
                    out = run_tool(graph, call.get("name", ""), call.get("args"), trace, ctx)
                messages.append(ToolMessage(content=out, tool_call_id=call.get("id") or call.get("name", "")))
        if finish is None:
            forced = _bind(model, [{"type": "function", "function": FINISH_SPEC}], "finish")
            response = _call(forced, [*messages, HumanMessage(content=FORCE_MESSAGE)], trace, config,
                             "llm_answer")
            finish = _finish_args(response)
            if finish is None:
                text = str(getattr(response, "content", "") or "").strip()
                finish = {"status": "partial", "answer": text,
                          "explanation": "The model did not call finish; its last text is returned."}
        return _finalize(qid, finish, ctx, trace, started)
    except Exception as e:  # fault isolation: one bad question must not stop the run
        return _failure(qid, e, trace, started)
