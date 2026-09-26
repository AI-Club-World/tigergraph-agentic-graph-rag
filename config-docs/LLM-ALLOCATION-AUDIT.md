# LLM-ALLOCATION-AUDIT.md — LLM vs deterministic allocation across P1 / P2 / P3

**Date**: 2026-09-26
**Branch**: `application-integration`
**Scope**: every pipeline step of P1 (RAG), P2 (GraphRAG), P3 (Agentic GraphRAG), plus graph ingestion, the embedding integration and the LLM integration.
**Method**: read-only code trace of `backend/src/ogr/{pipelines,ingest,common,graph,api}` and `frontend/src/{SettingsPanel.tsx,services/settingsService.ts}`. Baseline: `pytest -q` → 383 passed; `ruff check src tests` → 2 pre-existing E501 in `api/main.py:199,204`.
**Evidence limit**: qualitative. No live TigerGraph / Cloudflare / NVIDIA / Groq access from the audit environment (egress blocked), so no before/after accuracy numbers are claimed. The one existing quantitative reference is `AUDIT-03.md` (bge-small recall@10 0.709 on the public set, 16,669 chunks).
**Plan**: `implementation-plan-LLM-ALLOCATION.md` (every item cites a gap ID below).

---

## 1. Decision rule

For each step: does an LLM call change result quality, or only add cost for the same outcome?
Justified LLM categories (from the task brief): **J1** query rewriting (ambiguous queries only), **J2** re-ranking (cross-encoder first), **J3** response synthesis, **J4** entity/relation extraction for graph construction, **J5** agentic reasoning/planning. Anything else must be deterministic or be flagged as a judgment call (**JC**).

---

## 2. Current state — per step

Legend: **LLM** = LLM call · **DET** = deterministic · **MISSING** = step absent.

### 2.1 Ingestion (shared by all pipelines)

| Step | File | Current | Verdict |
|---|---|---|---|
| Infobox parse → OlympicEvent / Games / Sport / Venue vertices + edges | `ingest/infobox.py` | DET (header + field parser) | **Keep DET.** Relations come from Wikipedia infobox key/value fields (`gold`, `venue`, `prev`/`next`, `competitors`…) — explicit, not implicit. J4 applies only "when relations are domain-specific or implicit"; here an LLM would re-extract the same fields at ~16k calls of cost with hallucination risk. |
| Chunking (300 tok / 50 overlap) | `ingest/chunk_embed.py` | DET | Keep DET. |
| Chunk / event embedding | `ingest/chunk_embed.py` → `common/embeddings.py` | DET, local `BAAI/bge-small-en-v1.5`, 384-dim | Keep DET, **migrate model** (G-1). |

### 2.2 P1 — RAG (`pipelines/p1_rag.py`)

| Step | Current | Verdict |
|---|---|---|
| Query embedding | DET (local bge-small) | Migrate model (G-1). |
| Vector search Q5, top-k=10, unfiltered | DET | Keep. |
| Query rewriting | MISSING | **Do not add.** AD-9 fixes P1 as the unfiltered baseline of the ablation. |
| Re-ranking | MISSING — *by design* (AD-9: "no re-ranking") | **Conflict** between AD-9 and the J2 guidance → decision DP-1. |
| Response synthesis | LLM, shared CORE-02 contract, 1 call | Keep (J3). |

### 2.3 P2 — GraphRAG (`pipelines/p2_graphrag.py`)

| Step | Current | Verdict |
|---|---|---|
| Intent parse → `{operation, anchor, constraints, target_field}` | LLM, 1 call (+1 retry only on schema failure), shared with P3 | **Keep — JC.** This is not a simple classifier: it is structured query understanding (slot extraction of event title, games, sport, venue, numeric constraints, target field). A rule table cannot do this without question-template regex, which NFR-7 forbids. P2 must reuse P3's parser so the P3−P2 gap measures only the loop (PLAT-07). Nearest category: J1 (query rewriting into a structured query) — applied to every query because no deterministic path can produce the slots. |
| Entity linking to graph vocab | DET (longest-match on Games/Sport/Venue vocab) | Keep. |
| Routing (lookup / aggregate / traverse) | DET rule (`router.route`) | Keep — matches "small classifier or rule table". |
| Graph query (Q1 / Q2 / Q3 / Q4) | DET GSQL | Keep. |
| Re-ranking | N/A — evidence is structured rows, not chunks | No reranker needed. |
| Response synthesis | LLM, 1 call | Keep (J3). |

