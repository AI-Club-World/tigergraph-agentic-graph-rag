"""get_chat_model reuses one client per model configuration (AUDIT-03)."""

from __future__ import annotations

from ogr.common import llm
from ogr.common.config import RunConfig


def test_same_config_returns_the_same_client(monkeypatch):
    monkeypatch.setattr(llm, "_MODEL_CACHE", {})
    monkeypatch.setattr(llm, "_build_chat_model", lambda config: object())
    config = RunConfig(llm_model="m", llm_base_url="http://x/v1")
    assert llm.get_chat_model(config) is llm.get_chat_model(RunConfig(llm_model="m", llm_base_url="http://x/v1"))


def test_different_model_gets_a_different_client(monkeypatch):
    monkeypatch.setattr(llm, "_MODEL_CACHE", {})
    monkeypatch.setattr(llm, "_build_chat_model", lambda config: object())
    assert llm.get_chat_model(RunConfig(llm_model="a")) is not llm.get_chat_model(RunConfig(llm_model="b"))
