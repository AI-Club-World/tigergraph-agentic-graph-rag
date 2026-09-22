# AUDIT.md — RAG (P1) and Agentic GraphRAG (P3) implementation audit

**Date**: 2026-09-22
**Code root**: `F:\Hackathon\GitHub` (branch `feature/implementation-rag`)
**Audit scope**: the RAG pipeline (P1) and the Agentic GraphRAG pipeline (P3). P2/GraphRAG, ingestion, eval/scorer, API and frontend are out of scope.

**Specs read (in full)**

| Spec | Role |
|---|---|
| `implementation-plan-RAG.md` (PLAN-002) | Primary — RAG section |
| `implementation-plan-AGENT.md` (PLAN-003) | Primary — Agentic RAG section |
| `BUILD-PLAN.md` | Task table RAG-01/02, AGENT-01…08, CORE-02, LLM-01, PLAT-06/07/08. Wins over TECHNICAL-SPEC on conflict (TECHNICAL-SPEC header) |
| `TECHNICAL-SPEC.md` | §1 stack, §3 query library, §6 record contract, §7 intent schema, §8.1/§8.3 pipeline contracts, §9, §11, §14 |
| `ARCHITECTURE-SPEC.md` | §3 components, §4 seven agents, §5 necessity routing, §8 runtime view, AD-1…AD-15 |
| `APPLICATION-SPEC.md` | FR-2/4/5/6/7/10/11/12/16, NFR-1/2/3/6/7 |
| `implementation-plan-GRAPH.md`, `implementation-plan-UI.md` | Read for interface obligations only; not audited |

### Check commands and results

| Check | Command | Initial | Final |
|---|---|---|---|
| Tests | `python -m pytest -q` (in `backend/`) | **12 failed, 75 passed** | **104 passed** (87 existing + 17 new) |
| Import check | walk `ogr.*`, import every module | **27/27 OK** | **27/27 OK** |
| Compile check | `python -m compileall -q src tests` | **clean** | **clean** |
| Lint | — | **none present** (no ruff config, no `.github/workflows/` in repo) | none present |
| Anti-overfitting grep (PLAN-003 Verification) | `grep -rn "qtype\|pub-NNN\|eval-NNN" src/` | **PASS** — comments/docstrings only, no runtime read | **PASS**, now enforced by test |
| Holdout grep (BUILD-PLAN §2) | `grep -rn "acceptance/holdout" src/ tests/` | **PASS** — no references | **PASS** |

All 12 initial failures had a single root cause: `langchain`, `langchain_core` and `langgraph` are the fixed stack (TECHNICAL-SPEC §1, BUILD-PLAN §1) but were **not declared in `backend/pyproject.toml`**, which declared only `pydantic` and `python-dotenv`. Modules still imported cleanly because every LangChain/LangGraph import is lazy (inside a function body).

No live external service was contacted at any point. All pipeline tests run against mocked LLM objects and an offline `TigerGraphClient(mock_chunks=...)`.

---

## RAG (P1) — checklist

