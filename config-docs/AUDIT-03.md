# AUDIT-03.md — Independent review: code quality, architecture, spec compliance, judging criteria

**Date**: 2026-09-23
**Scope**: whole repo on `application-integration` — backend (`backend/src/ogr/`), frontend (`frontend/src/`), TigerGraph schema/queries (`backend/src/ogr/graph/`), against `config-docs/APPLICATION-SPEC.md`, `ARCHITECTURE-SPEC.md`, `TECHNICAL-SPEC.md`, `UI-SPEC.md`.
**Method**: read-only review — no code changes. Firsthand tracing of `pipelines/p3_agentic/*`, `graph/*`, `pipelines/p1_rag.py`, `pipelines/p2_graphrag.py` by the lead reviewer; delegated, independently-verified sub-reviews of `common/`, `eval/`, `ingest/`, `api/`, `cli.py` and of the full `frontend/src/` against `UI-SPEC.md`. `config-docs/AUDIT.md`'s prior self-reported "every item DONE" was treated as unverified and re-checked against the code rather than repeated.

This is iteration 3 of the audit record (`AUDIT.md` = iteration 1/2, covering P1/P3 plus a follow-on pass). This file does not replace it — it is an independent second read, scoped to code quality/architecture/spec-compliance/judging-criteria rather than task-by-task PLAN-00x conformance.

**Resolution pass (2026-09-23):** every finding below is annotated inline; the Scorecard adds a post-fix column. Also in this pass (technical directive, not an audit finding): default embedding model switched to `BAAI/bge-small-en-v1.5` (same 384-dim, free/local) — requires a `/build` re-embed of an existing index. Follow-up pass: scatter x-tick key collisions (`Charts.tsx`), unbounded `StreamTokenStore` (`api/security.py`), and per-iteration groundedness LLM calls (`evidence.py` deterministic pre-check, `orchestrator.py` verdict reuse) fixed; specs resynced to code.

---

## Scorecard

| Dimension | Score | Post-fix | Justification | Post-fix rationale |
|---|---|---|---|---|
| Code quality | 3/5 | 4/5 | Solid structure, typed dataclasses, mostly-good error isolation — but a Critical `asyncio.gather` bug can abort an entire 100-question batch run, plus a silently-swallowed embedding-model load failure and a non-constant-time API-key check. | All three named defects fixed with regression tests (backend 311 → 354 tests, frontend 5 → 20). Not 5: the fixes are unit-tested against mocks only — no live TigerGraph/LLM run in this pass. |
| Architecture | 4/5 | 5/5 | Genuine three-way ablation (P1 removes graph, P2 removes loop, P3 has both), shared answer contract enforced by construction, GSQL kept to 5 parameterized queries. Undercut by an unimplemented `server_config.json` split and no caching of per-query graph/LLM client construction. | Both undercutting items fixed: `config/server_config.json` with env > file > default; per-client vocab cache, one shared LLM instance, one process-wide TigerGraph client. |
| Spec compliance | 2/5 | 4/5 | Majority of FR/AD items independently verified as implemented correctly, but two Critical deviations: `POST /batch` (FR-13, TECHNICAL-SPEC §4.3) does not exist in the API, and the AD-15 disambiguation path — the named mitigation for 23% venue ambiguity — is dead code end-to-end. `AUDIT.md`'s self-reported "every item DONE" does not hold under independent tracing. | Both Criticals closed; specs resynced to code; the planned-but-never-built EVAL-04/REPRO-01 items (run `seed`, `throughput`/`timing` modes, `max_total_tokens` ceiling, rpm limit + backoff, `make reproduce` with `ogr.cli build`) implemented. Not 5: REPRO-01's Dockerfile and a pinned Python lockfile (ARCHITECTURE-SPEC §10) still do not exist, and nothing has been run against a live TigerGraph/LLM. |
| Agentic/RAG design | 4/5 | 5/5 | Two-LLM-touchpoint design (intent parse + one groundedness check) is disciplined and well-justified; routing is deterministic per DP-1 as specified. Marred by dead code (`no_further_action_available` is structurally unreachable) and a retry in the intent parser that never actually varies its input despite claiming to. | Dead stop reason reachable, retry feeds the error back, AD-15 disambiguation live and deterministic. |
| Token efficiency | 3/5 | 4/5 | LLM call count per run is minimal by design and correctly reconciled (Σ trace tokens == total, per DP-5). But every query rebuilds the LLM client and re-fetches all three graph vocabularies from TigerGraph from scratch (no caching across requests/batch items), and a failed batch record can abort accumulated spend on the whole run. | Caching as above; ambiguous-venue runs make 1 LLM call (intent) instead of ≥ 2; groundedness call skipped when a deterministic pre-check fails or evidence is unchanged; loop stops once all loop tools are tried. Not 5: savings shown by tests, not measured on a benchmark run. |

