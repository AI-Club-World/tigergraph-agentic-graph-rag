"""Runtime LLM provider selection (ARCHITECTURE-SPEC, Decision log: G-4)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import ogr.api.main as api_main
import ogr.common.llm as llm_module
from ogr.api.security import get_config
from ogr.common.config import RunConfig

HEADERS: dict[str, str] = {}  # the API is open: no key


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    previous = api_main.app.dependency_overrides.get(get_config)
    api_main.app.dependency_overrides[get_config] = lambda: RunConfig()
    api_main._runtime_overrides.clear()
    with TestClient(api_main.app) as c:
        yield c
    api_main._runtime_overrides.clear()
    if previous is None:
        api_main.app.dependency_overrides.pop(get_config, None)
    else:
        api_main.app.dependency_overrides[get_config] = previous


def test_providers_report_which_keys_are_configured(client):
    rows = {p["id"]: p for p in client.get("/settings/providers", headers=HEADERS).json()}
    assert set(rows) == {"gemini", "nvidia_nim", "groq"}
    assert rows["groq"]["configured"] is True and rows["gemini"]["configured"] is False


def test_patch_provider_sets_base_url_and_key_for_every_pipeline(client):
    resp = client.patch(
        "/settings", headers=HEADERS, json={"llm_provider": "groq", "llm_model": "openai/gpt-oss-120b"}
    )
    assert resp.status_code == 200
    assert resp.json()["llm_provider"] == "groq"
    cfg = api_main._get_config_with_overrides()
    assert cfg.llm_base_url == "https://api.groq.com/openai/v1"
    assert cfg.llm_api_key == "groq-key" and cfg.llm_model == "openai/gpt-oss-120b"


def test_patch_provider_without_key_is_refused(client):
    resp = client.patch("/settings", headers=HEADERS, json={"llm_provider": "gemini", "llm_model": "x"})
    assert resp.status_code == 400 and "GEMINI_API_KEY" in resp.json()["detail"]


def test_patch_provider_requires_model_and_known_provider(client):
    assert client.patch("/settings", headers=HEADERS, json={"llm_provider": "groq"}).status_code == 422
    resp = client.patch("/settings", headers=HEADERS, json={"llm_provider": "openai", "llm_model": "x"})
    assert resp.status_code == 422


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def test_list_models_drops_only_non_text_types(monkeypatch):
    ids = [
        "meta/llama-3.3-70b-instruct", "nvidia/nv-embedqa-e5-v5", "baai/bge-m3",
        "nvidia/llama-3.2-nv-rerankqa-1b-v2", "deepseek-ai/deepseek-v4-flash", "meta/llama-guard-4-12b",
        "microsoft/phi-4-multimodal-instruct", "google/diffusiongemma-26b-a4b-it",
        "nvidia/riva-translate-4b-instruct-v2", "nvidia/ai-synthetic-video-detector", "nvidia/nemotron-parse",
    ]
    monkeypatch.setattr(
        llm_module.urllib.request, "urlopen", lambda req, timeout: _Resp({"data": [{"id": i} for i in ids]})
    )
    assert llm_module.list_models("nvidia_nim", "k") == [
        "deepseek-ai/deepseek-v4-flash", "google/diffusiongemma-26b-a4b-it", "meta/llama-3.3-70b-instruct",
        "microsoft/phi-4-multimodal-instruct", "nvidia/riva-translate-4b-instruct-v2",
    ]


def test_gemini_list_is_flash_and_flash_lite(monkeypatch):
    ids = ["models/gemini-2.5-flash", "models/gemini-2.5-flash-lite", "models/gemini-2.5-pro",
           "models/gemini-2.5-flash-preview-tts", "models/text-embedding-004"]
    monkeypatch.setattr(
        llm_module.urllib.request, "urlopen", lambda req, timeout: _Resp({"data": [{"id": i} for i in ids]})
    )
    assert llm_module.list_models("gemini", "k") == ["gemini-2.5-flash", "gemini-2.5-flash-lite"]


def test_model_listing_failure_names_the_provider(client, monkeypatch):
    def fail(*_a, **_k):
        raise OSError("connection refused")

    monkeypatch.setattr(llm_module.urllib.request, "urlopen", fail)
    resp = client.get("/settings/models", params={"provider": "groq"}, headers=HEADERS)
    assert resp.status_code == 502 and resp.json()["detail"].startswith("groq:")


def test_nvidia_list_is_narrowed_to_catalog_free_endpoints(monkeypatch):
    llm_module._FREE_CACHE.clear()
    catalog = {"results": [{"resources": [
        {"name": "llama-3_3-70b-instruct", "orgName": "meta", "displayName": "Llama 3.3 70B Instruct"},
        {"resourceId": "nvidia/nemotron-4-340b-instruct"},
    ]}]}
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        return _Resp(catalog)

    monkeypatch.setattr(llm_module.urllib.request, "urlopen", fake_urlopen)
    config = RunConfig(nvidia_free_catalog_url="https://catalog.example/search", nvidia_free_catalog_query='{"q":1}')
    models, note = llm_module.nvidia_free_endpoints(
        ["meta/llama-3.3-70b-instruct", "nvidia/nemotron-4-340b-instruct", "paid/other-model"], config
    )
    assert models == ["meta/llama-3.3-70b-instruct", "nvidia/nemotron-4-340b-instruct"] and note is None
    assert seen["url"].startswith("https://catalog.example/search?q=")


def test_unreachable_catalog_shows_all_with_a_note(monkeypatch):
    llm_module._FREE_CACHE.clear()

    def fail(*_a, **_k):
        raise OSError("blocked")

    monkeypatch.setattr(llm_module.urllib.request, "urlopen", fail)
    config = RunConfig(nvidia_free_catalog_url="https://catalog.example/search", nvidia_free_catalog_query="")
    models, note = llm_module.nvidia_free_endpoints(["a/b"], config)
    assert models == ["a/b"] and "Free Endpoint filter unavailable" in note


@pytest.mark.parametrize(
    ("provider", "base_url", "preset"),
    [
        ("openai_compatible", "https://integrate.api.nvidia.com/v1", "nvidia_nim"),
        ("openai", "https://api.groq.com/openai/v1", "groq"),
        ("openai_compatible", "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini"),
        ("google", None, "gemini"),
        ("groq", "https://api.groq.com/openai/v1", "groq"),
        ("openai_compatible", "http://localhost:11434/v1", None),
    ],
)
def test_settings_name_the_preset_serving_the_startup_model(client, provider, base_url, preset):
    api_main._runtime_overrides.update(llm_provider=provider, llm_base_url=base_url)
    body = client.get("/settings").json()
    assert body["llm_provider"] == provider and body["llm_provider_preset"] == preset
    if base_url and preset is None:
        assert body["llm_base_host"] == "localhost:11434"