| # | Spec item | Spec ref | Initial | Final | Evidence | Notes |
|---|---|---|---|---|---|---|
| R1 | Chunk 300 / overlap 50 / `k=10`, recorded in `run_config` | PLAN-002 DP-1 A | DONE | DONE | `backend/src/ogr/common/config.py:19-21` | Env-overridable, defaults exactly as selected. |
| R2 | P1 retrieves over Chunks only, all 2,951 docs, no type filtering | PLAN-002 DP-2 A | DONE | DONE | `p1_rag.py:71-76` | `vtype="Chunk"`, `candidate_set=None`. |
| R3 | Shared answer contract `{answer, explanation}`, prompt byte-identical to P2/P3 | PLAN-002 G1; CORE-02; PLAT-06 | DONE | DONE | `contracts.py:61-74`; `p1_rag.py:87`; `orchestrator.py:313` | Both P1 and P3 call the one `invoke_llm_with_answer_contract`, so byte-identity holds by construction. |
| R4 | Q5 with `vtype="Chunk"`, `k` from run_config, no candidate_set / predicate / re-rank / threshold | PLAN-002 G1; AD-9 | DONE | DONE | `p1_rag.py:71-76`; `graph/client.py:52-103` | No filtering applied to results anywhere in the path. |
| R5 | Single LLM generation call | PLAN-002 G1; §8.1 | DONE | DONE | `p1_rag.py:86-91` | Exactly one `invoke`. |
| R6 | Citations: `source_id` = parent `doc_id`, `chunk_id` retained for display | PLAN-002 G1; PLAN-004 DP-1 | DONE | DONE | `p1_rag.py:104-115`; `client.py:124-127` | Parent resolved in Q5 normalisation. |
| R7 | `chunks_returned` and `citations_count` populated | PLAN-002 G1 | DONE | DONE | `p1_rag.py:77,115,124-125` | |
| R8 | Token/latency capture at the invocation layer, **not estimated post-hoc** | PLAN-002 G1; NFR-3; §11; PLAT-08 | **PARTIAL** | DONE | was `llm.py:100-105`; now `llm.py:_count_tokens_with_model_tokenizer` | The `local_tokenizer` branch estimated `len(chars)//4` while labelling the result `local_tokenizer`. §11 forbids estimation and PLAT-08 requires "the model's tokenizer". Now uses `model.get_num_tokens()`; falls back to `token_source="estimated"` only when the model exposes no tokenizer, so a guess is never labelled as a count. |
| R9 | Guard test: no candidate_set, no filter, no re-rank; non-Olympic chunks in index; no retriever imports | PLAN-002 G2; RAG-02; AD-9 | DONE | DONE | `tests/pipelines/test_p1_unfiltered.py:35,72,93` | 3 tests, all passing. Left untouched. |
| R10 | README states P1 is unfiltered by design and why | PLAN-002 G2; DOC-02 | DONE | DONE | `README.md:3-5` | |
| R11 | `pytest backend/tests/pipelines/test_p1.py` green | PLAN-002 Verification | **BROKEN** | DONE | `test_p1.py` 5/5 | 2 failed initially on the undeclared `langchain` dependency. |
| R12 | `python -m ogr.cli ask … --pipelines rag` | PLAN-002 Verification | DONE | DONE | `cli.py:42-44` | Wired. Not executed live — needs an LLM endpoint (out of scope per constraints). |
| R13 | LangChain declared as a dependency (generation call only) | PLAN-002 Stack; TECHNICAL-SPEC §1 | **MISSING** | DONE | `pyproject.toml:11-22` | See A19 — one shared fix. |

## Agentic GraphRAG (P3) — checklist

