"""Pluggable LLM provider abstraction for OGR pipelines.
Built on LangChain's ChatOpenAI / provider abstractions per PLAT-08 / LLM-01.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any

from ogr.common.config import RunConfig, get_default_config
from ogr.common.contracts import (
    SHARED_SYSTEM_PROMPT,
    SHARED_USER_PROMPT,
    TokenUsage,
    parse_answer_contract_json,
)

logger = logging.getLogger(__name__)

_MODEL_CACHE: dict[tuple, Any] = {}
_MODEL_CACHE_LOCK = threading.Lock()


def get_chat_model(config: RunConfig) -> Any:
    """Return the LangChain chat model for this configuration.

    One instance per distinct model configuration, reused across pipelines,
    queries and batch items: P1/P2/P3 therefore share the very same client
    (one LLM for all three, TECHNICAL-SPEC §14.3), and a query no longer pays
    for constructing a new one.
    """
    key = (
        config.llm_model,
        config.llm_base_url,
        config.llm_api_key,
        config.llm_temperature,
        config.llm_max_tokens,
        config.seed,
        config.llm_requests_per_minute,
    )
    with _MODEL_CACHE_LOCK:
        if key not in _MODEL_CACHE:
            _MODEL_CACHE[key] = _build_chat_model(config)
        return _MODEL_CACHE[key]


def _build_chat_model(config: RunConfig) -> Any:
    """Supports local OpenAI-compatible servers (Ollama, llama.cpp, vLLM) and cloud providers."""
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        # Fallback if langchain_openai is not yet installed
        try:
            from langchain.chat_models import ChatOpenAI
        except ImportError as exc:
            raise ImportError(
                "langchain-openai or langchain is required. "
                "Install it with: pip install langchain-openai"
            ) from exc

    base_url = config.llm_base_url
    api_key = config.llm_api_key or "local"

    kwargs: dict[str, Any] = {
        "model": config.llm_model,
        "temperature": config.llm_temperature,
        "max_tokens": config.llm_max_tokens,
        # Several integrations omit usage when streaming unless asked (DP-5).
        # Without this the cost axis silently reads zero.
        "stream_usage": True,
        # Retries are owned by invoke_and_count (one backoff policy, from
        # run_config), so the SDK's own retry loop is switched off.
        "max_retries": 0,
    }
    if config.seed is not None:
        kwargs["seed"] = config.seed
    if config.llm_requests_per_minute > 0:
        from langchain_core.rate_limiters import InMemoryRateLimiter

        # Shared by every pipeline because the model instance is shared.
        kwargs["rate_limiter"] = InMemoryRateLimiter(
            requests_per_second=config.llm_requests_per_minute / 60.0,
            check_every_n_seconds=0.1,
            max_bucket_size=1,
        )

    if base_url:
        kwargs["base_url"] = base_url
    if api_key:
        kwargs["api_key"] = api_key

    return ChatOpenAI(**kwargs)


def resolve_tool_calling_support(model: Any, setting: str = "auto") -> bool:
    """Resolve the 'auto|true|false' tool-calling setting to a boolean.

    'auto' inspects whether the model class overrides `bind_tools`; the
    LangChain base raises NotImplementedError, so an unoverridden method means
    the provider cannot do native function-calling and the intent parser must
    take the JSON-schema path (PLAT-08 / AD-13).
    """
    normalized = (setting or "auto").strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False

    bind_tools = getattr(type(model), "bind_tools", None)
    if bind_tools is None:
        return False
    try:
        from langchain_core.language_models.chat_models import BaseChatModel
    except ImportError:
        return callable(bind_tools)
    return bind_tools is not getattr(BaseChatModel, "bind_tools", None)


def _extract_usage(response: Any) -> TokenUsage | None:
    """Read provider-reported usage off a response, or None if absent."""
    usage_metadata = getattr(response, "usage_metadata", None)
    if isinstance(usage_metadata, dict) and usage_metadata:
        tokens = TokenUsage(
            input=usage_metadata.get("input_tokens", 0),
            output=usage_metadata.get("output_tokens", 0),
        )
        tokens.total = usage_metadata.get("total_tokens", tokens.input + tokens.output)
        return tokens

    resp_meta = getattr(response, "response_metadata", {})
    token_usage = resp_meta.get("token_usage", {}) if isinstance(resp_meta, dict) else {}
    if token_usage:
        tokens = TokenUsage(
            input=token_usage.get("prompt_tokens", 0),
            output=token_usage.get("completion_tokens", 0),
        )
        tokens.total = token_usage.get("total_tokens", tokens.input + tokens.output)
        return tokens

    return None


def _count_with_model_tokenizer(model: Any, text: str) -> int | None:
    """Count tokens with the model's own tokenizer, or None if it has none."""
    counter = getattr(model, "get_num_tokens", None)
    if not callable(counter):
        return None
    try:
        return int(counter(text))
    except Exception:
        return None


_RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}
_RETRYABLE_NAMES = {"RateLimitError", "APIConnectionError", "APITimeoutError", "InternalServerError"}


def _retry_delay(error: Exception, attempt: int, base_s: float) -> float | None:
    """Seconds to wait before retrying `error`, or None if it is not transient."""
    response = getattr(error, "response", None)
    status = getattr(error, "status_code", None) or getattr(response, "status_code", None)
    if status not in _RETRYABLE_STATUS and type(error).__name__ not in _RETRYABLE_NAMES:
        return None
    retry_after = getattr(response, "headers", {}).get("retry-after") if response is not None else None
    try:
        if retry_after is not None:
            return float(retry_after)
    except ValueError:
        pass
    # Exponential backoff with jitter so a pool of workers does not retry in step.
    return base_s * (2**attempt) + random.uniform(0, base_s)


def _invoke_with_backoff(model: Any, messages: Any, max_retries: int, base_s: float) -> Any:
    for attempt in range(max_retries + 1):
        try:
            return model.invoke(messages)
        except Exception as e:
            delay = _retry_delay(e, attempt, base_s) if attempt < max_retries else None
            if delay is None:
                raise
            logger.warning("LLM call failed (%s); retry %d/%d in %.1fs", e, attempt + 1, max_retries, delay)
            time.sleep(delay)
    raise AssertionError("unreachable")


def invoke_and_count(
    model: Any,
    messages: Any,
    reports_usage: str = "auto",
    max_retries: int | None = None,
    backoff_base_s: float | None = None,
) -> tuple[Any, TokenUsage, str, float]:
    """The single accounting entry point — every model call goes through here.

    DP-5 Option A: provider-reported usage where available, the model's own
    tokenizer where not, and an explicit 'estimated' label where the model
    exposes no tokenizer either. A guess is never labelled as a count.

    Returns:
        (response, tokens, token_source, latency_ms)
    """
    if max_retries is None or backoff_base_s is None:
        defaults = get_default_config()
        max_retries = defaults.llm_max_retries if max_retries is None else max_retries
        backoff_base_s = defaults.llm_backoff_base_s if backoff_base_s is None else backoff_base_s

    t0 = time.perf_counter()
    # Rate-limit and transient errors are retried with exponential backoff
    # (BUILD-PLAN: a 429 storm mid-run is the likeliest cause of a partial
    # run); only the successful call's usage is counted.
    response = _invoke_with_backoff(model, messages, max_retries, backoff_base_s)
    latency_ms = (time.perf_counter() - t0) * 1000.0

    raw_text = _response_text(response)

    if (reports_usage or "auto").strip().lower() != "false":
        tokens = _extract_usage(response)
        if tokens is not None:
            return response, tokens, "provider", latency_ms

    prompt_text = "\n".join(
        str(getattr(m, "content", m)) for m in (messages if isinstance(messages, list) else [messages])
    )
    prompt_count = _count_with_model_tokenizer(model, prompt_text)
    output_count = _count_with_model_tokenizer(model, raw_text)

    if prompt_count is not None and output_count is not None:
        tokens = TokenUsage(
            input=prompt_count,
            output=output_count,
            total=prompt_count + output_count,
        )
        return response, tokens, "local_tokenizer", latency_ms

    # No provider usage and no tokenizer: label the number honestly (§11).
    tokens = TokenUsage(
        input=max(1, len(prompt_text) // 4),
        output=max(1, len(raw_text) // 4),
    )
    tokens.total = tokens.input + tokens.output
    return response, tokens, "estimated", latency_ms


def _response_text(response: Any) -> str:
    """Flatten a chat response into plain text."""
    raw_text = response.content if hasattr(response, "content") else str(response)
    if isinstance(raw_text, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in raw_text
        )
    return raw_text


def invoke_llm_with_answer_contract(
    model: Any,
    context: str,
    question: str,
    reports_usage: str = "auto",
) -> tuple[str, str, TokenUsage, str, float]:
    """Invokes the chat model with the byte-identical CORE-02 shared answer contract.
    Returns:
        (answer, explanation, token_usage, token_source, latency_ms)
    """
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
    except ImportError:
        from langchain.schema import HumanMessage, SystemMessage

    messages = [
        SystemMessage(content=SHARED_SYSTEM_PROMPT),
        HumanMessage(content=SHARED_USER_PROMPT.format(context=context, question=question)),
    ]

    response, tokens, token_source, latency_ms = invoke_and_count(
        model, messages, reports_usage=reports_usage
    )

    parsed = parse_answer_contract_json(_response_text(response))
    return parsed["answer"], parsed["explanation"], tokens, token_source, latency_ms
