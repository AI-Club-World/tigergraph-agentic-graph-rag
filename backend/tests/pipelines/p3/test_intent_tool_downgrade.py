"""G-6: a selected model that rejects tool-calling falls back to the JSON-schema path."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from ogr.pipelines.p3_agentic.intent import IntentParser


class _BadRequest(Exception):
    status_code = 400


def _model(tool_error: Exception) -> MagicMock:
    model = MagicMock()
    bound = MagicMock()
    bound.invoke.side_effect = tool_error
    model.bind_tools.return_value = bound
    resp = MagicMock()
    resp.content = json.dumps({"operation": "COUNT", "anchor": {"sport": "Sailing"}})
    resp.usage_metadata = {"input_tokens": 5, "output_tokens": 5, "total_tokens": 10}
    model.invoke.return_value = resp
    return model


def test_tool_rejection_uses_json_schema_path_with_same_model():
    model = _model(_BadRequest("tools not supported for this model"))
    parser = IntentParser(model, supports_tool_calling=True)
    intent = parser.parse("How many sailing events?")
    assert intent.operation == "COUNT" and intent.anchor.sport == "Sailing"
    assert parser.extraction_path == "json_schema"
    assert model.invoke.call_count == 1


def test_other_errors_are_not_masked():
    class _Unauthorized(Exception):
        status_code = 401

    parser = IntentParser(_model(_Unauthorized("bad key")), supports_tool_calling=True)
    with pytest.raises(_Unauthorized):
        parser.parse("How many sailing events?")
