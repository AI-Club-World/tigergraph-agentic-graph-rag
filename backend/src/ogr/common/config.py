"""Configuration management for OGR pipelines and graph connections."""

from __future__ import annotations

import json
import logging
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
    "LLM_THINKING": ("llm_config", "completion_service", "thinking_level"),
    "LLM_SUPPORTS_TOOL_CALLING": ("llm_config", "completion_service", "supports_tool_calling"),
    "LLM_REPORTS_TOKEN_USAGE": ("llm_config", "completion_service", "reports_token_usage"),
    "NVIDIA_FREE_CATALOG_URL": ("llm_config", "nvidia_free_endpoints", "catalog_url"),
    "NVIDIA_FREE_CATALOG_QUERY": ("llm_config", "nvidia_free_endpoints", "catalog_query"),
    "EMBEDDING_MODEL": ("llm_config", "embedding_service", "model_name"),
    "RUN_POOL_SIZE": ("llm_config", "rate_limit", "max_concurrent"),
    "LLM_REQUESTS_PER_MINUTE": ("llm_config", "rate_limit", "requests_per_minute"),
    "LLM_BACKOFF_BASE_S": ("llm_config", "rate_limit", "backoff_base_s"),
    "LLM_MAX_RETRIES": ("llm_config", "rate_limit", "max_retries"),
    "OGR_STREAM_TOKEN_TTL_S": ("api_config", "stream_token_ttl_s"),
    "RUN_K": ("run_defaults", "k"),
    "RUN_CHUNK_TOKENS": ("run_defaults", "chunk_tokens"),
    "RUN_CHUNK_OVERLAP": ("run_defaults", "chunk_overlap"),
    "RUN_MAX_STEPS": ("run_defaults", "max_steps"),
    "RUN_MAX_TOKENS_PER_QUERY": ("run_defaults", "max_tokens_per_query"),
    "RUN_MAX_TOTAL_TOKENS": ("run_defaults", "max_total_tokens"),
    "RUN_LATENCY_MODE": ("run_defaults", "latency_mode"),
    "RUN_SEED": ("run_defaults", "seed"),
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


def _embedding_key(name: str | None) -> str:
    """The catalog key for EMBEDDING_MODEL. A retired value (the old
    `@cf/baai/bge-m3`) falls back to the default model: a graph embedded with
    it uses the pre-switching layout, and a build asks for the reset it needs."""
    from ogr.common.embedding_models import DEFAULT_MODEL_KEY, UnknownEmbeddingModel, resolve_model

    try:
        return resolve_model(name).key
    except UnknownEmbeddingModel:
        logging.getLogger(__name__).warning(
            "EMBEDDING_MODEL=%r is not a selectable model; using %s", name, DEFAULT_MODEL_KEY
        )
        return DEFAULT_MODEL_KEY


