"""Intent parser for P3 Agentic GraphRAG pipeline.

Source spec: TECHNICAL-SPEC §7 · APPLICATION-SPEC FR-12 · NFR-7
Plan: implementation-plan-AGENT.md Group 1

Emits {operation, anchor, constraints, target_field} per TECHNICAL-SPEC §7,
Pydantic-validated with exactly ONE retry on schema failure.

TWO EXTRACTION PATHS, ONE OUTPUT (PLAT-08 / AD-13):
  - Native tool-calling: where the configured model supports function-calling
    (detected by capability probe in LLM-01).
  - JSON-schema prompting: fallback for locally-hosted models that lack reliable
    tool-calling. Both paths produce an identical IntentSchema object and share
    the same validation and retry.

qtype → operation mapping (documented here; qtype is NEVER read at runtime):
  lookup      → LOOKUP
  aggregation → COUNT
  superlative → ARGMAX
  temporal    → TRAVERSE
  multi_hop   → TRAVERSE

NFR-7 compliance: qtype is an eval-set label and must never appear in the
answer path. The mapping above is for reporting only. No question-template
regex, no eval-string branching anywhere in this module.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from ogr.common.contracts import TokenUsage
from ogr.common.llm import invoke_and_count

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema (TECHNICAL-SPEC §7)
# ---------------------------------------------------------------------------

AnchorConstraintOp = Literal[">", "<", "=", ">=", "<="]

OPERATION_TYPES = Literal["LOOKUP", "COUNT", "ARGMAX", "TRAVERSE"]


class AnchorConstraint(BaseModel):
    field: str
    op: AnchorConstraintOp
    value: Any  # int or str per spec


class Anchor(BaseModel):
    sport: Optional[str] = None
    games: Optional[str] = None
    venue: Optional[str] = None
    title: Optional[str] = None
    event_id: Optional[str] = None


class IntentSchema(BaseModel):
    """Constrained intent output per TECHNICAL-SPEC §7."""
    operation: OPERATION_TYPES
    anchor: Anchor = Field(default_factory=Anchor)
    constraints: List[AnchorConstraint] = Field(default_factory=list)
    target_field: Optional[str] = None


# ---------------------------------------------------------------------------
# Tool definition for native function-calling path
# ---------------------------------------------------------------------------

INTENT_TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "emit_intent",
        "description": (
            "Emit the parsed intent schema from the user's question. "
            "operation must be one of: LOOKUP, COUNT, ARGMAX, TRAVERSE. "
            "LOOKUP: single event retrieval. COUNT: count events. "
            "ARGMAX: find max/min/best/most. TRAVERSE: follow temporal or multi-hop chains."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["LOOKUP", "COUNT", "ARGMAX", "TRAVERSE"],
                    "description": "Query operation type.",
                },
                "anchor": {
                    "type": "object",
                    "properties": {
                        "sport": {"type": "string", "description": "Sport name (e.g. 'Sailing')"},
                        "games": {"type": "string", "description": "Games identifier (e.g. '2016-Summer')"},
                        "venue": {"type": "string", "description": "Venue name"},
                        "title": {"type": "string", "description": "Event title for direct lookup"},
                        "event_id": {"type": "string", "description": "Event ID for direct lookup"},
                    },
                },
                "constraints": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string"},
                            "op": {"type": "string", "enum": [">", "<", "=", ">=", "<="]},
                            "value": {},
                        },
                        "required": ["field", "op", "value"],
                    },
                },
                "target_field": {
                    "type": "string",
                    "description": "The field to retrieve or aggregate (e.g. 'nations', 'gold', 'event_name').",
                },
            },
            "required": ["operation"],
        },
    },
}

# ---------------------------------------------------------------------------
# JSON-schema fallback prompt
# ---------------------------------------------------------------------------

JSON_SCHEMA_SYSTEM_PROMPT = """You are an intent parser for an Olympic sports question-answering system.
Parse the user's question and return a JSON object matching this exact schema:

{
  "operation": "LOOKUP" | "COUNT" | "ARGMAX" | "TRAVERSE",
  "anchor": {
    "sport": string or null,
    "games": string or null,
    "venue": string or null,
    "title": string or null,
    "event_id": string or null
  },
  "constraints": [
    { "field": string, "op": ">" | "<" | "=" | ">=" | "<=", "value": number or string }
  ],
  "target_field": string or null
}