| # | Spec item | Spec ref | Initial | Final | Evidence | Notes |
|---|---|---|---|---|---|---|
| A1 | "Fully-specified anchor" predicate: (`title` or `event_id`) ∧ `target_field` ∧ no constraints | PLAN-003 DP-1 A; FR-11 | DONE | DONE | `router.py:32-42` | Exactly the selected rule. |
| A2 | Necessity routing LOOKUP-direct / scoped-aggregate / loop | PLAN-003 G1; ARCH §5; AD-5 | DONE | DONE | `router.py:45-67`; tests `test_router.py` | |
| A3 | Intent schema `{operation, anchor, constraints, target_field}`, Pydantic-validated, **one** retry | PLAN-003 G1; FR-12; §7 | **BROKEN** | DONE | `intent.py:63-68,178-195` | Logic correct (`range(2)` = one retry); 8 tests failed only on the undeclared dependency. |
| A4 | Two extraction paths (native tool-calling / JSON-schema), identical output, path recorded | PLAN-003 G1; PLAT-08; AD-13 | PARTIAL | DONE | `intent.py:197-234`; `llm.py:resolve_tool_calling_support` | Both paths existed, but the selector was a hard boolean: `config.py` parsed `LLM_SUPPORTS_TOOL_CALLING` as `== "true"`, so `env.example`'s documented `auto` silently meant *false* and the native path was unreachable. Now `auto\|true\|false` with an offline capability probe. |
| A5 | `qtype → operation` documented; `qtype` never read at runtime; no regex/template branching | PLAN-003 G1; NFR-7 | DONE | DONE | `intent.py:16-25`; grep PASS | Now enforced by `test_anti_overfitting.py`. |
| A6 | Entity linking: longest-match over closed vocabularies, built at startup from the graph | PLAN-003 G2; ARCH §4 | DONE | DONE | `entity_linking.py:105-157`; `orchestrator.py:509-516` | Vocabularies loaded via `client.get_vocabulary`. |
| A7 | Dates normalised via the shared `common/dates.py` (no second normaliser) | PLAN-003 G2; GRAPH-03 | DONE | DONE | `entity_linking.py:60,138-147` | Single normaliser confirmed; no duplicate found. |
| A8 | Unresolved anchors returned explicitly, not guessed (the `eval-001` case) | PLAN-003 G2; DP-2 | DONE | DONE | `entity_linking.py:123-136,210-229`; `test_entity_linking.py` | |
| A9 | Five tool agents (Q4, Q5, HAS_CHUNK, Q2/Q3, Q4→Q1) each returning a uniform `AgentResult` | PLAN-003 G3; ARCH §4 | DONE | DONE | `agents/{graph_traversal,similarity_search,document_retrieval,aggregation,multi_hop}.py`; `agent_result.py:13-29` | `test_agents.py` conformance passing. |
| A10 | Evidence evaluator: deterministic scope gate + one labelled LLM groundedness call | PLAN-003 G4; DP-4 A; ARCH §3 | DONE | DONE | `evidence.py:69-116,156-205` | |
| A11 | Evaluator surfaces the `parse_confidence` exclusion count | PLAN-003 G4 | DONE | DONE | `evidence.py:208-216`; `aggregation.py:79-80` | |
| A12 | README states no LLM sits in the **scoring** path | PLAN-003 DP-4 A | **MISSING** | DONE | `README.md` "Where the LLM is, and is not" | DP-4 makes this README statement part of the decision; it was absent. |
| A13 | DP-2 fallbacks: scope fail → Q5; groundedness/empty anchor → HAS_CHUNK; each sets `strategy_change` | PLAN-003 DP-2 A | DONE | DONE | `orchestrator.py:256-283`; `similarity_search.py:79`; `document_retrieval.py:72` | Both otherwise-unreachable agents are reachable. |
| A14 | Stopping: sufficiency or budget; closed `stop_reason` vocabulary | PLAN-003 G4; DP-3 A; FR-7; AD-3 | DONE | DONE | `stopping.py:36-97`; `config.py:50-55` | The evaluator itself is correct; its *inputs* were not — see A18. |
| A15 | Strategy-change detector derives `strategy_changed` from `path_taken` vs `route_initial` | PLAN-003 G4; FR-6 | DONE | DONE | `strategy.py:32-79`; `orchestrator.py` `node_generate` | Derived, not set imperatively. Correctness depended on A18. |
| A15b | DP-2: each fallback sets `strategy_change: true` on its step | PLAN-003 DP-2 A; FR-6; ARCH §3 | **BROKEN** *(found while fixing A17)* | DONE | `trace.py:record`; `similarity_search.py:79`; `document_retrieval.py:72` | The fallback agents set `strategy_change=True` on their `AgentResult` — `test_agents.py:66,74,86` assert exactly that — but `TraceRecorder.record` overwrote the flag with a route-based verdict, and `ROUTE_TO_EXPECTED_TOOLS["loop"]` lists both fallbacks as expected. The agents' signal was therefore discarded and no fallback was ever flagged. Now OR-ed: route deviation **or** the agent's own declaration. `strategy.py` and its tests are untouched. |
| A15c | Bookkeeping steps must not be reported as strategy changes | FR-6 | **BROKEN** *(introduced by A20, caught before commit)* | DONE | `trace.py:record(path_name=…)` | `TraceRecorder` appended `agent_type` ("entity_linking", "evidence_evaluation") into `_path_taken`, then judged it against `ROUTE_TO_EXPECTED_TOOLS`, which is keyed on *path* names ("lookup", "traversal", …). Harmless while only tool steps were recorded; once the intent parse became a step (A20) it was flagged as a deviation on step 1 — a false positive in a judged metric (strategy-change frequency). Route-based detection now applies only to steps that supply a `path_name`. |
| A16 | `TraceStep` emitted with `chunks_returned` and `citations_count` | PLAN-003 G4; PLAN-004 DP-1; FR-5 | DONE | DONE | `trace.py:83-98` | |
| A17 | **Token reconciliation**: Σ `TraceStep.tokens` == record total, asserted | PLAN-003 DP-5 A; BUILD-PLAN §7; NFR-3 | **BROKEN** | DONE | was `trace.py:106-114,129-145` + `orchestrator.py:369-376`; now `trace.py:record_llm_generation/reconcile_assert` | Two independent defects, both demonstrated: (1) `record_llm_generation` added generation tokens to the record total but emitted **no** `TraceStep`, so Σ steps could never equal the total (measured 120 vs 5,520); (2) the orchestrator passed `cumulative_tokens().total` into `reconcile_assert`, which then compared that value **against itself** — ratio always 1.0, so the guard DP-5 calls "non-negotiable" could never fire. Generation is now its own `TraceStep` and the assertion compares Σ steps against the record total. |
| A18 | `path_taken` is an **append-only reducer**; typed state object | PLAN-003 G5 | **BROKEN** | DONE | was `orchestrator.py:50-67` (unused) + `:434` `StateGraph(dict)`; now `OrchestratorState` + `Annotated[..., add]` | `OrchestratorState` was declared but never used; the graph ran on `StateGraph(dict)`, where returning `{"path_taken": [x]}` **replaces** rather than appends (verified directly against LangGraph). Consequence below. |
| A19 | The loop terminates within budget on every question | PLAN-003 Stop conditions; DP-3; AD-3 | **BROKEN** | DONE | reproduction in "Spec conflicts and gaps" | Direct consequence of A18 + uncounted loop tokens: `step_count = len(path_taken)` oscillated 1↔2 and never reached `max_steps=6`, while `tokens_used` stayed 0 because the groundedness LLM call's tokens were never captured. **Both budgets were inert.** A TRAVERSE question with unsatisfiable evidence ran **10,007 iterations** and died on LangGraph's recursion limit with `stop_reason="error"`. |
| A20 | Every model call goes through the one accounting module, attributed to a `step_n` | PLAN-003 DP-5 A; NFR-3 | **PARTIAL** | DONE | `evidence.py:179`, `intent.py:210,228` called `model.invoke` directly | Intent-parse and groundedness tokens were invisible to the cost axis — the exact "agentic path looks free" failure DP-5 names. Both now go through `llm.invoke_and_count` **and** are recorded as their own `TraceStep`, because DP-5 requires each figure be attributed to a step, not merely summed. |
| A21 | Usage-on-stream explicitly enabled | PLAN-003 DP-5 A | **MISSING** | DONE | `llm.py:get_chat_model` `stream_usage=True` | LangChain omits usage when streaming unless asked. |
| A22 | LangGraph `StateGraph` implementing the ARCH §8 runtime view; nodes + conditional edges | PLAN-003 G5; §8.3 | DONE | DONE | `orchestrator.py:436-475` | Node and edge topology matches the spec. |
| A23 | **LOOKUP traverses zero loop edges** | PLAN-003 G5; G4 gate; US-5 | **BROKEN** | DONE | `orchestrator.py:459-460`; `test_orchestrator.py:169` | Topology was always correct (`lookup_direct → generate`); the verifying test failed on the undeclared dependency. |
| A24 | Emits `PipelineRecord` with full trace, `strategy_changed`, `stop_reason` | PLAN-003 G5; §6.2 | **BROKEN** | DONE | `orchestrator.py:378-393` | Failed initially on the dependency; also under-reported tokens (A17/A20). |
| A25 | One trace emitter, two consumers (live stream + batch array), built on `astream_events` | PLAN-003 G4; AD-1; AD-2 | **PARTIAL** | DONE | `orchestrator.py:astream_p3_agentic`; `trace.py:TraceRecorder(on_step=…)`; `test_trace_stream.py` | `astream_p3_agentic()` drives the compiled graph with LangGraph `astream_events` and yields each `TraceStep` as its node completes, then the `PipelineRecord` last. The `TraceRecorder` remains the single emitter feeding both. `test_one_emitter_two_consumers` asserts the streamed steps and the record's `trace` array are identical, which is the property AD-1/AD-2 actually care about; `test_stream_matches_the_sync_run` asserts streaming changes neither the answer, the stop reason nor the cost. The HTTP/SSE endpoint that will consume this is still `API-01`/PLAN-004 and out of scope, but the generator it consumes now exists and is tested. |
| A26 | Paraphrase generalization set, ~15 entries | PLAN-003 G5; AGENT-08; FR-16 | DONE | DONE | `acceptance/paraphrase/paraphrase_set.jsonl` (15 lines) | 6 tests passing. |
| A27 | Anti-overfitting review "gets a command, not an intention" | PLAN-003 Verification | **MISSING** | DONE | `tests/pipelines/p3/test_anti_overfitting.py` | The grep passed when run by hand but nothing enforced it. Now three tests. |
| A28 | `python -m ogr.cli ask … --pipelines agentic --show-trace` | PLAN-003 Verification | **MISSING** | DONE | `cli.py` | The CLI only knew `rag`; `agentic` printed "not yet implemented" and `--show-trace` did not exist. |
| A29 | LangGraph / LangChain / pyTigerGraph declared as dependencies | PLAN-003 Stack; TECHNICAL-SPEC §1; BUILD-PLAN §1 | **MISSING** | DONE | `pyproject.toml:11-22` | Root cause of all 12 initial failures. |
| A30 | No `GraphCypherQAChain` / text-to-GSQL; dispatch stays `operation → Q1–Q5` | PLAN-003 Research; BUILD-PLAN §7 | DONE | DONE | grep: no occurrence in `src/` | Now covered by `test_anti_overfitting.py`. |

