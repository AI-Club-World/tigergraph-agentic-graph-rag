# APPLICATION-SPEC.md
Agentic GraphRAG Hackathon — Three-Pipeline Comparison System

Status: **v0.4 — synchronised with the code on `application-integration`, 2026-09-27.** | Standard basis: IEEE 29148 (requirements), EARS notation

FR-/NFR- IDs are stable: the code cites them. Architecture and decisions: [ARCHITECTURE-SPEC.md](ARCHITECTURE-SPEC.md). Contracts, schema and API: [TECHNICAL-SPEC.md](TECHNICAL-SPEC.md). Screens: [UI-SPEC.md](UI-SPEC.md). Embedding models: [EMBEDDING-SWITCHING.md](EMBEDDING-SWITCHING.md). Running and deploying: [README.md](../README.md), [DEPLOY.md](DEPLOY.md).

---

## 1. Purpose

| Field | Value |
|---|---|
| Problem | No single view compares RAG vs GraphRAG vs Agentic GraphRAG answer quality, evidence and cost on the same query |
| Domain / corpus | Wikipedia Olympic results archive: 2,951 docs, 5,466,414 tokens, CC BY-SA 4.0. Olympic events span 1900–2022 across 21 Games. 73.3% Olympic event infoboxes (2,162), 18.5% film (546), 8.2% other (243). Further datasets can be uploaded and built alongside it |
| Question types | lookup, multi_hop, temporal, aggregation, superlative — 100 public eval questions (verified answers), 50 hidden |
| Solution | One query input, three pipelines run in parallel, results side by side with a cost/accuracy verdict; a batch harness and dashboard over the eval sets |
| Research thesis | Aggregation/superlative questions need exhaustive enumeration over a scoped set — a structural ceiling for top-k retrieval. Routing between cheap and agentic paths follows the parsed operation type, not a learned classifier |
| Primary use | Live demo to hackathon judges; batch harness for the required metrics dashboard |
| Out of scope | Multi-turn conversation; multi-user accounts (one shared API key); Person/NOC entity vertices (§3); Round-2 reasoning over evolving or conflicting facts (see ARCHITECTURE-SPEC, Known limitations) |

## 2. Stakeholders

| Role | Concern |
|---|---|
| Judges | Investigation accuracy, evidence quality, agentic effectiveness, engineering quality, innovation, presentation (per rubric) |
| Team (dev) | Debuggability of agent behaviour |
| Operator | Choosing LLM provider/model and embedding model, loading datasets, running benchmarks without restarting the server |
| Batch runner (non-human actor) | Same execution path, headless, over 100 known + 50 hidden questions |

## 3. Scope decisions (resolved, with basis)

| Decision | Resolution | Basis |
|---|---|---|
| Gold documents outside the Olympic subset? | No — 547/547 gold references are Olympic infoboxes | Verified against `eval_public.jsonl` × corpus |
| Embedding model | Five selectable models (`bge-large-en-v1.5` default, `qwen3-embedding-0.6b`, `embeddinggemma-300m`, `gte-large-en-v1.5`, `mxbai-embed-large-v1`), each with its own TigerGraph vertex type and HNSW index; at most two stored. `bge-large-en-v1.5` is served by Cloudflare Workers AI (CLS pooling) when configured, otherwise locally; the others locally | Lets the operator compare models without mixing embedding spaces (EMBEDDING-SWITCHING.md) |
| Vector store | TigerGraph only (Savanna or Community Edition 4.2+) | Hackathon eligibility; no external index |
| Venue modelling | Venue as vertex, not secondary index | 303 venues; ~23% of venue+date pairs non-unique — needs traverse-then-disambiguate |
| Person/NOC vertices + `WON_MEDAL` edges | Cut — medallists are attributes on the event | No question type traverses person→events |
| Intent extraction | Function-calling (or JSON-schema prompting when unsupported) with schema validation + one retry | Structural reliability without grammar-constrained decoding |
| Necessity routing | Rule on parsed operation type, not a trained classifier | A classifier trained on 100 questions overfits |
| Accuracy scoring | Deterministic EM/F1 against gold — no LLM judge | Gold answers exist and are verified |
| Authentication | `X-API-Key` on every data route; single-use stream tokens for SSE. The frontend's key is compiled into its bundle and is not a secret, so the backend must run on a trusted network | Protection against casual access, not a determined attacker |
| Query history | Persisted: every query, build and benchmark trial in `out/history.jsonl` (History screen); benchmark runs as JSONL files (Dashboard run picker) | Replay and audit of what was run |
| Datasets | JSONL datasets can be uploaded, renamed (display title) and built; the graph keeps every loaded dataset; rebuilding one requires confirmation | Multiple corpora without resetting the graph |
| Runtime settings | LLM provider (presets `gemini`, `nvidia_nim`, `groq`) and model, and the active embedding model, change at runtime without a restart; keys stay in the server environment | Switching models between runs without code or config edits |
| Batch resume | A rerun skips questions already written; a failed question is left unwritten and retried | A partial run is recoverable |

