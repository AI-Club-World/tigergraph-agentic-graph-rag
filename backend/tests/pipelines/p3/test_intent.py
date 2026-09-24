"""Tests for Group 1: Intent parser.

Verification Plan Group 1:
- test_intent_schema_validates
- test_retry_once_on_invalid_schema
- test_no_qtype_read_at_runtime
"""

from __future__ import annotations

import json

import ast
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ogr.pipelines.p3_agentic.intent import (
    Anchor,
    AnchorConstraint,
    IntentParser,
    IntentSchema,
)


def _make_mock_model(response_json: str) -> MagicMock:
    model = MagicMock()
    resp = MagicMock()
    resp.content = response_json
    resp.tool_calls = []
    model.invoke.return_value = resp
    return model


def _make_model_with_tool_call(args: dict) -> MagicMock:
    model = MagicMock()
    resp = MagicMock()
    resp.content = ""
    resp.tool_calls = [{"args": args}]
    bound = MagicMock()
    bound.invoke.return_value = resp
    model.bind_tools.return_value = bound
    return model


class TestIntentSchemaValidates:
    def test_valid_lookup_schema(self):
        """test_intent_schema_validates: Valid JSON produces correct IntentSchema."""
        model = _make_mock_model(
            '{"operation": "LOOKUP", "anchor": {"title": "Athletics at the 2016 Summer Olympics – Men\'s marathon"}, '
            '"constraints": [], "target_field": "nations"}'
        )
        parser = IntentParser(model, supports_tool_calling=False)
        result = parser.parse("How many nations competed in the men's marathon at the 2016 Olympics?")
        assert result.operation == "LOOKUP"
        assert result.anchor.title == "Athletics at the 2016 Summer Olympics – Men's marathon"
        assert result.target_field == "nations"
        assert result.constraints == []

    def test_valid_count_schema(self):
        model = _make_mock_model(
            '{"operation": "COUNT", "anchor": {"sport": "Sailing", "games": "2016-Summer"}, '
            '"constraints": [], "target_field": "event_name"}'
        )
        parser = IntentParser(model, supports_tool_calling=False)
        result = parser.parse("How many sailing events were held at Rio 2016?")
        assert result.operation == "COUNT"
        assert result.anchor.sport == "Sailing"
        assert result.anchor.games == "2016-Summer"

    def test_valid_argmax_schema(self):
        model = _make_mock_model(
            '{"operation": "ARGMAX", "anchor": {"sport": "Swimming", "games": "2008-Summer"}, '
            '"target_field": "gold_noc"}'
        )
        parser = IntentParser(model, supports_tool_calling=False)
        result = parser.parse("Which country won the most gold medals in swimming at Beijing 2008?")
        assert result.operation == "ARGMAX"
        assert result.target_field == "gold_noc"

    def test_valid_traverse_schema(self):
        model = _make_mock_model(
            '{"operation": "TRAVERSE", "anchor": {"title": "Triathlon at the 2016 Summer Olympics"}}'
        )
        parser = IntentParser(model, supports_tool_calling=False)
        result = parser.parse("What sport was at the previous edition of triathlon?")
        assert result.operation == "TRAVERSE"

    def test_tool_calling_path(self):
        """Tests the native tool-calling extraction path."""
        model = _make_model_with_tool_call({
            "operation": "COUNT",
            "anchor": {"sport": "Boxing", "games": "2004-Summer"},
            "target_field": "event_name",
        })
        parser = IntentParser(model, supports_tool_calling=True)
        result = parser.parse("How many boxing events at Athens 2004?")
        assert result.operation == "COUNT"
        assert result.anchor.sport == "Boxing"
        assert parser.extraction_path == "tool_calling"

    def test_json_schema_path_extraction_path_label(self):
        """extraction_path is recorded for run_config header."""
        model = _make_mock_model('{"operation": "ARGMAX", "anchor": {}}')
        parser = IntentParser(model, supports_tool_calling=False)
        assert parser.extraction_path == "json_schema"


class TestRetryOnceOnInvalidSchema:
    def test_retry_once_on_invalid_schema(self):
        """test_retry_once_on_invalid_schema: Model returns invalid JSON first, valid second."""
        model = MagicMock()
        bad_resp = MagicMock()
        bad_resp.content = "NOT VALID JSON {"
        bad_resp.tool_calls = []
        good_resp = MagicMock()
        good_resp.content = '{"operation": "COUNT", "anchor": {"sport": "Sailing"}}'
        good_resp.tool_calls = []
        model.invoke.side_effect = [bad_resp, good_resp]

        parser = IntentParser(model, supports_tool_calling=False)
        result = parser.parse("How many sailing events?")

        assert model.invoke.call_count == 2  # exactly one retry
        assert result.operation == "COUNT"

    def test_retry_feeds_the_validation_error_back(self):
        """The retry must differ from the first attempt — an identical prompt
        at temperature 0 reproduces the same failure."""
        model = MagicMock()
        bad_resp = MagicMock()
        bad_resp.content = "NOT VALID JSON {"
        bad_resp.tool_calls = []
        good_resp = MagicMock()
        good_resp.content = '{"operation": "COUNT", "anchor": {}}'
        good_resp.tool_calls = []
        model.invoke.side_effect = [bad_resp, good_resp]

        IntentParser(model, supports_tool_calling=False).parse("How many sailing events?")

        first, second = (call.args[0] for call in model.invoke.call_args_list)
        assert len(second) == len(first) + 1
        assert "rejected" in second[-1].content

    def test_fallback_to_traverse_on_double_failure(self):
        """After two failures, parser falls back to TRAVERSE (safe default for loop routing)."""
        model = MagicMock()
        bad_resp = MagicMock()
        bad_resp.content = "INVALID"
        bad_resp.tool_calls = []
        model.invoke.return_value = bad_resp

        parser = IntentParser(model, supports_tool_calling=False)
        result = parser.parse("Ambiguous question?")
        assert result.operation == "TRAVERSE"  # safe default

    def test_exactly_one_retry_not_more(self):
        """Parser invokes model at most twice — exactly one retry."""
        model = MagicMock()
        bad_resp = MagicMock()
        bad_resp.content = "BAD"
        bad_resp.tool_calls = []
        model.invoke.return_value = bad_resp

        parser = IntentParser(model, supports_tool_calling=False)
        parser.parse("test")
        assert model.invoke.call_count <= 2


