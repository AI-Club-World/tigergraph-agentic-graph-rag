"""Pluggable LLM provider abstraction for OGR pipelines.
Built on LangChain's ChatOpenAI / provider abstractions per PLAT-08 / LLM-01.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

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
        except ImportError:
            raise ImportError(
                "langchain-openai or langchain is required. Please install via: pip install langchain-openai"
            )

    base_url = config.llm_base_url
    api_key = config.llm_api_key or "local"

    kwargs: Dict[str, Any] = {
        "model": config.llm_model,
        "temperature": config.llm_temperature,
        "max_tokens": config.llm_max_tokens,
    }

    if base_url:
        kwargs["base_url"] = base_url
    if api_key:
        kwargs["api_key"] = api_key

    return ChatOpenAI(**kwargs)


def invoke_llm_with_answer_contract(
    model: Any,
    context: str,
    question: str,
) -> Tuple[str, str, TokenUsage, str, float]:
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

    t0 = time.perf_counter()
    response = model.invoke(messages)
    latency_ms = (time.perf_counter() - t0) * 1000.0

    raw_text = response.content if hasattr(response, "content") else str(response)
    if isinstance(raw_text, list):
        # LangChain may return list of content parts
        raw_text = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in raw_text)

    parsed = parse_answer_contract_json(raw_text)
    answer = parsed["answer"]
    explanation = parsed["explanation"]

    # Extract token usage from response metadata or usage callback
    tokens = TokenUsage()
    token_source = "provider"

    usage_metadata = getattr(response, "usage_metadata", None)
    if usage_metadata and isinstance(usage_metadata, dict):
        tokens.input = usage_metadata.get("input_tokens", 0)
        tokens.output = usage_metadata.get("output_tokens", 0)
        tokens.total = usage_metadata.get("total_tokens", tokens.input + tokens.output)
    else:
        resp_meta = getattr(response, "response_metadata", {})
        token_usage = resp_meta.get("token_usage", {}) if isinstance(resp_meta, dict) else {}
        if token_usage:
            tokens.input = token_usage.get("prompt_tokens", 0)
            tokens.output = token_usage.get("completion_tokens", 0)
            tokens.total = token_usage.get("total_tokens", tokens.input + tokens.output)
        else:
            # Fallback estimation if provider reports nothing
            token_source = "local_tokenizer"
            prompt_chars = len(SHARED_SYSTEM_PROMPT) + len(context) + len(question)
            tokens.input = max(1, prompt_chars // 4)
            tokens.output = max(1, len(raw_text) // 4)
            tokens.total = tokens.input + tokens.output

    return answer, explanation, tokens, token_source, latency_ms