Post-fix scores are a self-assessment by the agent that made the fixes, not an independent re-review.

---

## Review Comments

### `backend/src/ogr/pipelines/p3_agentic/agents/entity_linking.py` — venue disambiguation
- **[Critical][bug]** `entity_linking.py:178-197` (`_resolve_venue`) never returns `(None, non-empty-candidates)`. On an ambiguous multi-match it returns `(best, candidates)` (line 197); `resolved` is therefore always truthy, so `resolve()` (lines 124-130) always takes the `if resolved: result.venue = resolved` branch and the `disambiguation_candidates["venue"] = candidates` line is unreachable. **Failure scenario:** a question naming an ambiguous venue (e.g. "Olympic Stadium", 115 events) silently gets the longest-name candidate substituted with no disambiguation — exactly the "highest-similarity guess" behavior ARCHITECTURE-SPEC AD-15 explicitly rejected in favor of surfacing candidates.
  - **[RESOLVED]** `agents/entity_linking.py` `_resolve_venue` now returns `(None, candidates)` on an ambiguous non-exact multi-match; new `ResolvedAnchors.needs_disambiguation` (candidates present and no sport/title/event_id discriminator, per ARCHITECTURE-SPEC §13).
- **[Major][test-coverage]** `backend/tests/pipelines/p3/test_entity_linking.py:111-119` (`test_unresolved_venue_provides_candidates_when_partial`) gates its only real assertion behind `if result.venue is None:` — a condition the code above never satisfies for the multi-candidate case, so the test passes vacuously without ever exercising disambiguation. This is how the bug above shipped past 185 green tests.
  - **[RESOLVED]** `test_entity_linking.py` asserts unconditionally (venue `None`, all 3 candidates, `needs_disambiguation`); added `test_sport_discriminator_means_no_disambiguation_request`.
- **[Critical][bug]** `pipelines/p3_agentic/orchestrator.py` (all nodes) never reads `resolved_anchors.disambiguation_candidates` and never passes `has_disambiguation_candidates=True` into `should_stop()` (`stopping.py:55`). Even if the entity-linking bug above were fixed, `stop_reason="disambiguation_required"` is still unreachable — the wiring from entity linker → stopping evaluator doesn't exist.
  - **[RESOLVED]** `orchestrator.py`: `route_after_parse` sends `needs_disambiguation` runs to a new `disambiguate` node, which takes `stop_reason` from `should_stop(has_disambiguation_candidates=True)` and returns the candidates deterministically (no retrieval, no generation call); covered by `TestDisambiguationPath` in `test_orchestrator.py`.

### `backend/src/ogr/pipelines/p3_agentic/stopping.py`
- **[Minor][bug]** `stopping.py:92-95` — `no_further_action_available` requires `{"lookup","aggregation","traversal","similarity_search","document_retrieval","multi_hop"}.issubset(tools_tried)`. `"lookup"` and `"aggregation"` are only ever added by `node_lookup_direct`/`node_scoped_aggregate` (`orchestrator.py:188,210`), both of which route straight to `generate` and never enter the loop (`orchestrator.py:500-501`). Inside a loop run, `tools_tried` can therefore never contain `"lookup"` or `"aggregation"` — this stop reason is structurally dead code, despite the module docstring calling this a "closed vocabulary" of 6 reachable reasons.
  - **[RESOLVED]** `stopping.py`: fires when a loop traversal tool (`PRIMARY_LOOP_TOOLS`) and both fallbacks (`FALLBACK_TOOLS`) were tried — only loop-reachable tools; test `test_no_further_action_reachable_with_loop_tools_only`.

