# LLM Allocation, Embedding Migration & Provider Selection — Implementation Plan

**Gap doc source**: [LLM-ALLOCATION-AUDIT.md](LLM-ALLOCATION-AUDIT.md)
**Workspace**: `backend/`, `frontend/`, `config/`, `env.example`

---

## Research Summary

Audit classified every step of P1/P2/P3 and ingestion. **No existing LLM call is waste** — all trace to J3 (synthesis), J5 (P3 groundedness) or a documented judgment call (intent parse). Six gaps:

- **G-1** embedding is local bge-small 384-dim; required `@cf/baai/bge-m3` 1024-dim — forces schema change + full rebuild.
- **G-2** P3 prose fallback has no reranker; relevant chunks are lost to positional `evidence[:20]` truncation.
- **G-3** J2 vs AD-9 conflict for P1 (needs DP-1).
- **G-4** LLM provider not runtime-selectable; model lists static, no NIM/Groq.
- **G-5** rate-limit exhaustion surfaces as a raw SDK string.
- **G-6** tool-calling rejection from a selectable NIM/Groq model crashes intent parse.

---

## Design Decisions Required Before Implementation

> [!IMPORTANT]
> Options + recommendation listed. Not implemented until selected.

### DP-1 — Reranker in P1 (G-3)

| # | Approach | Notes |
|---|---|---|
| **A** *(Recommended)* | P1 stays unfiltered (AD-9). Reranker only in P3 prose fallback | Keeps the ablation honest: P1 = no graph, no rerank; any P1 gain would be credited to the wrong variable |
| B | P1 retrieves k=30, reranks to top-10 | Raises P1 accuracy; requires amending AD-9 and shrinks the measured P3−P1 gap |

### DP-2 — Reranker host (G-2)

| # | Approach | Notes |
|---|---|---|
| **A** *(Recommended)* | Cloudflare `@cf/baai/bge-reranker-base` (512-token context; chunks are 300) | Same account/token as bge-m3; no local weights; lets `sentence-transformers` (+ torch) be dropped |
| B | Local `BAAI/bge-reranker-v2-m3` via `sentence_transformers.CrossEncoder` | Stronger multilingual model, free; keeps torch dependency (~2 GB) and adds CPU latency (~1–3 s / 30 pairs) |

### DP-3 — Rate-limit behaviour (G-5)

| # | Approach | Notes |
|---|---|---|
| **A** *(Recommended)* | Keep bounded same-provider backoff for per-minute 429s (existing), fail fast on per-day quota (existing); on exhaustion raise `LLMRateLimitError` naming provider, model, reason, and "switch LLM in Settings" | Free tiers (30–40 RPM) recover in seconds; no cross-provider retry anywhere |
| B | Zero retries: first 429 → `LLMRateLimitError` | Simplest; with pool=2 on a 30-RPM tier, bursts will fail runs that would have succeeded |

### DP-4 — Embedding failure mode (G-1)

| # | Approach | Notes |
|---|---|---|
| **A** *(Recommended)* | Cloudflare creds absent → existing hash fallback, logged + recorded as `hash_fallback` in run header (parity with today). Creds present but request fails → raise | Keeps offline unit tests working; a live API error is never silently turned into noise |
| B | Always raise when embedding is unavailable | Strictest; tests need a mock for every embedding path |

---

## Proposed Changes (ordered by dependency)

### Group 1 — Embedding migration (G-1)

#### [MODIFY] `backend/src/ogr/common/embeddings.py`
- Replace `sentence-transformers` loader with a Cloudflare Workers AI client (stdlib `urllib`): `POST .../ai/run/@cf/baai/bge-m3`, `{"text": [...]}`, read `result.data`; batch size 50; L2-normalise.
- `embedding_backend()` → `"cloudflare"` | `"hash_fallback"` (DP-4).
#### [MODIFY] `backend/src/ogr/common/config.py`
- Defaults `EMBEDDING_MODEL=@cf/baai/bge-m3`, `EMBEDDING_DIM=1024`; add `cloudflare_account_id`, `cloudflare_api_token` (env only).
#### [MODIFY] `backend/src/ogr/graph/schema.gsql` — `DIMENSION=1024` (both vector attributes).
#### [MODIFY] `config/server_config.json`, `env.example` — model / dim / service = `cloudflare`; new env vars.
#### [MODIFY] `backend/src/ogr/api/main.py` (`_EMBEDDING_DIMS`), `pipelines/p3_agentic/agents/similarity_search.py` (default dim) — 1024.
#### [MODIFY] `frontend/src/services/settingsService.ts` — `EMBEDDING_OPTIONS` = bge-m3 only.
#### [MODIFY] `backend/pyproject.toml` — drop `sentence-transformers` (only if DP-2 = A).
#### [MODIFY] tests: `tests/common/test_embeddings.py`, `tests/graph/test_schema.py` (dim) — commit carries `TEST-CHANGE:` marker (CI guard).