### 2.4 P3 — Agentic GraphRAG (`pipelines/p3_agentic/*`)

| Step | Current | Verdict |
|---|---|---|
| Intent parse | LLM (same parser as P2) | Keep — JC as §2.3; this is also P3's plan step (J5). |
| Entity linking / AD-15 disambiguation | DET | Keep. |
| Necessity router | DET rule | Keep. |
| Tool agents: Q1 lookup, Q2/Q3 aggregation, Q4 traversal, multi-hop | DET GSQL | Keep. |
| Evidence evaluation stage 1 — scope coverage | DET | Keep. |
| Evidence evaluation stage 2 — groundedness | DET token-overlap pre-check, then LLM YES/NO; skipped when pre-check fails on prose or evidence is unchanged | **Keep — J5.** This verdict decides whether the loop continues and which fallback fires (the agentic decision). Already gated to avoid redundant calls (AUDIT-03 follow-up). No cheaper substitute is known to match it; removing it without measurement would violate the "don't degrade accuracy" constraint. |
| Fallback: Q5 similarity search (scope fail) | DET, top-k=10 | Keep; feeds G-2. |
| Fallback: HAS_CHUNK document retrieval (groundedness fail) | DET — returns **every** chunk of every evidence document, in document order | **Gap G-2.** |
| Context assembly for generation | `evidence[:20]` — positional truncation | **Gap G-2**: prose chunks past position 20 are dropped regardless of relevance; groundedness also reads only `evidence[:5]`. |
| Re-ranking | MISSING | **Gap G-2** — add a cross-encoder over prose chunks (J2). |
| Response synthesis | LLM, 1 call | Keep (J3). |

### 2.5 LLM call budget per query (current)

| Pipeline | Calls (typical) | All justified? |
|---|---|---|
| P1 | 1 (synthesis) | Yes (J3). |
| P2 | 2 (intent + synthesis) | Yes (JC-intent, J3). |
| P3 | 2–N (intent + ≤1 groundedness per loop iteration with new evidence + synthesis); direct lookup / aggregate / disambiguation routes add no groundedness call | Yes (JC-intent, J5, J3). |

**Finding: no LLM call is waste under the decision rule.** No existing LLM call is removed by the plan. The gaps are a missing component (reranker), the embedding / provider setup, and error handling.

---

## 3. Embedding integration — current vs required

| Aspect | Current | Required |
|---|---|---|
| Model | `BAAI/bge-small-en-v1.5` via local `sentence-transformers` | `@cf/baai/bge-m3` via Cloudflare Workers AI REST |
| Dimension | 384 | 1024 |
| Pipelines covered | All (single `common/embeddings.py` module) | All — unchanged single module, no per-pipeline variation |
| Where 384 is hard-coded | `graph/schema.gsql:112-113`, `config.py` default, `server_config.json`, `api/main.py:_EMBEDDING_DIMS`, `embeddings.py` defaults, `similarity_search.py` default, `settingsService.ts` options | all → 1024 / bge-m3 |
| Failure mode | Model load failure → sha256 hash pseudo-vectors, logged, recorded as `hash_fallback` in run header | See G-1 |

**G-1 consequences** (unavoidable): the vector attributes change dimension, so the existing index is invalid — the graph must be re-created and `ogr.cli build` re-run (full re-embed of ~16.7k chunks + events). Free-tier cost: bge-m3 is billed ~1,075 neurons / M input tokens; ~16.7k × ~300 tokens ≈ 5M tokens ≈ 5.4k neurons, inside the 10k neurons/day free allocation, once.

Cloudflare API (per Cloudflare docs, not live-verified from this environment): `POST https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/baai/bge-m3`, body `{"text": [..]}`, response `{"result": {"shape": [n, 1024], "data": [[..]]}, "success": true}`. Credentials: `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` (env only, never in `server_config.json`).

---

## 4. LLM integration — current vs required