---

## Spec conflicts and gaps

**1. `pyproject.toml` contradicted the fixed stack (resolved).**
TECHNICAL-SPEC §1 and BUILD-PLAN §1 fix the backend stack as Python 3.11 · FastAPI · `sse-starlette` · LangGraph/LangChain · pyTigerGraph, with `sentence-transformers` for embeddings. `backend/pyproject.toml` declared only `pydantic` and `python-dotenv`. Resolution: declared the dependencies the audited modules actually import (`langchain-core`, `langchain-openai`, `langgraph`, `pyTigerGraph`, `sentence-transformers`). FastAPI and `sse-starlette` are **not** added — no module in scope imports them, and API-01 is not on this branch.

**2. The two loop budgets were both inert — the headline defect (resolved).**
PLAN-003 lists "the loop fails to terminate within budget on any question" as a stop condition. Reproduced before the fix, with a TRAVERSE question whose groundedness check always fails:

```
status      : error
stop_reason : error
error_detail: Recursion limit of 10007 reached without hitting a stop condition
trace steps : 0
```

Two causes, both now fixed: `path_taken` replaced instead of accumulating (A18), so the step budget never armed; and the loop's only LLM call was made outside the accounting module (A20), so the token budget never armed either. `stopping.py` itself was correct throughout — it was being fed constants.

