"""Connectivity check for the configured LLM and TigerGraph endpoints.

`python -m ogr.cli verify`

Answers one question per dependency: does the configured credential reach a
working endpoint? Nothing here writes, ingests or spends more than a few
tokens. Secrets are never printed — only whether they are set.
"""

from __future__ import annotations

from ogr.common.config import RunConfig, get_default_config

OK, FAIL, SKIP = "OK", "FAIL", "SKIP"


def _mask(value: str | None) -> str:
    if not value:
        return "<empty>"
    return f"<set, {len(value)} chars>"


def check_llm(config: RunConfig) -> tuple[str, str]:
    """One tiny completion through the same boundary the pipelines use."""
    if not config.llm_api_key and not config.llm_base_url:
        return SKIP, "no LLM_API_KEY and no LLM_BASE_URL"
    try:
        from ogr.common.llm import get_chat_model, invoke_and_count
    except Exception as e:
        return FAIL, f"import failed: {e}"

    try:
        # A short cap: reachability needs one token, and a reasoning model
        # given the full LLM_MAX_TOKENS can think past the health timeout.
        model = get_chat_model(config.model_copy(update={"llm_max_tokens": 32}))
    except Exception as e:
        return FAIL, f"could not construct client: {e}"

    try:
        from langchain_core.messages import HumanMessage

        # One attempt, no backoff: a retried 429 would outlast the
        # HEALTH_LLM_TIMEOUT_S window of /health/llm.
        _, tokens, source, latency = invoke_and_count(
            model, [HumanMessage(content="Reply with the single word: ok")], max_retries=0
        )
        return OK, (
            f"{config.llm_provider}/{config.llm_model} responded in {latency:.0f} ms, "
            f"{tokens.total} tokens ({source})"
        )
    except Exception as e:
        return FAIL, f"{type(e).__name__}: {str(e)[:160]}"


def check_tigergraph(config: RunConfig, client=None) -> tuple[str, str]:
    """Reach REST++ through the same connection and auth the queries use.

    `echo` rather than `getVersion`: /version can be refused to a query-only
    token (e.g. Savanna) while installed queries work, which showed the
    database as down while it was serving queries."""
    if not config.tg_host:
        return SKIP, "TG_HOST is empty — paste the workspace endpoint from Savanna"

    try:
        import pyTigerGraph  # noqa: F401
    except ImportError:
        return FAIL, "pyTigerGraph not installed (pip install -e '.[dev]')"

    from ogr.graph.client import TigerGraphClient

    client = client or TigerGraphClient(config)
    client._ensure_connection()
    if client.conn is None:
        return FAIL, "client could not be constructed — see the warning logged above"

    try:
        reply = client.conn.echo()
        return OK, f"connected to {config.tg_host} (graph {config.tg_graphname}): {str(reply)[:80]}"
    except Exception as e:
        return FAIL, f"{type(e).__name__}: {str(e)[:200]}"


def check_embedding(config: RunConfig) -> tuple[str, str]:
    """Which tier would serve the active embedding model right now.

    OK   = Cloudflare (for a model it hosts) answered a one-text request.
    SKIP = degraded but semantic: the local model (loaded or cached) serves.
    FAIL = no working tier — queries and re-embed jobs would fail (strict)."""
    import time

    from ogr.common import embeddings
    from ogr.common.embedding_models import resolve_model

    model = resolve_model(config.embedding_model)
    cf_note = "no Cloudflare credentials"
    if not model.cloudflare_id:
        cf_note = f"Cloudflare does not host {model.label}"
    elif config.cloudflare_account_id and config.cloudflare_api_token:
        t0 = time.perf_counter()
        try:
            [vector] = embeddings._embed_cloudflare(
                ["ok"], config.cloudflare_account_id, config.cloudflare_api_token, model.cloudflare_id
            )
            ms = (time.perf_counter() - t0) * 1000
            return OK, f"Cloudflare {model.cloudflare_id}, {len(vector)}-dim, {ms:.0f} ms"
        except Exception as e:
            cf_note = f"Cloudflare failed ({type(e).__name__}: {str(e)[:120]})"

    if embeddings._MODELS.get(model.hf_id) is not None:
        return SKIP, f"{cf_note}; local {model.hf_id} loaded and serving"
    try:
        from huggingface_hub import try_to_load_from_cache

        cached = isinstance(try_to_load_from_cache(model.hf_id, "config.json"), str)
    except Exception:
        cached = False
    if cached:
        return SKIP, f"{cf_note}; local {model.hf_id} cached (loads on first use)"
    return FAIL, f"{cf_note}; local {model.hf_id} not downloaded — vectors would be hash noise"


def check_queries(config: RunConfig) -> tuple[str, str]:
    """Are the five GSQL queries installed? The pipelines are useless without them."""
    if not config.tg_host:
        return SKIP, "needs TG_HOST"
    from ogr.graph.client import TigerGraphClient

    client = TigerGraphClient(config)
    client._ensure_connection()
    if client.conn is None:
        return SKIP, "no connection"
    try:
        installed = client.conn.getInstalledQueries()
        names = set(installed) if isinstance(installed, (list, set)) else set(installed.keys())
    except Exception as e:
        return FAIL, f"could not list queries: {str(e)[:140]}"

    expected = {"q1_lookup", "q2_count_where", "q3_argmax", "q4_traverse", "q5_hybrid_search"}
    # pyTigerGraph returns endpoint keys ("GET /query/<graph>/q1_lookup"),
    # not bare query names — compare on the last path segment.
    missing = sorted(expected - {n.rsplit("/", 1)[-1] for n in names})
    if missing:
        return FAIL, f"missing: {', '.join(missing)} (GRAPH-07 not built yet)"
    return OK, "all five installed"


def run(config: RunConfig | None = None, pre_build: bool = False) -> int:
    """Print one line per dependency. Returns 0 only if nothing FAILed.

    `pre_build`: the queries are installed by the build, so on a fresh
    workspace their absence is reported (WARN) rather than failing."""
    cfg = config or get_default_config()

    print("Configuration")
    print(f"  TG_HOST          {cfg.tg_host or '<empty>'}")
    print(f"  TG_CLOUD         {cfg.tg_cloud}")
    print(f"  TG_TOKEN         {_mask(cfg.tg_token)}")
    print(f"  LLM_PROVIDER     {cfg.llm_provider}")
    print(f"  LLM_MODEL        {cfg.llm_model}")
    print(f"  LLM_API_KEY      {_mask(cfg.llm_api_key)}")
    print(f"  EMBEDDING_MODEL  {cfg.embedding_model}")
    print()

    queries = check_queries(cfg)
    if pre_build and queries[0] == FAIL and queries[1].startswith("missing"):
        queries = ("WARN", queries[1].replace("GRAPH-07 not built yet", "installed by the build"))
    results = [
        ("LLM", *check_llm(cfg)),
        ("Embedding", *check_embedding(cfg)),
        ("TigerGraph", *check_tigergraph(cfg)),
        ("GSQL queries", *queries),
    ]
    print("Checks")
    for name, status, detail in results:
        print(f"  [{status:4}] {name:14} {detail}")

    failed = [name for name, status, _ in results if status == FAIL]
    print()
    print(f"{len(failed)} failed" if failed else "all reachable checks passed")
    return 1 if failed else 0