### `backend/src/ogr/pipelines/p3_agentic/intent.py`
- **[Minor][bug]** `intent.py:196-200` — the retry log says "retrying with explicit correction prompt," but `_extract(question)` is called identically on both attempts (no error feedback, no prompt change). At `temperature=0` (default per §14.1), the retry will very often reproduce the identical failure, burning a full extra LLM call for no behavioral difference. Log message overclaims what the code does.
  - **[RESOLVED]** `intent.py`: the one retry now appends the validation error (`_correction_message`) to both extraction paths' prompts; log text corrected; test `test_retry_feeds_the_validation_error_back`.

### `backend/src/ogr/graph/client.py`
- **[Minor][design]** `client.py:106-111,198-225` — `self.last_query_args` is mutated on every `hybrid_search`/`_run_query` call on a client instance that is shared across concurrently-dispatched pipelines (P1/P2/P3 via `asyncio.gather`) and across a batch pool of up to 6 in flight. Comment says it's "for inspection and guard test assertion," but if anything outside tests ever reads it, it's a race. Document as test-only or remove.
  - **[RESOLVED]** `graph/client.py`: `last_query_args` documented as test-only (read only by `test_p1_unfiltered.py`; no production reader).
- **[Minor][design]** No thread-safety statement for `pyTigerGraph.TigerGraphConnection` reused across concurrent async/thread-pool callers (per `AUDIT.md`: "Sync pipelines run in a worker thread"). Worth a one-line confirmation in the code or a connection-per-call/pool strategy, given the client is shared app-wide in `api/main.py`.
  - **[RESOLVED]** `graph/client.py` class docstring: pyTigerGraph ≥ 2.0 uses a per-thread `requests.Session` (verified in `pyTigerGraphBase._session`); lazy connect serialised by `_conn_lock`; `pyproject.toml` pins `pyTigerGraph>=2.0`; `api/main.py` now actually shares one client (`_get_client`).

### `backend/src/ogr/pipelines/p3_agentic/orchestrator.py`
- **[Major][efficiency]** `_prepare_run` (lines 519-544) rebuilds `EntityLinker` from 3 fresh `client.get_vocabulary()` REST calls, and constructs a new LLM client via `get_chat_model(cfg)`, on **every single query** — in `api/main.py` and in batch mode — unless the caller explicitly passes `entity_linker=`/`llm_model=`. Games/Sport/Venue vocabularies (21/41/303 values) are static for a run; this is 3 avoidable REST round-trips per query, multiplied by 150 questions in a batch run.
  - **[RESOLVED]** `TigerGraphClient.get_vocabulary` caches each non-empty vocabulary per client; `common/llm.get_chat_model` returns one cached instance per model config (the same LLM object serves P1/P2/P3); `api/main.py` reuses one process-wide client — vocab REST calls drop from 3/query to 3/process (cache cleared after `/build` reload).