### Group 2 — Reranker (G-2, DP-1, DP-2)

#### [NEW] `backend/src/ogr/common/rerank.py`
- `rerank(query, chunks, top_n) -> chunks` — cross-encoder scores (per DP-2), sorted desc; on missing creds / API error, return input order unchanged (logged) so P3 never degrades below today.
#### [MODIFY] `backend/src/ogr/pipelines/p3_agentic/orchestrator.py`
- `node_generate`: rerank prose items (`source in {similarity_search, document_retrieval}`) against the question; structured graph rows stay first and untouched; then `[:20]`.
- `node_evaluate_evidence`: rerank `document_retrieval` output before it joins state, so groundedness (`evidence[:5]`) also sees the best chunks.
#### (DP-1 = B only) [MODIFY] `pipelines/p1_rag.py` + AD-9 amendment in `ARCHITECTURE-SPEC.md`.

### Group 3 — Provider selection (G-4)

#### [MODIFY] `backend/src/ogr/common/llm.py`
- `PROVIDER_PRESETS = {gemini, nvidia_nim, groq}` — client kind, base URL, list URL, key env var.
- `list_models(provider)` — live `GET {base}/models`; drop only non-text model types (embedding, rerank, retriever, speech/audio, image-generation, OCR) — no hand-picked subset.
#### [MODIFY] `backend/src/ogr/common/config.py` — `gemini_api_key`, `nvidia_api_key`, `groq_api_key` (env only).
#### [MODIFY] `backend/src/ogr/api/main.py`
- `GET /settings/providers` → presets with `configured` (key present).
- `GET /settings/models?provider=` → live list (502 with provider name on failure).
- `PATCH /settings` accepts `llm_provider`; resolves base URL + key from the preset; clears client cache. Per-query config snapshot unchanged → one LLM for all 3 pipelines per run.
#### [MODIFY] `frontend/src/services/settingsService.ts`, `frontend/src/SettingsPanel.tsx`
- Provider dropdown → live model dropdown (free-text still allowed); remove static `MODELS_BY_PROVIDER`.
#### [MODIFY] `env.example` — `GEMINI_API_KEY`, `NVIDIA_API_KEY`, `GROQ_API_KEY`.

### Group 4 — Rate-limit error (G-5, DP-3)

#### [MODIFY] `backend/src/ogr/common/llm.py`
- `LLMRateLimitError(provider, model, reason)`; raised by `_invoke_with_backoff` when the final failure is a rate limit / quota. Message names provider + model + reason + "switch the LLM in Settings; no automatic fallback". Flows unchanged into `PipelineRecord.error_detail` (existing handlers) → UI.

### Group 5 — Intent-parse robustness (G-6)

#### [MODIFY] `backend/src/ogr/pipelines/p3_agentic/intent.py`
- If the tool-calling request is rejected by the provider (HTTP 400 / `BadRequestError`), switch this parser to the JSON-schema path and retry — same model, same provider. Shared by P2 and P3, so both stay identical.

---

## Verification Plan

```
cd backend && ruff check src tests && pytest -q
cd frontend && npm run lint && npm run build && npm test
```

New tests:
- **G1**: Cloudflare request/response parse (mocked `urlopen`), normalisation, batching, creds-absent → `hash_fallback`, API error → raises.
- **G2**: `rerank` reorders by mocked scores; API failure → original order; `node_generate` keeps structured rows ahead of reranked prose.
- **G3**: `list_models` filters non-text types; `PATCH /settings` with provider sets base URL/key; unknown provider → 422.
- **G4**: 429 exhaustion → `LLMRateLimitError` text contains provider + model; no second provider called.
- **G5**: tool-calling 400 → JSON-schema path used, intent returned.

Manual (needs live creds — not possible from audit environment): re-create graph, `ogr.cli build`, public benchmark; compare against `AUDIT-03.md` recall@10 0.709 baseline.

---

## Execution Order

1. Group 1 (embedding) → verify suite
2. Group 2 (reranker, P3) → verify
3. Group 3 (provider selection) → Group 4 (rate-limit error) → verify
4. Group 5 (intent robustness) → verify
5. Spec sync: `TECHNICAL-SPEC.md` §1 tech-stack rows (embedding, LLM, reranker)