## 4. Functional requirements (EARS notation)

| ID | Requirement |
|---|---|
| FR-1 | The system shall accept a single free-text query via one input field |
| FR-2 | Upon submission, the system shall invoke the RAG, GraphRAG and Agentic GraphRAG pipelines concurrently |
| FR-3 | While any pipeline is running, the system shall render that pipeline's column in a running state independent of the other two |
| FR-4 | When a pipeline completes, the system shall render its answer, evidence/citations, tokens used and latency in its column |
| FR-5 | While the Agentic GraphRAG pipeline is running, the system shall append each investigation step to a visible trace panel as it occurs |
| FR-6 | If the orchestrator deviates from its initial route (a fallback, or an empty direct lookup escalated into the loop), the system shall mark that step as a strategy change in the trace |
| FR-7 | When the Agentic GraphRAG pipeline stops, the system shall display the stop reason from the closed vocabulary (`sufficient_evidence`, `step_budget_exhausted`, `token_budget_exhausted`, `no_further_action_available`, `disambiguation_required`, `error`, `direct_route`) |
| FR-8 | When all three pipelines have completed, the system shall compute and display a verdict strip showing token multipliers (Agentic ÷ RAG, Agentic ÷ GraphRAG) and accuracy delta (EM/F1-based) where ground truth is available |
| FR-9 | Where ground truth is not available for a query, the verdict strip shall display "N/A" for accuracy delta rather than omit the field |
| FR-10 | Every rendered answer shall include citations traceable to source chunks or graph entities, scorable as a set against `gold_doc_ids` |
| FR-11 | The system shall route each query by parsed operation type: LOOKUP with fully-specified anchor → direct single-query path (no agent loop); COUNT/ARGMAX → one scoped aggregation query; TRAVERSE or underspecified anchor → multi-step agentic loop. Fully-specified ⇔ (`anchor.title` or `anchor.event_id` non-null) and `target_field` non-null and `constraints` empty. A direct lookup that returns nothing shall escalate into the loop |
| FR-12 | The intent parser shall emit a constrained schema — operation, anchor, constraints, target_field — via LLM function-calling (JSON-schema prompting where the model lacks it), validated with one retry on schema failure |
| FR-13 | The system shall expose the same pipeline-invocation and metrics-capture logic in a headless batch mode, callable without the UI (`ogr.cli batch`, `POST /batch`) |
| FR-14 | In batch mode, the system shall accept a list of questions and produce one structured record per question per pipeline, scored by EM, F1, precision, recall and completeness (= recall) over the returned document set against `gold_doc_ids` |
| FR-15 | The system shall run against the 100 known and the 50 hidden evaluation questions, producing metrics-dashboard input for both, broken out per question type |
| FR-16 | The system shall support a hand-authored paraphrase set (15 questions, same intents via different surface forms) as a generalization check, distinct from the scored eval sets |
| FR-17 | Every pipeline shall return a structured answer `{answer, explanation}` from a prompt identical across pipelines apart from retrieved context; EM and F1 shall score `answer` only |
| FR-18 | The LLM shall be selectable without code change: at startup by configuration (provider, model, base URL, API key; native Gemini/Claude or any OpenAI-compatible endpoint) and at runtime from the Settings panel (provider presets `gemini`, `nvidia_nim`, `groq` with live model lists). One LLM serves all three pipelines within a query or batch run |
| FR-19 | All data routes shall require an API key supplied by configuration; SSE routes shall use a short-lived single-use stream token, since `EventSource` cannot send headers. Unauthenticated routes are limited to `/health`, `/health/db`, `/health/llm`, `/health/embedding` and `GET /settings`, none of which return secrets |
| FR-20 | The metrics dashboard shall present both an aggregate benchmark view and a per-question table covering all evaluation questions across all three pipelines, with a "pipelines disagree" filter and trace drill-down |
| FR-21 | The system shall let the operator upload a JSONL dataset, rename its display title, and build it into the graph alongside datasets already loaded; building an already-built dataset shall require an explicit rebuild |
| FR-22 | The system shall let the operator switch the active embedding model; a switch to a model that is not fully embedded shall require an explicit choice between replacing and keeping parallel indices, and a query whose selected model is not complete shall be refused with the list of models that are |
| FR-23 | The system shall record every query, build and benchmark attempt (including refused ones) and show them in a History view |
| FR-24 | When a batch run is restarted with the same output file, the system shall skip questions already written and run only the rest |