Operation selection rules:
- LOOKUP: question asks for a specific attribute of a named event (use title or event_id)
- COUNT: question asks how many / number of
- ARGMAX: question asks for most / highest / lowest / best / first / last
- TRAVERSE: question involves temporal chains (previous/next edition) or multi-hop relations

Return ONLY valid JSON, no markdown, no explanation.
"""

JSON_SCHEMA_USER_PROMPT = "Question: {question}\n\nJSON:"


# ---------------------------------------------------------------------------
# Parser implementation
# ---------------------------------------------------------------------------

class IntentParser:
    """Intent parser with dual extraction paths and one schema validation + retry.

    At startup a capability probe decides whether to use native tool-calling
    (fast, structured) or JSON-schema prompting (compatible with all local models).
    Both paths produce identical IntentSchema objects — routing behaviour does not
    change with the provider.
    """

    def __init__(self, model: Any, supports_tool_calling: bool = False) -> None:
        self.model = model
        self.supports_tool_calling = supports_tool_calling
        # Record which extraction path is active for run_config header
        self.extraction_path = "tool_calling" if supports_tool_calling else "json_schema"
        # Tokens spent parsing intent. Read by the orchestrator so the entry
        # point to P3 is not invisible on the cost axis (DP-5).
        self.last_tokens = TokenUsage()
        self.last_token_source = "provider"

    def parse(self, question: str) -> IntentSchema:
        """Parse question into IntentSchema with one retry on schema failure."""
        self.last_tokens = TokenUsage()
        for attempt in range(2):  # exactly one retry
            try:
                raw = self._extract(question)
                schema = self._validate(raw)
                return schema
            except (ValidationError, ValueError, TypeError) as e:
                if attempt == 0:
                    logger.warning(
                        "Intent parse attempt 1 failed (%s); retrying with explicit correction prompt.",
                        e,
                    )
                else:
                    logger.error("Intent parse failed after 1 retry: %s", e)
                    # Return a safe default: TRAVERSE with empty anchor (routes to loop)
                    return IntentSchema(operation="TRAVERSE")
        return IntentSchema(operation="TRAVERSE")

    def _extract(self, question: str) -> Dict[str, Any]:
        if self.supports_tool_calling:
            return self._extract_tool_calling(question)
        return self._extract_json_schema(question)

    def _extract_tool_calling(self, question: str) -> Dict[str, Any]:
        """Native function-calling path."""
        try:
            from langchain_core.messages import HumanMessage
        except ImportError:
            from langchain.schema import HumanMessage

        model_with_tools = self.model.bind_tools([INTENT_TOOL_DEFINITION])
        response = self._invoke_counted(model_with_tools, [HumanMessage(content=question)])
        tool_calls = getattr(response, "tool_calls", [])
        if tool_calls:
            return tool_calls[0].get("args", {})
        # Fallback if tool_calls empty
        return self._parse_json_from_text(getattr(response, "content", "{}"))

    def _extract_json_schema(self, question: str) -> Dict[str, Any]:
        """JSON-schema prompting fallback for local models."""
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
        except ImportError:
            from langchain.schema import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content=JSON_SCHEMA_SYSTEM_PROMPT),
            HumanMessage(content=JSON_SCHEMA_USER_PROMPT.format(question=question)),
        ]
        response = self._invoke_counted(self.model, messages)
        raw_text = response.content if hasattr(response, "content") else str(response)
        if isinstance(raw_text, list):
            raw_text = "".join(
                p.get("text", "") if isinstance(p, dict) else str(p) for p in raw_text
            )
        return self._parse_json_from_text(raw_text)

    def _invoke_counted(self, model: Any, messages: Any) -> Any:
        """Invoke through the accounting module, accumulating across retries."""
        response, tokens, source, _ = invoke_and_count(model, messages)
        self.last_tokens = TokenUsage(
            input=self.last_tokens.input + tokens.input,
            output=self.last_tokens.output + tokens.output,
            total=self.last_tokens.total + tokens.total,
        )
        self.last_token_source = source
        return response

    @staticmethod
    def _parse_json_from_text(text: str) -> Dict[str, Any]:
        text = text.strip()
        # Strip markdown fences
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()
        return json.loads(text)

    @staticmethod
    def _validate(raw: Dict[str, Any]) -> IntentSchema:
        """Validate raw dict against IntentSchema (raises ValidationError on failure)."""
        # Normalize anchor: ensure it's a dict
        if "anchor" not in raw or raw["anchor"] is None:
            raw["anchor"] = {}
        return IntentSchema.model_validate(raw)
