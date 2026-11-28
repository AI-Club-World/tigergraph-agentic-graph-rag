"""Prompt-based JSON tool calling for models without native tool-calling support."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from ogr.common.config import RunConfig
from ogr.r2.graph_backend import R2Graph
from ogr.r2.tools import FINISH_SPEC, TOOL_SPECS, ToolContext, run_tool
from ogr.r2.trace import TraceRecorder

__all__ = [
    "TOOL_MODE_ENV",
    "RETRY_MESSAGE",
    "FORCE_TEXT_MESSAGE",
    "is_text_mode",
    "render_tools_prompt",
    "parse_tool_call",
    "run_text_loop",
]

TOOL_MODE_ENV = "R2_TOOL_MODE"

RETRY_MESSAGE = (
    'Invalid response. Reply with exactly one JSON object: {"tool": "<name>", "args": {...}} '
    'or {"tool": "finish", "args": {"status": "...", "answer": ..., "explanation": "...", '
    '"citations": [...]}}.'
)

FORCE_TEXT_MESSAGE = (
    "The tool budget is used up. Reply now with a single JSON finish call: "
    '{"tool": "finish", "args": {"status": "...", "answer": ..., "explanation": "...", '
    '"citations": [...]}}.'
)


def is_text_mode() -> bool:
    return os.environ.get(TOOL_MODE_ENV, "native").strip().lower() == "text"


def _format_param(name: str, spec: dict[str, Any], required: set[str]) -> str:
    kind = spec.get("type", "any")
    if kind == "array" and isinstance(spec.get("items"), dict):
        kind = f"array[{spec['items'].get('type', 'any')}]"
    if "enum" in spec:
        vals = ", ".join(json.dumps(v) for v in spec["enum"])
        kind = f"{kind} enum[{vals}]"
    req = "required" if name in required else "optional"
    desc = f" - {spec['description']}" if spec.get("description") else ""
    return f"  - {name} ({kind}, {req}){desc}"


def render_tools_prompt(
    tool_specs: list[dict[str, Any]] = TOOL_SPECS,
    finish_spec: dict[str, Any] = FINISH_SPEC,
) -> str:
    """Render tool schemas and JSON-call instructions for text-only models."""
    lines = [
        "Available tools (reply with exactly one JSON object per turn, no other text):",
        '  {"tool": "<name>", "args": {...}}',
        '  {"tool": "finish", "args": {"status": "...", "answer": ..., "explanation": "...", '
        '"citations": [...]}}',
        "",
    ]
    for raw in [*tool_specs, finish_spec]:
        fn = raw["function"] if "function" in raw else raw
        params = fn.get("parameters") or {}
        props = params.get("properties") or {}
        required = set(params.get("required") or [])
        lines.append(f"- {fn['name']}: {fn.get('description', '')}")
        for pname, pspec in props.items():
            lines.append(_format_param(pname, pspec, required))
    return "\n".join(lines)


def parse_tool_call(text: str) -> tuple[str, dict[str, Any]] | None:
    """Extract the first valid {"tool": ..., "args": {...}} JSON object from text."""
    if not text:
        return None
    decoder = json.JSONDecoder()
    pos = 0
    while True:
        idx = text.find("{", pos)
        if idx == -1:
            return None
        try:
            obj, _ = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            pos = idx + 1
            continue
        if isinstance(obj, dict):
            tool = obj.get("tool")
            args = obj.get("args")
            if isinstance(tool, str) and tool.strip() and (args is None or isinstance(args, dict)):
                return tool.strip(), ({} if args is None else args)
        pos = idx + 1


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return str(content or "")


def run_text_loop(
    question: str,
    graph: R2Graph,
    model: Any,
    config: RunConfig,
    trace: TraceRecorder,
    ctx: ToolContext,
    budget: int,
    call_fn: Callable[[Any, list[Any], TraceRecorder, RunConfig, str], Any],
    system_prompt: str,
) -> dict[str, Any]:
    """Run the question-answering loop using prompt-based JSON tool calls."""
    messages: list[Any] = [
        SystemMessage(content=f"{system_prompt}\n\n{render_tools_prompt()}"),
        HumanMessage(content=question),
    ]
    used = 0
    llm_calls = 0
    invalid_streak = 0
    finish: dict[str, Any] | None = None

    while finish is None and used < budget:
        label = "plan" if llm_calls == 0 else "llm_step"
        llm_calls += 1
        response = call_fn(model, messages, trace, config, label)
        text = _extract_text(getattr(response, "content", ""))
        parsed = parse_tool_call(text)
        if parsed is None:
            messages.append(response)
            if invalid_streak == 0:
                invalid_streak = 1
                messages.append(HumanMessage(content=RETRY_MESSAGE))
                continue
            break
        tool, args = parsed
        if tool == "finish":
            finish = args
            break
        invalid_streak = 0
        used += 1
        out = run_tool(graph, tool, args, trace, ctx)
        messages.append(response)
        messages.append(HumanMessage(content=f"Tool result ({tool}):\n{out}"))

    if finish is None:
        response = call_fn(
            model,
            [*messages, HumanMessage(content=FORCE_TEXT_MESSAGE)],
            trace,
            config,
            "llm_answer",
        )
        text = _extract_text(getattr(response, "content", ""))
        parsed = parse_tool_call(text)
        if parsed is not None and parsed[0] == "finish":
            finish = parsed[1]
        else:
            finish = {
                "status": "partial",
                "answer": text.strip(),
                "explanation": "The model did not call finish; its last text is returned.",
            }
    return finish