## 5. Non-functional requirements

| ID | Requirement | Rationale |
|---|---|---|
| NFR-1 | Pipeline calls shall execute concurrently, not sequentially | Latency comparison is only meaningful without serial waits |
| NFR-2 | Failure or timeout in one pipeline shall not block rendering of the other two | Demo resilience. Exception by design: an LLM rate limit past the retry threshold stops the run and names the provider/model |
| NFR-3 | Token and time capture shall be instrumented at the pipeline-invocation layer, every model call through one accounting function | Trace data is judged; per-step tokens must sum to the record total |
| NFR-4 | Batch output shall be reproducible: embedding model and backend, LLM and run parameters logged per run, runnable end to end via `make reproduce` | Reproducibility is a rubric item |
| NFR-5 | UI and batch mode shall share one dispatcher and one aggregator implementation | No drift between demo and submitted metrics |
| NFR-6 | Evaluation scoring shall be deterministic, run-to-run identical for identical inputs | No LLM in the scoring loop |
| NFR-7 | No question-template regex and no read of `qtype` shall appear in the answer path | Anti-overfitting: routing goes through the constrained intent schema |

## 6. User stories

| ID | Story | Acceptance |
|---|---|---|
| US-1 | As a judge, I submit one query and see three answers side by side | FR-1, FR-2, FR-4 |
| US-2 | As a judge, I see how much more the agentic approach cost in tokens/time | FR-8 |
| US-3 | As a judge, I can inspect why the agent took each step and why it stopped | FR-5, FR-6, FR-7 |
| US-4 | As a judge, I can see an aggregation question where top-k retrieval is wrong at any k and the agentic path is exact with full citations | FR-10, FR-11 |
| US-5 | As a judge, I can see a simple lookup where the agentic path is correct but costs more tokens for no accuracy gain | FR-8, FR-11 |
| US-6 | As the team, we run the same logic in batch to produce the dashboard without rebuilding pipelines | FR-13, FR-14, FR-15, FR-24 |
| US-7 | As an operator, I switch LLM or embedding model and load another dataset without restarting the server | FR-18, FR-21, FR-22 |

## 7. Success criteria

| Criterion | Target |
|---|---|
| Concurrent execution demonstrated live | 3 columns visibly populate independently |
| Verdict strip present for every query | 100% of demo queries |
| Trace completeness | Every agentic run shows steps, tool calls, tokens, stop reason |
| Batch coverage | 100 known + 50 hidden questions fully processed, zero silent failures |
| Structured-query solvability (measured against the corpus, pre-agent) | aggregation 21/21, superlative 10/10, lookup 19/19, multi_hop 27/28, temporal 18/22 |
| Per-qtype metrics reported | EM, F1, precision, recall, completeness — each by all 5 question types |
| Generalization check | Paraphrase set answered through the same intent schema, not template-matched |
| Reuse | 0 duplicated pipeline-invocation logic between UI and batch mode |
| Accuracy floor | P3 EM ≥ 0.85 overall; ≥ 0.90 on aggregation, superlative and lookup |
| Thesis criterion | P3 − P1 EM gap on aggregation ≥ 0.50 |
| Cost-honesty criterion | At least one qtype reported where P3 is *not* worth its token multiplier |

These targets have not yet been measured against a live TigerGraph and LLM.

## 8. Dependencies

| Dependency | Notes |
|---|---|
| TigerGraph Savanna (or Community Edition 4.2+) | Graph + vector store; vector search (`vectorSearch`, HNSW) required |
| LLM provider | Intent parsing, P3 groundedness check, generation. Keys from the server environment only |
| Embedding host | Cloudflare Workers AI (`CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`) for `bge-large-en-v1.5` and the P3 reranker; local `sentence-transformers` weights for the other models (EmbeddingGemma needs Hugging Face licence acceptance) |
| Provided dataset | Corpus (`data/corpus/`), 100 known questions (`data/questions/eval_public.jsonl`), 50 hidden (`acceptance/holdout/eval_hidden.jsonl`; field names `qid` / `question` / `qtype`) |

## 9. Open questions

| Question | Status |
|---|---|
| Ground-truth scoring method | **Resolved** — deterministic EM/F1 (SQuAD-style normalization), no LLM judge |
| Persisted query history | **Resolved** — implemented (FR-23); batch records additionally replay every scored question |
| Multi-person answer scoring | **Resolved** — split on lowercase→uppercase boundaries with a prefix guard (`Mc`, `Mac`, `O'`, `Di`, `De`, `Van`, `Le`, `La`); the unguarded rule mis-splits `Rosannagh MacLennan` (pub-067). Genuine concatenations are pub-015 and pub-099 |