### `backend/src/ogr/eval/batch_runner.py` / `store.py`
- **[Critical][bug]** `batch_runner.py:107-130` — `_run_one` has no try/except around `BatchRecord` construction or `store.append`, and the `asyncio.gather(*(_run_one(q) for q in pending))` call (line 130) omits `return_exceptions=True`. A single downstream exception (e.g. `store.append`'s secret-leak assertion misfiring — see below, or a Pydantic validation error) propagates out of `gather`, cancels every other in-flight question, and aborts the whole 100/50-question run — contradicting APPLICATION-SPEC §7's "zero silent failures" and the module's own docstring. `test_one_pipeline_failure_does_not_drop_the_question` only tests a failure `dispatch()` already isolates, not this path.
  - **[RESOLVED]** `eval/batch_runner.py`: every question runs under its own try/except (logged with traceback), so no exception reaches `gather` — `return_exceptions` is therefore unneeded; unrecorded questions stay unwritten (resume retries them) and the run ends with `BatchIncompleteError` naming them (CLI exits 1, `/runs` status `failed`); test `TestPostDispatchFailureIsolation`.
- **[Minor][security]** `store.py:27` — secret-leak regex only matches `sk-[A-Za-z0-9_-]{16,}` (OpenAI-shaped). TigerGraph secrets/tokens and other providers' keys have different shapes and would not be caught by the write-time assertion TECHNICAL-SPEC §14.3 claims covers "no credential ... in a persisted record."
  - **[RESOLVED]** `eval/store.py`: adds Groq/Google/HF/GitHub/JWT shapes plus an exact-value check against configured `LLM_API_KEY`, `TG_PASSWORD`, `TG_SECRET`, `TG_TOKEN`, `TG_JWT_TOKEN`, `OGR_API_KEY` (≥ 8 chars); tests in `test_store.py`.

### `backend/src/ogr/common/`
- **[Major][bug]** `embeddings.py:13-22` — `SentenceTransformer(model_name)` load failure is caught by a bare `except Exception` with **no logging** (module has no `logging` import), silently routing every embedding through a SHA-256 pseudo-vector fallback. Vector search then runs against noise with nothing in logs, `PipelineRecord`, or the batch store ever indicating the configured embedding model never loaded — undermines NFR-4 reproducibility.
  - **[RESOLVED]** `common/embeddings.py`: load failure logged at ERROR ("vector search results are NOT semantic"); `embedding_backend()` (`sentence-transformers`|`hash_fallback`) is written into every batch run's `run_config` header (`batch_runner.run_config_header`).
- **[Minor][bug]** `embeddings.py:10-22` — `_MODEL_INSTANCE` is a single unkeyed global; a second call with a different `model_name` silently returns the first-loaded model.
  - **[RESOLVED]** `common/embeddings.py`: `_MODELS` dict keyed by model name (failures cached too, not retried per call); default model now read from `RunConfig`, so ingestion and query embedding cannot diverge; test `test_cache_is_keyed_by_model_name`.
- **[Major][spec-conflict]** `common/config.py` never reads `config/server_config.json` — no `config/` directory exists in the repo. TECHNICAL-SPEC §14.1's two-file split (committed structure vs. `.env` secrets) is half-implemented: everything comes straight from `os.getenv`.
  - **[RESOLVED]** added `config/server_config.json` (no secrets); `common/config.py` `_env()` resolves env > file > code default for 16 fields; TECHNICAL-SPEC §14.1 synced to the file; tests `tests/common/test_config.py`.
- **[Minor][spec-conflict]** `contracts.py:54` — `token_source` includes `"estimated"`, a third value TECHNICAL-SPEC §6.2 doesn't list (documented in `AUDIT.md` as a deliberate widening — reasonable, but still an undocumented-to-consumers schema extension).
  - **[RESOLVED]** `estimated` documented to consumers: TECHNICAL-SPEC §6.2, UI-SPEC data model + provenance note, `frontend/src/types.ts` union, `ResultColumn.tsx` note.

### `backend/src/ogr/api/`
- **[Critical][spec-conflict]** `api/main.py` has no `POST /batch` route. Confirmed by grepping every route decorator in the file — only `/query`, `/query/{id}/result`, `/query/{id}/stream`, `/build`, `/build/{id}/stream`, `/batch/{run_id}/records` exist. TECHNICAL-SPEC §4.3 and FR-13 ("callable without the UI") both require it; the fully-implemented `batch_runner.py` is reachable only from `cli.py`, not the API.
  - **[RESOLVED]** `POST /batch` landed in commit `dbfe5ee` after this audit's snapshot: `api/main.py` `post_batch` delegates to `batch_runner.run_batch` (plus `GET /datasets`, `/runs`); covered by `tests/api/test_runs.py`. Re-verified in this pass.
- **[Minor][bug]** `api/main.py:56` — `StreamTokenStore()` uses its hardcoded `ttl_s=300` default; `config.ogr_stream_token_ttl_s` is read nowhere. `OGR_STREAM_TOKEN_TTL_S` in `.env` has no effect.
  - **[RESOLVED]** `api/main.py`: `StreamTokenStore(ttl_s=get_default_config().ogr_stream_token_ttl_s)`; test `test_stream_token_ttl_comes_from_config`.
- **[Minor][security]** `api/security.py:34` — `x_api_key != config.ogr_api_key` is a plain string comparison, not `secrets.compare_digest`. Low real-world severity behind `127.0.0.1`, but it's the one secret this module protects.
  - **[RESOLVED]** `api/security.py`: `secrets.compare_digest` on the encoded key.
- **[Minor][design]** `api/main.py:57-58` — `_queries`/`_builds` dicts grow unboundedly across a session; no eviction after a client reads the result.
  - **[RESOLVED]** `api/main.py`: `_evict_finished` drops the oldest finished `/query` and `/build` entries beyond `_MAX_RETAINED = 100`; test `test_finished_queries_are_evicted_beyond_the_cap`.
- Router-level `Depends(require_api_key)` (`main.py:54`) correctly matches TECHNICAL-SPEC §4.5's "protected by default" design — **no finding, cited as compliant**.
  - **[N/A — compliance note, not a finding]** No change required.

### `backend/src/ogr/cli.py`
- **[Minor][design]** `cli.py:117-157` (`ask` command) has no per-pipeline try/except, unlike `dispatcher.py`/`api/main.py`. One pipeline's exception aborts the whole CLI invocation, printing nothing for pipelines that already succeeded — inconsistent with the fault-isolation pattern used everywhere else.
  - **[RESOLVED]** `cli.py` `ask`: each pipeline runs in its own try/except and a failure yields `dispatcher.error_record`; test `tests/test_cli.py`.

### Frontend — `frontend/src/`
- **[Critical][design]** Three accessibility gaps UI-SPEC §14 explicitly frames as **must-fix-in-rebuild**, not preserve-as-is, are still present verbatim: expandable eval rows (`EvalTable.tsx:175-177`) have no `onKeyDown`/`tabIndex`/`role`/`aria-expanded`; no `aria-live` region anywhere (`SearchView.tsx`, `TracePanel.tsx`); chart tooltips remain SVG `<title>`-hover-only (`Charts.tsx:85`) with no data-table fallback.
  - **[RESOLVED]** `EvalTable.tsx` rows: `tabIndex`, Enter/Space `onKeyDown`, `aria-expanded`, `aria-controls`; `SearchView.tsx`: `aria-live="polite"` status region; `Charts.tsx`: "Show data table" `<details>` fallback (`.sr-only`/`.chart-data` in `index.css`).
- **[Major][test-coverage]** `SearchView.test.tsx` has exactly 2 tests. No `BuildView.test.tsx`, `Dashboard.test.tsx`, or `EvalTable.test.tsx` exists at all — so the Build reducer's sticky-`ready`/`max()`/token-accumulation semantics, the Dashboard's mean-of-ratios computation and 0.5/0.05 thresholds, and the Eval table's disagreement normalization and four sort orders — all things UI-SPEC calls load-bearing — are untested.
  - **[RESOLVED]** added `BuildView.test.tsx` (4), `Dashboard.test.tsx` (4), `EvalTable.test.tsx` (5): reducer sticky-`ready`/`max()`/token sums, mean-of-ratios + 0.5/0.05 thresholds, normalization, all four sorts, keyboard expand.
- **[Major][design]** `services/mock/transport.ts:16-32` — `MATCHERS` array is declared in one order (`aggregation, superlative, multi_hop, lookup`) but `scenarioFor` silently uses a second, independently-ordered `ordered` array that actually matches spec §5.3. Runtime is correct; the code has two disagreeing sources of truth, a maintenance trap for the next editor.
  - **[RESOLVED]** `transport.ts`: single `MATCHERS` array in UI-SPEC §5.3 order; `scenarioFor` iterates it directly (behaviour unchanged).
- **[Minor][bug]** `Dashboard.tsx:48-52` — `agentic.tokens.total / rag.tokens.total` unguarded against `rag.tokens.total === 0`, which would fold `Infinity`/`NaN` into a qtype's mean silently.
  - **[RESOLVED]** `Dashboard.tsx`: questions with `rag.tokens.total === 0` are excluded from the qtype mean; covered in `Dashboard.test.tsx`.
- **[Minor][style]** `Dashboard.tsx:117,122`, `EvalTable.tsx:83,140` use curly quotes where UI-SPEC's literal strings (§8, §9) specify straight quotes.
  - **[RESOLVED]** `Dashboard.tsx`, `EvalTable.tsx`: straight quotes per UI-SPEC §8/§9 literals.
- Everything else independently spot-checked — data model, mock-transport timing/scenario routing, Search run lifecycle, Build reducer semantics, "never recompute a score" invariant, Eval table normalization/sorting, formatting helpers, theming tokens, 1100px breakpoint, zero `any` escape hatches — **matches UI-SPEC exactly**. This is the strongest module in the codebase for spec fidelity.
  - **[N/A — compliance note, not a finding]** No change required.

### GSQL / schema — `backend/src/ogr/graph/`
No correctness defects found in `schema.gsql` or `q1`–`q5`. Endpoints are pinned as required, `bronze` is correctly a `SET<STRING>`, vector attributes added via the required `SCHEMA_CHANGE JOB`, Q2/Q3's constraint handling matches the documented 2-constraint practical limit. Only style-level: Q1's fallback to a raw `Document` match (`q1_lookup.gsql:68-72`) returns a different attribute shape under the same `results` alias as the `EventRow` tuple branch — works because `client.py` treats results generically, but is worth a comment noting the shape divergence for the next reader.
  - **[RESOLVED]** `q1_lookup.gsql`: comment on the Document-vs-EventRow shape divergence under `results`.

---

## Recommendations (ranked by impact)

1. **Fix the AD-15 disambiguation path.** Change `_resolve_venue` to return `(None, candidates)` on ambiguous multi-match instead of `(best, candidates)`, and wire `resolved_anchors.disambiguation_candidates` through to `should_stop(has_disambiguation_candidates=...)` in `orchestrator.py`. This restores a named, MUST-level architecture decision (AD-15) and the risk mitigation for 23% of venue questions. Fix the masking test (`test_entity_linking.py:117`) to assert unconditionally.
  - **[RESOLVED]** see `entity_linking.py`, `orchestrator.py`, `test_entity_linking.py` notes above.
2. **Guard `batch_runner._run_one` and add `return_exceptions=True` to the `asyncio.gather` in `run_batch`.** One bad record currently can void an entire scored benchmark run — this is the metric the whole submission is judged on (APPLICATION-SPEC §7 success criterion: "zero silent failures").
  - **[RESOLVED]** see `batch_runner.py` note above.
3. **Implement `POST /batch`** in `api/main.py`, delegating to the existing `batch_runner`. Currently a hard FR-13 gap — the frontend and any judge-facing tooling cannot trigger a batch run without the CLI.
  - **[RESOLVED]** present since `dbfe5ee`; see `api/main.py` note above.
4. **Log and surface the embedding-model fallback** in `common/embeddings.py` (at minimum a `logger.error`; ideally propagate a flag into `run_config`/`PipelineRecord` so a silent semantic-search degradation isn't invisible in results).
  - **[RESOLVED]** logged + `embedding_backend` in `run_config`; see `embeddings.py` note above.
5. **Cache the per-run `EntityLinker`/vocabularies and LLM client** instead of rebuilding them every query in `_prepare_run` — real latency/resource cost across a 150-question batch and a live demo.
  - **[RESOLVED]** see `_prepare_run` note above.
6. **Fix the frontend accessibility gaps** UI-SPEC §14 requires fixed (keyboard-operable eval rows, `aria-live` region, chart tooltip fallback) and add tests for `BuildView`'s reducer and `Dashboard`'s mean-of-ratios — both are spec-load-bearing and currently unverified by any test.
  - **[RESOLVED]** see Frontend notes above.
7. **Minor hardening batch**, lower priority: `secrets.compare_digest` for the API key check, widen the secret-leak regex beyond `sk-...`, wire `OGR_STREAM_TOKEN_TTL_S` into `StreamTokenStore`, guard the Dashboard's ratio division by zero, add per-pipeline try/except to `cli.py ask`.
  - **[RESOLVED]** all five done; see `security.py`, `store.py`, `api/main.py:56`, `Dashboard.tsx`, `cli.py` notes above.