class TestNoQtypeReadAtRuntime:
    def test_no_qtype_read_at_runtime(self):
        """test_no_qtype_read_at_runtime: intent.py contains no 'qtype' variable reads at runtime.

        NFR-7: qtype is an eval-set label and must never appear in the answer path.
        This AST check is the automated guard against accidentally introducing it.
        """
        intent_file = Path(__file__).resolve().parents[3] / "src" / "ogr" / "pipelines" / "p3_agentic" / "intent.py"
        assert intent_file.exists(), f"intent.py not found at {intent_file}"
        tree = ast.parse(intent_file.read_text(encoding="utf-8"))

        # Collect all Name nodes used in code (not in docstrings/comments)
        runtime_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                runtime_names.add(node.id)
            elif isinstance(node, ast.Attribute):
                runtime_names.add(node.attr)

        # 'qtype' must not appear as a runtime variable or attribute
        assert "qtype" not in runtime_names, (
            "NFR-7 violation: 'qtype' found as a runtime identifier in intent.py. "
            "qtype is an eval-set label and must never appear in the answer path."
        )

    def test_router_contains_no_qtype(self):
        """router.py must also have no qtype reads — it is part of the answer path."""
        router_file = Path(__file__).resolve().parents[3] / "src" / "ogr" / "pipelines" / "p3_agentic" / "router.py"
        assert router_file.exists()
        tree = ast.parse(router_file.read_text(encoding="utf-8"))
        runtime_names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert "qtype" not in runtime_names, "NFR-7 violation: 'qtype' found in router.py"

    def test_no_eval_string_branching(self):
        """No eval-set phrasings appear in intent.py strings (anti-overfitting check)."""
        intent_file = Path(__file__).resolve().parents[3] / "src" / "ogr" / "pipelines" / "p3_agentic" / "intent.py"
        content = intent_file.read_text(encoding="utf-8")
        # eval-set phrasing patterns that would indicate hard-coded branching
        forbidden_patterns = [
            "how many nations",
            "who won gold",
            "what sport was",
            "pub-00",
        ]
        for pattern in forbidden_patterns:
            assert pattern not in content.lower(), (
                f"Anti-overfitting violation: eval-set phrasing '{pattern}' found in intent.py"
            )


class TestGroundInQuestion:
    """Deterministic post-check of the LLM's extraction (any provider)."""

    def _parse(self, raw: dict, question: str):
        model = MagicMock()
        resp = MagicMock()
        resp.content = json.dumps(raw)
        resp.tool_calls = []
        model.invoke.return_value = resp
        return IntentParser(model, supports_tool_calling=False).parse(question)

    def test_empty_strings_become_none_and_numbers_are_numbers(self):
        intent = self._parse(
            {"operation": "COUNT", "anchor": {"sport": "Biathlon", "venue": "", "event_id": ""},
             "constraints": [{"field": "competitors", "op": ">", "value": "73"}], "target_field": ""},
            "How many biathlon events had more than 73 competitors?",
        )
        assert intent.anchor.venue is None and intent.anchor.event_id is None
        assert intent.constraints[0].value == 73
        assert intent.target_field is None

    def test_invented_event_id_and_venue_are_dropped(self):
        intent = self._parse(
            {"operation": "LOOKUP", "anchor": {"title": "Women's RS:X", "venue": "Marina da Glória",
                                               "event_id": "sailing-2016-womens-rsx"}},
            "Which nation won the Women's RS:X?",
        )
        assert intent.anchor.event_id is None
        assert intent.anchor.venue is None
        assert intent.anchor.title == "Women's RS:X"  # composed titles are kept

    def test_venue_written_in_the_question_is_kept(self):
        intent = self._parse(
            {"operation": "LOOKUP", "anchor": {"venue": "Olympic Weightlifting Gymnasium"}},
            "Who won at the olympic weightlifting gymnasium on 20 September?",
        )
        assert intent.anchor.venue == "Olympic Weightlifting Gymnasium"


def test_tool_calling_path_forces_the_intent_tool():
    model = MagicMock()
    bound = MagicMock()
    resp = MagicMock()
    resp.tool_calls = [{"args": {"operation": "COUNT", "anchor": {}}}]
    bound.invoke.return_value = resp
    model.bind_tools.return_value = bound
    IntentParser(model, supports_tool_calling=True).parse("How many events?")
    assert model.bind_tools.call_args.kwargs.get("tool_choice") == "emit_intent"
