"""Live-run regressions: graph rows must reach the model with their fields,
a lookup must keep only the asked Games, and a truncated reply must still
yield its answer."""

from __future__ import annotations

from ogr.common.config import RunConfig
from ogr.common.contracts import format_evidence_context, parse_answer_contract_json
from ogr.pipelines.p3_agentic.agents.entity_linking import narrow_to_games

ROWS = [
    {"event_id": "sailing-2012-Summer-women-s-rs-x", "event_name": "Women's RS:X", "doc_id": "Q1",
     "nations": 27, "date_year": 2012, "gold": "Marina Alabau; ", "win_value": ""},
    {"event_id": "sailing-2016-Summer-women-s-rs-x", "event_name": "Women's RS:X", "doc_id": "Q2",
     "nations": 26, "date_year": 2016, "gold": "Charline Picon; ", "win_value": "64 points"},
]


def test_structured_rows_render_every_non_empty_field():
    context = format_evidence_context(ROWS[1:])
    assert "[Source: Q2]" in context
    assert "nations: 26" in context and "gold: Charline Picon" in context
    assert "win_value: 64 points" in context
    assert "doc_id" not in context  # shown in the header instead


def test_prose_chunks_keep_their_text():
    assert "Sailing text" in format_evidence_context([{"doc_id": "Q9", "text": "Sailing text"}])


def test_lookup_keeps_only_the_resolved_games():
    assert [r["nations"] for r in narrow_to_games(ROWS, "2016-Summer")] == [26]


def test_unmatched_games_keeps_all_rows():
    assert len(narrow_to_games(ROWS, "1996-Summer")) == 2
    assert len(narrow_to_games(ROWS, None)) == 2


def test_truncated_json_still_yields_the_answer():
    parsed = parse_answer_contract_json('{\n  "answer": "26",\n  "explanation": "The context lists')
    assert parsed["answer"] == "26"


def test_gemini_thinking_level_reaches_the_client():
    from ogr.common import llm

    model = llm._build_chat_model(
        RunConfig(llm_provider="google", llm_model="m", llm_api_key="k", llm_base_url=None, llm_thinking="minimal")
    )
    assert model.thinking_config == {"thinking_level": "minimal"}