After the fix, the same question:

```
status      : done
stop_reason : step_budget_exhausted
trace steps : 11
sum(TraceStep.tokens) == record total -> True
```

and with a satisfiable groundedness check it stops on `sufficient_evidence` in 7 steps — AD-3's primary signal, with the budget as the safety valve rather than the only exit. Both paths are pinned by `test_loop_budget.py`.

**2b. DP-2 "each fallback sets strategy_change" vs `strategy.py`'s route-based table (resolved in favour of DP-2).**
`ROUTE_TO_EXPECTED_TOOLS["loop"]` lists `similarity_search` and `document_retrieval` as expected tools, so under the route-based detector a fallback inside a `loop` run is not a deviation — and `test_loop.py:210-218` pins that behaviour. DP-2 Option A says the opposite: "Each fallback sets `strategy_change: true`". FR-6 and the ARCH §3 Strategy-Change Detector both describe "re-query after evidence check fails" as the deviation to mark, which is exactly when these fallbacks fire. Resolved per the conflict rule (prefer the more specific, explicitly-selected statement): the flag is now the OR of the route verdict and the agent's own declaration. `strategy.py` keeps its semantics and all its tests pass unchanged; only the recorder's combination logic changed. Without this, the strategy-change frequency chart would have read zero for every loop run.

