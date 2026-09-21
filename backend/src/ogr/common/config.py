"""Configuration management for OGR pipelines and graph connections."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load .env from workspace root or current directory
load_dotenv()


class RunConfig(BaseModel):
    """Run configuration per TECHNICAL-SPEC and DP-1 Option A."""

    # DP-1 parameters (Option A: 300 tokens, 50 overlap, k=10)
    k: int = Field(default_factory=lambda: int(os.getenv("RUN_K", "10")))
    chunk_tokens: int = Field(default_factory=lambda: int(os.getenv("RUN_CHUNK_TOKENS", "300")))
    chunk_overlap: int = Field(default_factory=lambda: int(os.getenv("RUN_CHUNK_OVERLAP", "50")))

    # LLM parameters
    llm_provider: str = Field(default_factory=lambda: os.getenv("LLM_PROVIDER", "openai_compatible"))
    llm_model: str = Field(default_factory=lambda: os.getenv("LLM_MODEL", "qwen2.5:7b-instruct"))
    llm_base_url: Optional[str] = Field(default_factory=lambda: os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"))
    llm_api_key: Optional[str] = Field(default_factory=lambda: os.getenv("LLM_API_KEY") or None)
    llm_temperature: float = Field(default_factory=lambda: float(os.getenv("LLM_TEMPERATURE", "0.0")))
    llm_max_tokens: int = Field(default_factory=lambda: int(os.getenv("LLM_MAX_TOKENS", "1024")))

    # Embeddings
    embedding_model: str = Field(
        default_factory=lambda: os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    )
    embedding_dim: int = Field(default_factory=lambda: int(os.getenv("EMBEDDING_DIM", "384")))

    # TigerGraph connection
    tg_host: str = Field(default_factory=lambda: os.getenv("TG_HOST", "http://localhost"))
    tg_graphname: str = Field(default_factory=lambda: os.getenv("TG_GRAPHNAME", "OlympicGraphRAG"))
    tg_restpp_port: int = Field(default_factory=lambda: int(os.getenv("TG_RESTPP_PORT", "14240")))
    tg_gs_port: int = Field(default_factory=lambda: int(os.getenv("TG_GS_PORT", "14240")))
    tg_username: str = Field(default_factory=lambda: os.getenv("TG_USERNAME", "tigergraph"))
    tg_password: str = Field(default_factory=lambda: os.getenv("TG_PASSWORD", ""))
    tg_secret: str = Field(default_factory=lambda: os.getenv("TG_SECRET", ""))
    tg_token: str = Field(default_factory=lambda: os.getenv("TG_TOKEN", ""))
    tg_use_cert: bool = Field(default_factory=lambda: os.getenv("TG_USE_CERT", "true").lower() == "true")
    tg_cert_path: Optional[str] = Field(default_factory=lambda: os.getenv("TG_CERT_PATH") or None)

    # P3 Agentic pipeline parameters (DP-3 Option A)
    max_steps: int = Field(
        default_factory=lambda: int(os.getenv("RUN_MAX_STEPS", "6"))
    )
    max_tokens_per_query: int = Field(
        default_factory=lambda: int(os.getenv("RUN_MAX_TOKENS_PER_QUERY", "20000"))
    )
    llm_supports_tool_calling: bool = Field(
        default_factory=lambda: os.getenv("LLM_SUPPORTS_TOOL_CALLING", "false").lower() == "true"
    )



def get_default_config() -> RunConfig:
    """Return a RunConfig initialized from environment and defaults."""
    return RunConfig()
