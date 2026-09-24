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


class _Status(Exception):
    def __init__(self, status_code):
        super().__init__(f"status {status_code}")
        self.status_code = status_code


class _Model:
    def __init__(self, errors):
        self.errors = list(errors)
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        resp = type("R", (), {})()
        resp.content = "ok"
        resp.usage_metadata = {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4}
        return resp


def test_rate_limited_call_is_retried_with_exponential_backoff(monkeypatch):
    sleeps = []
    monkeypatch.setattr(llm.time, "sleep", sleeps.append)
    monkeypatch.setattr(llm.random, "uniform", lambda a, b: 0.0)
    model = _Model([_Status(429), _Status(503)])
    _resp, tokens, _src, _lat = llm.invoke_and_count(model, [], max_retries=5, backoff_base_s=2)
    assert model.calls == 3
    assert sleeps == [2.0, 4.0]
    assert tokens.total == 4  # only the successful call is counted


def test_non_transient_error_is_not_retried(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    model = _Model([_Status(401)])
    try:
        llm.invoke_and_count(model, [], max_retries=5, backoff_base_s=2)
    except _Status:
        pass
    assert model.calls == 1


def test_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    model = _Model([_Status(429)] * 10)
    try:
        llm.invoke_and_count(model, [], max_retries=2, backoff_base_s=1)
    except _Status:
        pass
    assert model.calls == 3


def test_seed_rate_limiter_and_single_retry_policy_reach_the_client():
    model = llm._build_chat_model(
        RunConfig(llm_model="m", llm_api_key="x", seed=7, llm_requests_per_minute=30)
    )
    assert model.seed == 7
    assert model.max_retries == 0
    assert model.rate_limiter is not None
    assert llm._build_chat_model(RunConfig(llm_model="m", llm_api_key="x", llm_requests_per_minute=0)).rate_limiter is None