**3. TECHNICAL-SPEC §11 "no estimation" vs PLAT-08's `local_tokenizer` fallback (resolved by reading them together).**
§11 forbids post-hoc estimation; PLAT-08 permits a `local_tokenizer` count where the provider reports nothing. The code satisfied neither: it estimated `len(chars)//4` and labelled it `local_tokenizer`. Resolution: use the model's own tokenizer via `get_num_tokens()` for the `local_tokenizer` label, and introduce a distinct `estimated` label for the residual case where the model exposes no tokenizer — so a guess is never presented as a count. **This widens the `token_source` enum** in TECHNICAL-SPEC §6.2 from `provider|local_tokenizer` to `provider|local_tokenizer|estimated`; flagged here because it touches the frozen record contract (CORE-01). The alternative — silently mislabelling an estimate — is the failure PLAT-08 exists to prevent.

**4. `DEFAULT_GAMES_VOCAB` holds 53 entries where the spec measured 21 Games (left as-is).**
`entity_linking.py:40-56` bundles 53 Games strings; PLAN-003 and ARCH §7 state 21 distinct Games values. This list is only a fallback for offline runs — at startup the vocabulary is loaded from the graph (`orchestrator.py:509`), which is authoritative. A superset cannot cause a false match against a corpus value that does not exist. Left unchanged: correcting a fallback constant to a number only the live graph can confirm would be inventing data.

**5. `stopping.py` returns `"sufficient_evidence"` as a sentinel when `stop=False` (left as-is).**
`stopping.py:97` returns a real vocabulary member alongside `stop=False`. It is documented as unused in that branch and every caller checks the boolean first. Changing it would touch a DONE module for no behavioural gain.

**6. `env.example` is at the repo root, not `backend/.env.example` (left as-is).**
BUILD-PLAN §1's layout places it at `backend/.env.example`. One template already exists and is complete; creating a second would be worse than the inconsistency. New variable names were added to the existing file.

**7. `LLM_REPORTS_TOKEN_USAGE` was documented but never read (resolved).**
`env.example` documents `auto|true|false`; `config.py` had no such field. Added, and honoured in the accounting module.

**Spec-silent details, minimal assumptions logged**
- PLAN-003 Group 4 requires the trace emitter to be "built on LangGraph `astream_events`". Implemented as an `on_step` subscriber callback rather than an `astream_events` wrapper: the second consumer (the SSE panel) is PLAN-004/API-01 and is not on this branch, so an async streaming interface here would have no caller and no test. Recorded as A25 PARTIAL rather than claimed as DONE.
- The tool-calling capability probe resolves `auto` by inspecting whether the model class overrides `bind_tools`, not by issuing a probe request. The constraints forbid live external calls, and an offline inspection is deterministic and reproducible.
- `--show-trace` output format is unspecified; it prints one line per `TraceStep` with step number, agent, tool, tokens, latency and a strategy-change marker, matching the `TraceStep` fields in §6.3.

---

## Changes made