def _embedding_dim(name: str | None) -> int:
    from ogr.common.embedding_models import resolve_model

    return resolve_model(_embedding_key(name)).dim


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
    # Keys for the runtime-selectable presets (common/llm.py PROVIDER_PRESETS).
    gemini_api_key: str = Field(default_factory=lambda: _env("GEMINI_API_KEY", ""))
    groq_api_key: str = Field(default_factory=lambda: _env("GROQ_API_KEY", ""))
    nvidia_api_key: str = Field(default_factory=lambda: _env("NVIDIA_API_KEY", ""))
    # NGC catalog search that build.nvidia.com's "Free Endpoint" filter uses;
    # the NIM /v1/models list carries no such label. Kept in config so the
    # query can be corrected without a code change.
    nvidia_free_catalog_url: str = Field(default_factory=lambda: _env("NVIDIA_FREE_CATALOG_URL", ""))
    nvidia_free_catalog_query: str = Field(default_factory=lambda: _env("NVIDIA_FREE_CATALOG_QUERY", ""))
    llm_temperature: float = Field(default_factory=lambda: float(_env("LLM_TEMPERATURE", "0.0")))
    llm_max_tokens: int = Field(default_factory=lambda: int(_env("LLM_MAX_TOKENS", "1024")))
    # Gemini thinking level (minimal|low|medium|high; empty = provider
    # default). 'minimal' by default: thinking tokens count against
    # max_tokens and truncated the answer JSON in live runs, and the answer
    # path is extraction/synthesis, not multi-step reasoning.
    llm_thinking: str = Field(default_factory=lambda: (_env("LLM_THINKING", "minimal") or "").lower())
    # Sampling seed passed to the provider where supported; recorded in every
    # run header (NFR-4). Empty = no seed.
    seed: int | None = Field(default_factory=lambda: int(v) if (v := _env("RUN_SEED", "")) else None)
    # Rate limiting (free tiers 429 aggressively).
    # requests_per_minute 0 disables the limiter; retries back off
    # exponentially from backoff_base_s on 429/5xx/connection errors.
    llm_requests_per_minute: float = Field(
        default_factory=lambda: float(_env("LLM_REQUESTS_PER_MINUTE", "0"))
    )
    llm_backoff_base_s: float = Field(default_factory=lambda: float(_env("LLM_BACKOFF_BASE_S", "2")))
    llm_max_retries: int = Field(default_factory=lambda: int(_env("LLM_MAX_RETRIES", "5")))

    # Embeddings — one of common/embedding_models.py, by key. This is the
    # startup default; the model in use is the active one of the embedding
    # store (ingest/embedding_index.py), set from Settings. The dimension is
    # the model's own. Credentials are env-only; Cloudflare is skipped when
    # they are empty.
    embedding_model: str = Field(default_factory=lambda: _embedding_key(_env("EMBEDDING_MODEL")))
    embedding_dim: int = Field(default_factory=lambda: _embedding_dim(_env("EMBEDDING_MODEL")))
    # false: embed with the local model only (Cloudflare still serves the
    # reranker) — e.g. an index built locally is queried with the same tier.
    embedding_remote: bool = Field(
        default_factory=lambda: _env("EMBEDDING_REMOTE", "true").lower() != "false"
    )
    # A self-hosted embedding service (POST {url}/embed {"model", "texts"} ->
    # {"embeddings"}) serving the same catalog models; tried first when set.
    embedding_host_url: str = Field(default_factory=lambda: _env("EMBEDDING_HOST_URL", ""))
    # false: never embed through Cloudflare (it still serves the reranker).
    embedding_cloudflare: bool = Field(
        default_factory=lambda: _env("EMBEDDING_CLOUDFLARE", "true").lower() != "false"
    )
    cloudflare_account_id: str = Field(default_factory=lambda: _env("CLOUDFLARE_ACCOUNT_ID", ""))
    cloudflare_api_token: str = Field(default_factory=lambda: _env("CLOUDFLARE_API_TOKEN", ""))

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
    # 'throughput' runs with pool_size for accuracy/token metrics (pool-
    # invariant); 'timing' forces pool 1 so latency_ms is comparable
    # (TECHNICAL-SPEC §11). Recorded in the run header.
    latency_mode: str = Field(default_factory=lambda: _env("RUN_LATENCY_MODE", "throughput").lower())
    # Run-level cost ceiling; the per-query budgets bound a query, this
    # bounds a whole batch run. 0 disables it.
    max_total_tokens: int = Field(default_factory=lambda: int(_env("RUN_MAX_TOTAL_TOKENS", "5000000")))

    # API-01. Required on every route except /health (TECHNICAL-SPEC §4.5).
    # Empty means "no key configured" — the API refuses every request rather
    # than silently running unauthenticated.
    ogr_api_key: str = Field(default_factory=lambda: _env("OGR_API_KEY", ""))
    # Optional second key for destructive routes (build/reset, uploads,
    # embedding jobs, settings, benchmarks, imports). Set, it splits access:
    # OGR_API_KEY becomes a viewer key (ask, read). Unset, OGR_API_KEY keeps
    # every right, as before.
    ogr_admin_key: str = Field(default_factory=lambda: _env("OGR_ADMIN_KEY", ""))
    # Lifetime of a browser session (POST /auth/session); 8 h by default.
    ogr_session_ttl_s: int = Field(default_factory=lambda: int(_env("OGR_SESSION_TTL_S", "28800")))
    # /health/llm waits this long for its one-token completion; a cold
    # free-tier model can take well over 20 s.
    health_llm_timeout_s: float = Field(
        default_factory=lambda: float(_env("HEALTH_LLM_TIMEOUT_S", "120"))
    )
    ogr_stream_token_ttl_s: int = Field(
        default_factory=lambda: int(_env("OGR_STREAM_TOKEN_TTL_S", "300"))
    )
    # CORS. Comma-separated browser origins allowed to call this API; the
    # Vite dev server (5173) is included by default so `npm run dev` works
    # against a locally running backend with no extra configuration.
    ogr_cors_origins: list[str] = Field(
        default_factory=lambda: [
            origin.strip()
            for origin in _env(
                "OGR_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
            ).split(",")
            if origin.strip()
        ]
    )



def get_default_config() -> RunConfig:
    """Return a RunConfig initialized from environment and defaults."""
    return RunConfig()
