"""Tests for the server_config.json / .env split (TECHNICAL-SPEC §14.1)."""

from __future__ import annotations

from ogr.common import config as config_module
from ogr.common.config import SERVER_CONFIG_PATH, RunConfig


def test_committed_server_config_exists_and_carries_no_secrets():
    text = SERVER_CONFIG_PATH.read_text(encoding="utf-8").lower()
    for secret in ("api_key", "password", "secret", "token\""):
        assert secret not in text


def test_file_value_is_used_when_env_is_unset(monkeypatch):
    monkeypatch.delenv("RUN_K", raising=False)
    monkeypatch.setattr(config_module, "_SERVER_CONFIG", {"run_defaults": {"k": 7}})
    assert RunConfig().k == 7


def test_env_overrides_the_file(monkeypatch):
    monkeypatch.setenv("RUN_K", "3")
    monkeypatch.setattr(config_module, "_SERVER_CONFIG", {"run_defaults": {"k": 7}})
    assert RunConfig().k == 3


def test_code_default_applies_when_neither_is_set(monkeypatch):
    monkeypatch.delenv("RUN_K", raising=False)
    monkeypatch.setattr(config_module, "_SERVER_CONFIG", {})
    assert RunConfig().k == 10


def test_booleans_in_the_file_map_to_env_style_strings(monkeypatch):
    monkeypatch.delenv("TG_USE_CERT", raising=False)
    monkeypatch.setattr(config_module, "_SERVER_CONFIG", {"db_config": {"useCert": False}})
    assert RunConfig().tg_use_cert is False
