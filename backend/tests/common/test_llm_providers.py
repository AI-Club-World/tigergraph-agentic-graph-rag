"""common/llm.py picks a native client per LLM_PROVIDER; the rest of the
system is provider-agnostic (usage_metadata, one retry policy, one limiter)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ogr.common import llm
from ogr.common.config import RunConfig


@pytest.mark.parametrize(
    ("provider", "cls"),
    [
        ("anthropic", "ChatAnthropic"),
        ("claude", "ChatAnthropic"),
        ("google", "ChatGoogleGenerativeAI"),
        ("gemini", "ChatGoogleGenerativeAI"),
        ("openai", "ChatOpenAI"),
        ("groq", "ChatOpenAI"),
        ("openai_compatible", "ChatOpenAI"),
    ],
)
def test_provider_selects_its_client(provider, cls):
    model = llm._build_chat_model(
        RunConfig(llm_provider=provider, llm_model="m", llm_api_key="k", llm_base_url=None, llm_requests_per_minute=30)
    )
    assert type(model).__name__ == cls
    assert model.max_retries == 0  # invoke_and_count owns retries for every provider
    assert model.rate_limiter is not None


def test_anthropic_gets_token_limit_and_base_url():
    model = llm._build_chat_model(
        RunConfig(llm_provider="anthropic", llm_model="m", llm_api_key="k", llm_base_url="http://proxy", llm_max_tokens=321)
    )
    assert model.max_tokens == 321
    assert model.anthropic_api_url == "http://proxy"


def test_gemini_gets_seed_and_token_limit():
    model = llm._build_chat_model(
        RunConfig(llm_provider="google", llm_model="m", llm_api_key="k", llm_base_url=None, seed=7, llm_max_tokens=321)
    )
    assert model.seed == 7
    assert model.max_output_tokens == 321


def test_cache_key_includes_provider(monkeypatch):
    monkeypatch.setattr(llm, "_MODEL_CACHE", {})
    monkeypatch.setattr(llm, "_build_chat_model", lambda config: object())
    a = llm.get_chat_model(RunConfig(llm_provider="google", llm_model="m"))
    b = llm.get_chat_model(RunConfig(llm_provider="anthropic", llm_model="m"))
    assert a is not b


def test_google_style_error_code_is_retried():
    class APIError(Exception):
        code = 429

    assert llm._retry_delay(APIError("quota"), 0, 1.0) is not None


def test_anthropic_overloaded_is_retried():
    assert llm._retry_delay(SimpleNamespace(status_code=529, response=None), 0, 1.0) is not None


def test_list_shaped_content_is_flattened():
    response = SimpleNamespace(content=[{"type": "thinking", "thinking": "..."}, {"type": "text", "text": "YES"}])
    assert llm._response_text(response) == "YES"


def test_wrapped_rate_limit_error_without_status_is_retried():
    class GoogleRateLimitError(Exception):
        pass

    assert llm._retry_delay(GoogleRateLimitError("429 RESOURCE_EXHAUSTED"), 0, 1.0) is not None
