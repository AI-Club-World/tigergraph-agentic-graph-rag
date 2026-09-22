"""Pluggable LLM provider abstraction for OGR pipelines.
Built on LangChain's ChatOpenAI / provider abstractions per PLAT-08 / LLM-01.
"""

from __future__ import annotations

import time
from typing import Any

from ogr.common.config import RunConfig
from ogr.common.contracts import (
    SHARED_SYSTEM_PROMPT,
    SHARED_USER_PROMPT,
    TokenUsage,
    parse_answer_contract_json,
)


def get_chat_model(config: RunConfig) -> Any:
    """Return an initialized LangChain chat model based on run_config.
    Supports local OpenAI-compatible servers (Ollama, llama.cpp, vLLM) and cloud providers.
    """
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
    }

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


def invoke_and_count(
    model: Any,
    messages: Any,
    reports_usage: str = "auto",
) -> tuple[Any, TokenUsage, str, float]:
    """The single accounting entry point — every model call goes through here.

    DP-5 Option A: provider-reported usage where available, the model's own
    tokenizer where not, and an explicit 'estimated' label where the model
    exposes no tokenizer either. A guess is never labelled as a count.

    Returns:
        (response, tokens, token_source, latency_ms)
    """
    t0 = time.perf_counter()
    response = model.invoke(messages)
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
