"""Configuration management for OGR pipelines and graph connections."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load .env from workspace root or current directory
load_dotenv()

# TECHNICAL-SPEC §14.1: committed, secret-free structure. Precedence per
# setting: environment (.env) > config/server_config.json > code default.
# Secrets and deployment-specific values (hosts, keys, provider, model) are
# never in the file — they come only from the environment.
SERVER_CONFIG_PATH = Path(__file__).resolve().parents[4] / "config" / "server_config.json"

# env var -> path inside server_config.json
_FILE_KEYS: dict[str, tuple[str, ...]] = {
    "TG_GRAPHNAME": ("db_config", "graphname"),
    "TG_USE_CERT": ("db_config", "useCert"),
    "TG_CERT_PATH": ("db_config", "certPath"),
    "LLM_TEMPERATURE": ("llm_config", "completion_service", "model_kwargs", "temperature"),
    "LLM_MAX_TOKENS": ("llm_config", "completion_service", "model_kwargs", "max_tokens"),
    "LLM_SUPPORTS_TOOL_CALLING": ("llm_config", "completion_service", "supports_tool_calling"),
    "LLM_REPORTS_TOKEN_USAGE": ("llm_config", "completion_service", "reports_token_usage"),
    "EMBEDDING_MODEL": ("llm_config", "embedding_service", "model_name"),
    "EMBEDDING_DIM": ("llm_config", "embedding_service", "dimension"),
    "RUN_POOL_SIZE": ("llm_config", "rate_limit", "max_concurrent"),
    "OGR_STREAM_TOKEN_TTL_S": ("api_config", "stream_token_ttl_s"),
    "RUN_K": ("run_defaults", "k"),
    "RUN_CHUNK_TOKENS": ("run_defaults", "chunk_tokens"),
    "RUN_CHUNK_OVERLAP": ("run_defaults", "chunk_overlap"),
    "RUN_MAX_STEPS": ("run_defaults", "max_steps"),
    "RUN_MAX_TOKENS_PER_QUERY": ("run_defaults", "max_tokens_per_query"),
}


def _load_server_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


_SERVER_CONFIG = _load_server_config(SERVER_CONFIG_PATH)


def _file_value(name: str) -> str | None:
    """A server_config.json value as the string its env var would carry."""
    node: Any = _SERVER_CONFIG
    for key in _FILE_KEYS.get(name, ()):
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    if node is None or isinstance(node, dict):
        return None
    return str(node).lower() if isinstance(node, bool) else str(node)


def _env(name: str, default: str | None = None) -> str | None:
    """Environment first, then server_config.json, then the code default."""
    value = os.getenv(name)
    if value is not None:
        return value
    file_value = _file_value(name)
    return file_value if file_value is not None else default


class RunConfig(BaseModel):
    """Run configuration per TECHNICAL-SPEC and DP-1 Option A."""

    # DP-1 parameters (Option A: 300 tokens, 50 overlap, k=10)
    k: int = Field(default_factory=lambda: int(_env("RUN_K", "10")))
    chunk_tokens: int = Field(default_factory=lambda: int(_env("RUN_CHUNK_TOKENS", "300")))
    chunk_overlap: int = Field(default_factory=lambda: int(_env("RUN_CHUNK_OVERLAP", "50")))

    # LLM parameters
    llm_provider: str = Field(default_factory=lambda: _env("LLM_PROVIDER", "openai_compatible"))
    llm_model: str = Field(default_factory=lambda: _env("LLM_MODEL", "qwen2.5:7b-instruct"))
    llm_base_url: str | None = Field(default_factory=lambda: _env("LLM_BASE_URL", "http://localhost:11434/v1"))
    llm_api_key: str | None = Field(default_factory=lambda: _env("LLM_API_KEY") or None)
    llm_temperature: float = Field(default_factory=lambda: float(_env("LLM_TEMPERATURE", "0.0")))
    llm_max_tokens: int = Field(default_factory=lambda: int(_env("LLM_MAX_TOKENS", "1024")))

    # Embeddings
    embedding_model: str = Field(
        default_factory=lambda: _env("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    )
    embedding_dim: int = Field(default_factory=lambda: int(_env("EMBEDDING_DIM", "384")))

    # TigerGraph connection
    tg_host: str = Field(default_factory=lambda: _env("TG_HOST", "http://localhost"))
    tg_graphname: str = Field(default_factory=lambda: _env("TG_GRAPHNAME", "OlympicGraphRAG"))
    # Ports are optional. Community Edition uses 14240; Savanna serves over TLS
    # on 443 and pyTigerGraph derives that itself when tg_cloud is set, so
    # forcing 14240 there would send every request to a closed port.
    tg_restpp_port: int | None = Field(
        default_factory=lambda: int(p) if (p := _env("TG_RESTPP_PORT", "")) else None
    )
    tg_gs_port: int | None = Field(
        default_factory=lambda: int(p) if (p := _env("TG_GS_PORT", "")) else None
    )
    # Savanna / TigerGraph Cloud. Changes how pyTigerGraph builds URLs and
    # negotiates auth, so it must be set for a cloud workspace.
    tg_cloud: bool = Field(
        default_factory=lambda: _env("TG_CLOUD", "false").lower() == "true"
    )
    tg_jwt_token: str = Field(default_factory=lambda: _env("TG_JWT_TOKEN", ""))
    tg_username: str = Field(default_factory=lambda: _env("TG_USERNAME", "tigergraph"))
    tg_password: str = Field(default_factory=lambda: _env("TG_PASSWORD", ""))
    tg_secret: str = Field(default_factory=lambda: _env("TG_SECRET", ""))
    tg_token: str = Field(default_factory=lambda: _env("TG_TOKEN", ""))
    tg_use_cert: bool = Field(default_factory=lambda: _env("TG_USE_CERT", "true").lower() == "true")
    tg_cert_path: str | None = Field(default_factory=lambda: _env("TG_CERT_PATH") or None)

    # P3 Agentic pipeline parameters (DP-3 Option A)
    max_steps: int = Field(
        default_factory=lambda: int(_env("RUN_MAX_STEPS", "6"))
    )
    max_tokens_per_query: int = Field(
        default_factory=lambda: int(_env("RUN_MAX_TOKENS_PER_QUERY", "20000"))
    )
    # 'auto' probes the model's capability at startup; 'true'/'false' force it.
    # auto is the default because assuming capability is what breaks P3 silently
    # on a local model (PLAT-08 / AD-13).
    llm_supports_tool_calling: str = Field(
        default_factory=lambda: _env("LLM_SUPPORTS_TOOL_CALLING", "auto").lower()
    )
    llm_reports_token_usage: str = Field(
        default_factory=lambda: _env("LLM_REPORTS_TOKEN_USAGE", "auto").lower()
    )

    # Batch runner (EVAL-04). PLAT-08: default 2 concurrent on cloud free
    # tiers — a 429 storm mid-run is the likeliest cause of a partial run.
    pool_size: int = Field(default_factory=lambda: int(_env("RUN_POOL_SIZE", "2")))

    # API-01. Required on every route except /health (TECHNICAL-SPEC §4.5).
    # Empty means "no key configured" — the API refuses every request rather
    # than silently running unauthenticated.
    ogr_api_key: str = Field(default_factory=lambda: _env("OGR_API_KEY", ""))
    ogr_stream_token_ttl_s: int = Field(
        default_factory=lambda: int(_env("OGR_STREAM_TOKEN_TTL_S", "300"))
    )



def get_default_config() -> RunConfig:
    """Return a RunConfig initialized from environment and defaults."""
    return RunConfig()
