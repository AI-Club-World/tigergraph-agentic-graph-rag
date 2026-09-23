"""Shared contracts, data models, and prompt templates for OGR pipelines."""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, Field


class Citation(BaseModel):
    """Citation schema per TECHNICAL-SPEC §6.2.
    source_id is the parent doc_id (wikidata QID) used for scoring.
    chunk_id is the chunk identifier retained for display.
    """
    source_id: str
    chunk_id: str | None = None
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
    citations: list[Citation] = Field(default_factory=list)
    chunks_returned: int = 0
    citations_count: int = 0
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    # 'estimated' exists so a character-heuristic count is never presented as a
    # tokenizer count: §11 forbids estimation, PLAT-08 requires the figure be
    # labelled rather than fabricated or dropped.
    token_source: Literal["provider", "local_tokenizer", "estimated"] = "provider"
    latency_ms: float = 0.0
    trace: list[TraceStep] | None = None
    strategy_changed: bool | None = None
    stop_reason: str | None = None
    status: Literal["done", "error"] = "done"
    error_detail: str | None = None


class Verdict(BaseModel):
    """Cost/accuracy verdict per TECHNICAL-SPEC §6.1.

    Accuracy deltas are the literal string "n/a" where no ground truth exists
    (FR-9: the field is displayed as N/A rather than omitted).
    """
    token_multiplier_vs_rag: float = 0.0
    token_multiplier_vs_graphrag: float = 0.0
    accuracy_delta_vs_rag: float | Literal["n/a"] = "n/a"
    accuracy_delta_vs_graphrag: float | Literal["n/a"] = "n/a"
    summary_line: str = ""


class QueryLevelRecord(BaseModel):
    """One query across all three pipelines, per TECHNICAL-SPEC §6.1."""
    query_id: str
    query_text: str
    qtype: str | None = None
    timestamp: str = ""
    pipelines: dict[str, PipelineRecord] = Field(default_factory=dict)
    verdict: Verdict = Field(default_factory=Verdict)


class PipelineScores(BaseModel):
    """Deterministic scores for one pipeline on one question (TECHNICAL-SPEC §9).

    Completeness is an explicit alias of Recall (DP-2 Option A): |retrieved n
    gold| / |gold| *is* recall. It is retained as its own field only because
    the guidebook names the column.
    """
    em: float = 0.0
    f1: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    completeness: float = 0.0


class BatchRecord(BaseModel):
    """One evaluation question across all three pipelines, per TECHNICAL-SPEC §6.4."""
    run_id: str
    question_id: str
    question_text: str
    qtype: str | None = None
    ground_truth: list[str] = Field(default_factory=list)
    gold_doc_ids: list[str] = Field(default_factory=list)
    record: QueryLevelRecord


class Question(BaseModel):
    """An evaluation question, using the data files' field names verbatim.

    Both eval_public.jsonl and eval_hidden.jsonl use qid / question / qtype
    (BUILD-PLAN §10 — the F-14 adapter was deleted). `answer` is a list of
    gold variants scored max-over-variants, and is empty for the hidden set.
    """
    qid: str
    question: str
    qtype: Literal["lookup", "multi_hop", "temporal", "aggregation", "superlative"] | None = None
    answer: list[str] = Field(default_factory=list)
    gold_doc_ids: list[str] = Field(default_factory=list)


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


def parse_answer_contract_json(raw_text: str) -> dict[str, str]:
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
    match = re.search(
        r'\{\s*"answer"\s*:\s*"(.*?)"\s*,\s*"explanation"\s*:\s*"(.*?)"\s*\}',
        cleaned,
        re.DOTALL,
    )
    if match:
        return {"answer": match.group(1).strip(), "explanation": match.group(2).strip()}

    # A reply cut off mid-JSON (e.g. an output-token limit) still usually
    # carries a complete "answer" field; recover it rather than scoring the
    # raw JSON text as the answer.
    partial = re.search(r'"answer"\s*:\s*"((?:[^"\\]|\\.)*)"', cleaned)
    if partial:
        try:
            answer = json.loads(f'"{partial.group(1)}"')
        except ValueError:
            answer = partial.group(1)
        return {"answer": answer.strip(), "explanation": cleaned}

    return {"answer": cleaned, "explanation": cleaned}


# Keys that identify a row rather than describe it; the doc id is shown in
# the [Source: ...] header instead.
_CONTEXT_SKIP = frozenset({"doc_id", "chunk_id", "source", "score", "seq", "vtype", "attributes", "v_id"})


def format_evidence_item(item: dict) -> str:
    """One evidence record as context text. Prose chunks keep their text;
    structured graph rows (Q1-Q4) are rendered as every non-empty field, so
    the attribute the question asks about actually reaches the model."""
    if item.get("text"):
        return str(item["text"]).strip()
    fields = []
    for key, value in item.items():
        if key in _CONTEXT_SKIP or value is None or value == "" or isinstance(value, (dict, list)):
            continue
        if isinstance(value, str):
            value = value.strip().rstrip(";").strip()
        fields.append(f"{key}: {value}")
    return "; ".join(fields)


def format_evidence_context(evidence: list[dict], empty: str = "No relevant graph results found.") -> str:
    """Shared by P2 and P3 so graph evidence is rendered identically."""
    if not evidence:
        return empty
    return "\n\n".join(
        f"[{i}] [Source: {e.get('doc_id') or e.get('event_id') or 'unknown'}]\n{format_evidence_item(e)}"
        for i, e in enumerate(evidence, 1)
    )