| File | Change |
|---|---|
| `backend/pyproject.toml` | Declare the fixed stack: `langchain-core`, `langchain-openai`, `langgraph`, `pyTigerGraph`, `sentence-transformers`; require Python ≥3.11 per TECHNICAL-SPEC §1 (A29, R13). |
| `backend/src/ogr/common/config.py` | `llm_supports_tool_calling` becomes `auto\|true\|false`; add `llm_reports_token_usage` (A4, A21, gap 7). |
| `backend/src/ogr/common/llm.py` | Enable `stream_usage`; add `resolve_tool_calling_support()` offline probe; add `invoke_and_count()` as the single accounting entry point; replace the `chars//4` estimate with the model's tokenizer and add the honest `estimated` label (R8, A4, A20, A21). |
| `backend/src/ogr/common/contracts.py` | Widen `token_source` to include `estimated` (gap 3). |
| `backend/src/ogr/pipelines/p3_agentic/intent.py` | Route both extraction paths through `invoke_and_count` so intent-parse tokens reach the cost axis (A20). |
| `backend/src/ogr/pipelines/p3_agentic/evidence.py` | Groundedness call goes through `invoke_and_count`; return its token usage to the caller (A20). |
| `backend/src/ogr/pipelines/p3_agentic/trace.py` | `record_llm_generation` now emits a real `TraceStep`; `reconcile_assert` compares Σ `TraceStep.tokens` against the record total and returns a bool; add `trace_token_sum()`, the `on_step` subscriber, and the `path_name` parameter that separates tool steps from bookkeeping steps (A17, A15b, A15c, A25). |
| `backend/src/ogr/pipelines/p3_agentic/orchestrator.py` | Use the typed `OrchestratorState` with an append-only `Annotated` reducer for `path_taken`, `evidence` and `steps`; nodes now return only their own additions; record the intent parse and the evidence evaluation as trace steps; resolve tool-calling capability through the probe; pass `tools_tried` to `should_stop`; derive `strategy_changed` from the route comparison OR any flagged step (A15b, A17, A18, A19, A20, A24). |
| `backend/src/ogr/cli.py` | Add `--pipelines agentic` and `--show-trace` (A28). |
| `backend/src/ogr/pipelines/p3_agentic/orchestrator.py` *(follow-up pass)* | Add `astream_p3_agentic()` built on LangGraph `astream_events`; factor the shared setup into `_prepare_run()` and the two duplicated error blocks into `_error_record()` so the sync and streaming paths cannot diverge (A25). |
| `backend/tests/pipelines/p3/test_anti_overfitting.py` | **New.** Enforce the PLAN-003 verification greps: no runtime `qtype` read, no eval-set strings, no text-to-GSQL chain (A27, A30). |
| `backend/tests/pipelines/p3/test_loop_budget.py` | **New.** Regression tests for A18/A19: `path_taken` accumulates across loop iterations, and an unsatisfiable TRAVERSE question stops on `step_budget_exhausted` rather than the recursion limit. |
| `backend/tests/pipelines/p3/test_token_reconciliation.py` | **New.** Regression test for A17: Σ `TraceStep.tokens` equals the record total, and `reconcile_assert` warns on a genuine mismatch. |
| `backend/tests/pipelines/p3/test_trace_stream.py` | **New.** A25: the streamed steps equal the record's trace array, and streaming changes neither the answer, the stop reason nor the cost. |
| `README.md` | Add "Where the LLM is, and is not" — no LLM in the scoring path, one labelled groundedness call in the retrieval path (A12, DP-4). |
| `env.example` | Document `LLM_REPORTS_TOKEN_USAGE`; note `auto` is now honoured for `LLM_SUPPORTS_TOOL_CALLING`. |

No existing test was modified. No file outside the audited scope was edited.

## Status roll-up

| Status | Initial | Final |
|---|---|---|
| DONE | 24 | **43** |
| PARTIAL | 5 | 0 |
| BROKEN | 8 | 0 |
| MISSING | 6 | 0 |

**Every RAG and Agentic-RAG item in PLAN-002 and PLAN-003 is now DONE.** A25 was the last one open and closed in a follow-up pass: `astream_p3_agentic()` now drives the graph with LangGraph `astream_events` and yields `TraceStep`s live, with a test asserting the stream and the batch record carry identical steps.

---

## Follow-on work (beyond the RAG/Agentic-RAG audit scope)

Built after the audit closed, at the user's direction. Verified the same way — existing tests, ruff, import/compile checks, no live services.