| Aspect | Current | Required |
|---|---|---|
| Abstraction | Provider-agnostic `common/llm.py`: native Gemini (`google`/`gemini`), native Claude, OpenAI-compatible for everything else | Keep |
| Same LLM for all 3 pipelines in a run | Yes — config snapshot taken once per `/query` and per batch run; one cached client instance | Keep (verified: `api/main.py:_run_query`, `batch_runner`) |
| Runtime selection | `PATCH /settings` changes **model only**; provider, base URL and key are fixed by env | Provider **and** model selectable at runtime (UI) |
| Model lists | Static, hand-written in `settingsService.ts` (OpenAI, Anthropic, old Gemini ids); no NIM, no Groq | Gemini Flash / Flash-Lite, **all** NVIDIA NIM free-tier text models, Groq models — enumerated live |
| Rate limit | Up to 5 same-provider retries with backoff on 429/5xx; per-day quota fails fast; final error text is the raw SDK message | Clear error naming provider + reason; **no** cross-provider fallback (none exists today — keep it that way) |

Provider endpoints (OpenAI-compatible model listing — `GET {base}/models`, Bearer key):

| Preset | Client | Base / list URL | Key env |
|---|---|---|---|
| `gemini` | native `ChatGoogleGenerativeAI` | list: `https://generativelanguage.googleapis.com/v1beta/openai/models` | `GEMINI_API_KEY` |
| `nvidia_nim` | OpenAI-compatible | `https://integrate.api.nvidia.com/v1` | `NVIDIA_API_KEY` |
| `groq` | OpenAI-compatible | `https://api.groq.com/openai/v1` | `GROQ_API_KEY` |

---

## 5. Gap list

| ID | Pipeline · step | Type | Gap | Planned change |
|---|---|---|---|---|
| **G-1** | All · embedding (ingest + query) | Migration | Local bge-small 384-dim; required `@cf/baai/bge-m3` 1024-dim | Cloudflare client in `common/embeddings.py`; dim 1024 everywhere; schema + rebuild |
| **G-2** | P3 · fallback evidence → context | Missing component (quality) | No reranker; HAS_CHUNK returns all chunks, then positional `[:20]` truncation drops relevant prose | Cross-encoder rerank of prose chunks against the question before truncation (J2) |
| **G-3** | P1 · retrieval | Spec conflict | J2 suggests reranking; AD-9 forbids it for the baseline | Decision DP-1 |
| **G-4** | All · LLM selection | Missing feature | Provider not selectable at runtime; model lists static and missing NIM / Groq | Provider presets + live model enumeration + UI provider picker |
| **G-5** | All · LLM errors | Error handling | Rate-limit exhaustion surfaces as a raw SDK string without provider context | `LLMRateLimitError` naming provider/model/reason; no fallback |
| **G-6** | P2 / P3 · intent parse | Robustness (caused by G-4) | Tool-calling probe returns `true` for every OpenAI-compatible client; a NIM / Groq model without function-calling returns HTTP 400, which `IntentParser.parse` does not catch → pipeline error | On a tool-calling rejection, retry once on the JSON-schema path (same model) |
| — | Ingest · extraction | No gap | Infobox relations are explicit | Keep DET (documented §2.1) |
| — | P1/P2/P3 · query rewriting | No gap | Intent parser already produces a structured query; AD-15 handles ambiguity deterministically | Do not add a separate rewrite call |
| — | P3 · groundedness | No gap (J5) | Already gated | Keep |

---

## 6. Judgment calls (recorded per the "no LLM by default" constraint)

| Call | Category | Reasoning |
|---|---|---|
| Intent parse on every P2/P3 query | JC → nearest J1 | Structured slot extraction is not achievable by a rule table under NFR-7; P2 must share it for the ablation. Cost is one short call. |
| Groundedness YES/NO in the P3 loop | J5 | Decides loop continuation and fallback choice. Already skipped when a deterministic pre-check decides, or evidence is unchanged. |
| No LLM reranker | J2 | Cross-encoder is first choice; an LLM reranker is only justified after the cross-encoder is measured insufficient on this data — not yet measured (no live access). |

---

## 7. Design decisions (resolved 2026-09-26 — detail in plan)

