"""Shared contracts, data models, and prompt templates for OGR pipelines."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class Citation(BaseModel):
    """Citation schema per TECHNICAL-SPEC §6.2.
    source_id is the parent doc_id (wikidata QID) used for scoring.
    chunk_id is the chunk identifier retained for display.
    """
    source_id: str
    chunk_id: Optional[str] = None
    ref_type: Literal["chunk", "entity", "relationship"] = "chunk"


class TokenUsage(BaseModel):
    """Token accounting per TECHNICAL-SPEC §6.2."""
    input: int = 0
    output: int = 0
    total: int = 0


class TraceStep(BaseModel):
    """TraceStep schema per TECHNICAL-SPEC §6.3 (agentic_graphrag only)."""
    step_n: int
    agent_type: str
    tool_called: str
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    chunks_returned: int = 0
    citations_count: int = 0
    latency_ms: float = 0.0
    strategy_change: bool = False
    notes: str = ""


class PipelineRecord(BaseModel):
    """Pipeline output record conforming verbatim to TECHNICAL-SPEC §6.2."""
    pipeline: Literal["rag", "graphrag", "agentic_graphrag"]
    answer: str
    explanation: str
    citations: List[Citation] = Field(default_factory=list)
    chunks_returned: int = 0
    citations_count: int = 0
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    token_source: Literal["provider", "local_tokenizer"] = "provider"
    latency_ms: float = 0.0
    trace: Optional[List[TraceStep]] = None
    strategy_changed: Optional[bool] = None
    stop_reason: Optional[str] = None
    status: Literal["done", "error"] = "done"
    error_detail: Optional[str] = None


# CORE-02: Shared answer contract prompt template
# Used identically across P1, P2, and P3 apart from retrieved context
SHARED_SYSTEM_PROMPT = """You are a precise question-answering assistant.
Answer the user's question using strictly the provided context.
Output your response as a valid JSON object with exactly two keys:
  "answer": the shortest possible span answering the question (e.g. "5", "Men's marathon", "26").
  "explanation": concise prose explaining the answer with citations referencing the source context.
Do not output any markdown code fences or other text outside the JSON object.
"""

SHARED_USER_PROMPT = """Context:
{context}

Question: {question}

JSON:"""


def parse_answer_contract_json(raw_text: str) -> Dict[str, str]:
    """Parses model output conforming to the CORE-02 answer contract.
    Extracts 'answer' and 'explanation'.
    """
    cleaned = raw_text.strip()
    # Strip markdown code fences if present
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            answer = str(data.get("answer", "")).strip()
            explanation = str(data.get("explanation", "")).strip()
            return {"answer": answer, "explanation": explanation}
    except Exception:
        pass

    # Fallback heuristic if JSON parsing fails
    match = re.search(r'\{\s*"answer"\s*:\s*"(.*?)"\s*,\s*"explanation"\s*:\s*"(.*?)"\s*\}', cleaned, re.DOTALL)
    if match:
        return {"answer": match.group(1).strip(), "explanation": match.group(2).strip()}

    return {"answer": cleaned, "explanation": cleaned}