| Task | Spec ref | Status | Evidence | Notes |
|---|---|---|---|---|
| Repo hygiene + CI guards | BUILD-PLAN §2 | DONE | `.gitignore`, `.github/workflows/ci.yml`, `pyproject.toml` `[tool.ruff]` | None of it existed. 39 `__pycache__/*.pyc` untracked (`--cached`, still on disk). Ruff clean over `src` and `tests`. Both guard checks wired: the holdout grep is scoped to source rather than the whole tree — the specs and this file discuss the holdout by name, and opening it from code is the thing being guarded — and was verified against a planted violation. The no-test-modified check requires an explicit `TEST-CHANGE:` marker. The frontend job self-skips when `package.json` is absent, since that module lives on `feature/initial-ui`. |
| `EVAL-01` name normalizer | PLAN-004 G1; §9 | DONE | `common/names.py`; `tests/eval/test_names.py` | SQuAD normalization plus the multi-person splitter. Every guarded prefix (`Mac`, `Mc`, `Van`, `Di`, `De`, `Le`, `La`, `O'`) has a test, and a guarded name still splits correctly when a second person is concatenated onto it. |
| `EVAL-02` scorer | PLAN-004 G1; §9; FR-14; NFR-6 | DONE | `eval/scorer.py`; `tests/eval/test_scorer.py` | EM and token F1 over the `answer` span only (PLAT-06), precision/recall/F1 over the returned document set, Completeness as the explicit recall alias (DP-2), per-qtype breakdown. No `@k` — undefined for P2/P3, which retrieve by traversal. No LLM in the path. F1 cases carry their arithmetic in the docstring so the expected value is checkable by eye. |
| `EVAL-03` dispatcher | PLAN-004 G2; FR-2; NFR-1; NFR-2 | DONE | `eval/dispatcher.py`; `tests/eval/test_dispatcher.py` | `asyncio.gather`, each pipeline in its own failure domain, never raises. Sync pipelines run in a worker thread so a blocking call cannot stall the loop and serialise the others — which would look concurrent in the code and not be. Asserted with a timing test, per PLAN-004's own manual step. |
| `EVAL-03` aggregator | PLAN-004 G2; FR-8; FR-9; NFR-5; AD-1 | DONE | `eval/aggregator.py`; `tests/eval/test_aggregator.py` | Token multipliers, EM-based accuracy deltas, literal `"n/a"` where no ground truth. Negative-delta and no-gain cases tested explicitly: a verdict that only ever flatters the agent would be a defect, not a good result. |
| `GRAPH-08` P2 pipeline | PLAN-GRAPH G4; §8.2; PLAT-07 | DONE | `pipelines/p2_graphrag.py`; `tests/pipelines/test_p2.py` | Shares P3's intent parser, then exactly one query — counted by a test, including the empty-result case where an evidence check would have fired a second. `trace`/`strategy_changed`/`stop_reason` stay null because P2 has no loop. P2's cost includes its intent parse; omitting it would credit P2 with a free parse P3 is charged for, and that ratio is what the cost argument rests on. |

**Final check results across the whole branch**: `pytest -q` → **185 passed**; `ruff check src tests` → **clean**; import walk → **33/33 OK**; `compileall` → **clean**. All three pipelines are reachable from the CLI (`--pipelines rag|graphrag|agentic`).

**Still out of scope, not built**: ingestion and the GSQL query library (`GRAPH-01…07`, `GRAPH-09`), the batch runner and record store (`EVAL-04`), the API (`API-01`), the frontend (`WEB-01…04`, which lives on `feature/initial-ui`), the hidden run (`HID-01`) and `make reproduce` (`REPRO-01`). The `out/` and `data/` directories from the BUILD-PLAN §1 layout do not exist on this branch, so no pipeline has been run against a real graph or a real LLM — every test here runs against mocks.

**Not verifiable offline** (left as-is, per the no-live-services constraint): the end-to-end `python -m ogr.cli ask …` runs against a real LLM endpoint and a live TigerGraph workspace; the G4 manual check ("one question per operation traced by hand") and the PLAN-002 manual lookup/aggregation pair both need those services. All pipeline logic is exercised against mocks instead.