- **DP-1** Reranker in P1 vs AD-9 → **P3 only**; P1 stays the unfiltered baseline.
- **DP-2** Reranker host → **Cloudflare `@cf/baai/bge-reranker-base`**.
- **DP-3** Rate limit → **retry same provider up to `LLM_MAX_RETRIES`, then stop the run** and ask the user to switch model and restart. No cross-provider fallback.
- **DP-4** Embedding failure → **same-model chain: Cloudflare bge-m3 → local `BAAI/bge-m3`** (then existing hash fallback, recorded). Same model on every tier, so the single-embedding-model rule holds. *Amended 2026-09-26:* the chosen NVIDIA NIM tier was removed — a live probe of `POST integrate.api.nvidia.com/v1/embeddings` returns `410 Gone: "The model 'baai/bge-m3' has reached its end of life on 2026-08-25"`, and the live NIM catalog has no other bge-m3; substituting a different NVIDIA model would put query vectors in a different space from the index.

Sources consulted for provider facts: [Cloudflare bge-m3](https://developers.cloudflare.com/workers-ai/models/bge-m3/), [Cloudflare bge-reranker-base](https://developers.cloudflare.com/workers-ai/models/bge-reranker-base/), [NVIDIA NIM free tier](https://itsfree.ai/provider/nvidia-nim/).

---

## 8. Verification pass (2026-09-26) — defects found and fixed

Method: live end-to-end run of the real backend and frontend (Chromium via Playwright) against a local OpenAI-compatible stub LLM, direct probes of the live NVIDIA / Groq / Cloudflare / Gemini endpoints, and two independent code reviews (backend, frontend) verified against both sides of each interface. Backend 383 → 422 tests; frontend 11/20 → 20/20 passing; `ruff`, `tsc`, `vite build` clean.

| Area | Defect | Fix |
|---|---|---|
| CI | 9 frontend tests failed (`RequiresServices` threw without its provider); `npm run build` failed (`test` key vs vite `defineConfig`); 2 ruff errors | provider-less render allowed; vitest `defineConfig`; lint fixed; `tests/conftest.py` keeps the suite off the network |
| Providers | urllib default User-Agent rejected by Cloudflare-fronted APIs (Groq: error 1010 / 403) | explicit User-Agent on every urllib call |
| Embeddings | NIM `baai/bge-m3` retired (410) | tier removed (DP-4 amendment above) |
| NIM catalog | filter dropped text LLMs (`diffusiongemma`, `riva-translate`) and kept image/video models | filter checked against the live 82-model catalog: 63 text models kept |
| Build | `POST /build` marked RAG ready after local chunk+embed (even with TigerGraph down), emitted stage names the UI does not know, per-stage/zero elapsed, no vector-readiness gate; Build button required the LLM | real stages, ready only when answerable, elapsed from build start, `wait_until_ready` gate, build needs TigerGraph only |
| Build | failed CREATE/INSTALL QUERY reported as success | install verified via `getInstalledQueries` |
| P3 | HAS_CHUNK fallback returned every chunk in the graph with empty text (`getEdgesByType` misuse) | per-document `getEdges` + `getVerticesById` |
| P2/P3 | venue questions ran Q4 PREV_EDITION (empty); underspecified LOOKUP answered from the previous edition; temporal traversal ignored the Games anchor | shared `first_loop_tool`: Q4 HELD_AT→Q1 for venues, Q1 for named events, anchor edition resolved before Q4; P2 still one query |
| P2/P3 | Q1 Document fallback rows had no content/citation | vertex rows flattened with `doc_id` |
| Accounting | `LLM_REPORTS_TOKEN_USAGE` honoured by P2 generation only | every LLM call in every pipeline |
| API | P3 setup blocked the event loop per query; health LLM probe retried past the UI timeout | setup in a worker thread; probe is one attempt, UI timeout 30 s |
| UI | SSE drop left columns spinning; stale results across runs; model-list race; empty-model Apply; every Apply reset the TigerGraph client; Dashboard/Eval opened non-existent run `latest`; RunPicker desync; null `qtype` crash | fixed individually |

**Not changed (flagged):** when a loop iteration adds no new evidence, P3 repeats the same traversal/fallback until the step budget. It costs no LLM tokens (the verdict is reused), and existing tests (`test_unsatisfiable_loop_stops_on_step_budget`, `test_unchanged_evidence_reuses_the_groundedness_verdict`) specify that stop reason, so stopping early with `no_further_action_available` is left as a decision.

**Still unverified (needs real credentials):** Cloudflare bge-m3 / reranker response shapes, Gemini/Groq/NIM chat with real keys, and a full build + benchmark against TigerGraph Savanna.
