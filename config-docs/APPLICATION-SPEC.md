# APPLICATION-SPEC.md
Agentic GraphRAG Hackathon — Three-Pipeline Comparison System

Status: **v0.5 — synchronised with the code on `round-2`, 2026-11-14.** Round 1 is measured (§7); Round 2 is built and tested offline, not yet measured live (§10–§12). | Standard basis: IEEE 29148 (requirements), EARS notation

FR-/NFR- IDs are stable: the code cites them. Architecture and decisions: [ARCHITECTURE-SPEC.md](ARCHITECTURE-SPEC.md). Contracts, schema and API: [TECHNICAL-SPEC.md](TECHNICAL-SPEC.md). Screens: [UI-SPEC.md](UI-SPEC.md). Embedding models: [EMBEDDING-SWITCHING.md](EMBEDDING-SWITCHING.md). Round 2: [ROUND2-DESIGN.md](ROUND2-DESIGN.md), [ROUND2-RESULTS.md](ROUND2-RESULTS.md), [ROUND2-INTERVIEW-LOG.md](ROUND2-INTERVIEW-LOG.md). Running and deploying: [README.md](../README.md), [DEPLOY.md](DEPLOY.md).

---

## 1. Purpose

| Field | Value |
|---|---|
| Problem | No single view compares RAG vs GraphRAG vs Agentic GraphRAG answer quality, evidence and cost on the same query |
| Domain / corpus | Wikipedia Olympic results archive: 2,951 docs, 5,466,414 tokens, CC BY-SA 4.0. Olympic events span 1900–2022 across 21 Games. 2,187 documents (74.1%) are Olympic event pages with an infobox; the rest are other pages (films and others) that only RAG and the prose fallbacks read. Further datasets can be uploaded and built alongside it |
| Question types | lookup, multi_hop, temporal, aggregation, superlative — 100 public eval questions (verified answers), 50 hidden |
| Solution | One query input, three pipelines run in parallel, results side by side with a cost/accuracy verdict; a batch harness and dashboard over the eval sets |
| Research thesis (Round 1, measured) | Aggregation/superlative questions need exhaustive enumeration over a scoped set — a structural ceiling for top-k retrieval. Routing between cheap and agentic paths follows the parsed operation type, not a learned classifier. Result: Agentic EM 0.98 against RAG 0.59 at 40% of RAG's median tokens (§7) |
| Research thesis (Round 2, to be measured) | When facts change, sources disagree or statements are hedged, top-k retrieval hands the model several values and no rule for choosing. An agent that stores each statement as a claim (who said it, when, how firmly) can choose by an inspectable rule, keep the losing values as evidence, and say how sure it is. The extra work is a graph query and arithmetic, not extra LLM calls |
| Primary use | Live demo to hackathon judges; batch harness for the required metrics dashboard |
| Out of scope | Multi-turn conversation; multi-user accounts (one shared API key); Person/NOC entity vertices (§3); abstaining from an answer (Round-2 policy: always commit to one answer with a confidence); claims read from free prose by an LLM (allowed by gate G4, not built) |

## 2. Stakeholders

| Role | Concern |
|---|---|
| Judges | Round 1 rubric: investigation accuracy, evidence quality, agentic effectiveness, engineering quality, innovation, presentation. Round 2 (as known): relative accuracy improvement of Agentic GraphRAG over plain RAG, architecture, agent design, token efficiency, engineering quality. §2.1 maps each criterion to its evidence |
| Team (dev) | Debuggability of agent behaviour |
| Operator | Choosing LLM provider/model and embedding model, loading datasets, running benchmarks without restarting the server |
| Batch runner (non-human actor) | Same execution path, headless, over 100 known + 50 hidden questions |

### 2.1 Judging criteria and the evidence for each

"Measured" means a recorded live run. "Offline" means tests or the
component-level harness, without TigerGraph or an LLM. Nothing in the
Round-2 column is a live pipeline result yet.

| Criterion | Round-1 evidence (measured, run `r5-public`) | Round-2 evidence | Gap to close |
|---|---|---|---|
| Relative accuracy, Agentic vs RAG | EM 0.98 vs 0.59 (+0.39); right on 39 questions RAG misses, wrong on none RAG gets right | Offline only: the resolver picks the true value on 0.89–0.94 of harness test questions (oracle parse); no RAG comparison | **Live harness run, three pipelines** (§12 step 5). This is the judged number and it does not exist yet |
| Architecture | One graph holds entities, chunks and vectors; five installed GSQL queries; shared dispatcher for UI and batch | Additive fact layer (`Dataset, Source, Entity, Claim`), dataset-scoped search, adapters per dataset; Round-1 types and queries untouched | First install on Savanna (§12 step 2) |
| Agent design | Deterministic router, evidence check, fallbacks, closed stop vocabulary, answer verification | Claim probe decides whether claims matter; temporal scope, supersession and conflict resolution are deterministic and written to the trace; one corroborating search on a narrow margin; ask-back when the question is ambiguous | Show it on the trace panel in the demo (US-8 to US-11) |
| Token efficiency | Median 2,550 tokens vs RAG 6,453; 62 of 100 questions take the direct route | No new LLM calls: the claims route replaces the groundedness call with arithmetic | Tokens per question on the harness (§12 step 5) |
| Engineering quality | `make reproduce`; deterministic scorer; anti-overfitting tests | 693 backend and 63 frontend tests; dev/test split with weights frozen before test; gate log for every schema or model decision | Round-1 regression re-run on `round-2` (§12 steps 1 and 6) |
| Honesty of claims | A question type reported where the agent is not worth it (lookup) | Limits listed in `ROUND2-RESULTS.md` §4, including where the resolver stops working | Keep every Round-2 number tied to a run file |

## 3. Scope decisions (resolved, with basis)

| Decision | Resolution | Basis |
|---|---|---|
| Gold documents outside the Olympic subset? | No — 547/547 gold references are Olympic infoboxes | Verified against `eval_public.jsonl` × corpus |
| Embedding model | Five selectable models (`bge-large-en-v1.5` default, `qwen3-embedding-0.6b`, `embeddinggemma-300m`, `gte-large-en-v1.5`, `mxbai-embed-large-v1`), each with its own TigerGraph vertex type and HNSW index; at most two stored. `bge-large-en-v1.5` is served by Cloudflare Workers AI (CLS pooling) when configured, otherwise locally; the others locally | Lets the operator compare models without mixing embedding spaces (EMBEDDING-SWITCHING.md) |
| Vector store | TigerGraph only (Savanna or Community Edition 4.2+) | Hackathon eligibility; no external index |
| Venue modelling | Venue as vertex, not secondary index | 319 venues; ~23% of venue+date pairs non-unique — needs traverse-then-disambiguate |
| Person/NOC vertices + `WON_MEDAL` edges | Cut — medallists are attributes on the event | No question type traverses person→events |
| Intent extraction | Function-calling (or JSON-schema prompting when unsupported) with schema validation + one retry | Structural reliability without grammar-constrained decoding |
| Necessity routing | Rule on parsed operation type, not a trained classifier | A classifier trained on 100 questions overfits |
| Accuracy scoring | Deterministic EM/F1 against gold — no LLM judge | Gold answers exist and are verified |
| Access | Open: no sign-in, key or role (owner's decision); no secret in the browser bundle (the build refuses a `VITE_API_KEY`) | Anyone who reaches the backend can build, reset and run benchmarks; a public deployment needs a proxy with its own authentication |
| Query history | Persisted: every query, build and benchmark trial in `out/history.jsonl` (History screen); benchmark runs as JSONL files (Dashboard run picker) | Replay and audit of what was run |
| Datasets | JSONL datasets can be uploaded, renamed (display title) and built; the graph keeps every loaded dataset; rebuilding one requires confirmation | Multiple corpora without resetting the graph |
| Runtime settings | LLM provider (presets `gemini`, `nvidia_nim`, `groq`) and model, and the active embedding model, change at runtime without a restart; keys stay in the server environment | Switching models between runs without code or config edits |
| Batch resume | A rerun skips questions already written; a failed question is left unwritten and retried | A partial run is recoverable |
| Missing counts | A count the infobox does not record is stored as 0 (TigerGraph INT has no null) and read as "not recorded": never counted, never ranked, never shown as a value | "Fewer than N" used to count events with no figure |
| Ambiguous questions | The agent asks which venue or event was meant when the candidates give different answers, and offers them as choices | A guess that happens to be right cannot be told from one that is wrong |
| Round-2 schema | One graph, additive fact layer, datasets scoped by `IN_DATASET` (gate G1, owner's decision 2026-10-24) | A separate graph per dataset would duplicate the embedding types and break the max-two-models design |
| Round-2 confidence | Computed by the agent from the weighed claims, for Agentic GraphRAG only; the shared answer prompt is unchanged (gate G2) | Round-1 results stay comparable; a model's stated confidence is usually poorly calibrated |
| Round-2 answer policy | Always commit to one best answer, with a confidence and the conflicting values cited; no abstention | Owner's decision |

## 4. Functional requirements (EARS notation)

| ID | Requirement |
|---|---|
| FR-1 | The system shall accept a single free-text query via one input field |
| FR-2 | Upon submission, the system shall invoke the RAG, GraphRAG and Agentic GraphRAG pipelines concurrently |
| FR-3 | While any pipeline is running, the system shall render that pipeline's column in a running state independent of the other two |
| FR-4 | When a pipeline completes, the system shall render its answer, evidence/citations, tokens used and latency in its column |
| FR-5 | While the Agentic GraphRAG pipeline is running, the system shall append each investigation step to a visible trace panel as it occurs |
| FR-6 | If the orchestrator deviates from its initial route (a fallback, or an empty direct lookup escalated into the loop), the system shall mark that step as a strategy change in the trace |
| FR-7 | When the Agentic GraphRAG pipeline stops, the system shall display the stop reason from the closed vocabulary (`sufficient_evidence`, `step_budget_exhausted`, `token_budget_exhausted`, `no_further_action_available`, `disambiguation_required`, `error`, `direct_route`, and for Round 2 `conflict_resolved`) |
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
| FR-19 | **Withdrawn.** The application is open by the owner's decision (§3, Access): no API key and no stream token. The id is kept so later ids do not shift; UI-SPEC still mentions it and is out of date on this point |
| FR-20 | The metrics dashboard shall present both an aggregate benchmark view and a per-question table covering all evaluation questions across all three pipelines, with a "pipelines disagree" filter and trace drill-down |
| FR-21 | The system shall let the operator upload a JSONL dataset, rename its display title, and build it into the graph alongside datasets already loaded; building an already-built dataset shall require an explicit rebuild |
| FR-22 | The system shall let the operator switch the active embedding model; a switch to a model that is not fully embedded shall require an explicit choice between replacing and keeping parallel indices, and a query whose selected model is not complete shall be refused with the list of models that are |
| FR-23 | The system shall record every query, build and benchmark attempt (including refused ones) and show them in a History view |
| FR-24 | When a batch run is restarted with the same output file, the system shall skip questions already written and run only the rest |
| FR-25 | If the question's venue matches several venues, or several events at the venue on the asked day give different answers, and the question names nothing that tells them apart, the agent shall stop with `disambiguation_required`, name the candidates, and the UI shall offer each as a re-ask |
| FR-26 | The system shall treat a count the corpus does not record as unknown: excluded from counts and rankings, reported as "not counted", and never shown to the model as 0 |

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
| US-8 | As a judge, I ask who holds a result "as of 2015", "originally" and "currently", and get three different, correct answers, each with the superseded values shown | R2-FR-1, R2-FR-4, R2-FR-8 |
| US-9 | As a judge, I ask a question where a blog and an official source disagree, and see which value was chosen, the score behind it, and the losing value still cited | R2-FR-2, R2-FR-8 |
| US-10 | As a judge, I ask a question whose only support is a hedged report, and the answer comes with a visibly low confidence instead of false certainty | R2-FR-3 |
| US-11 | As a judge, I see on the trace that the conflict was settled by a graph query and a deterministic score, and how many tokens that cost next to RAG | R2-FR-8, R2-NFR-2 |
| US-12 | As a judge, I ask an ambiguous question and the agent asks back with the candidates instead of guessing | FR-25 |
| US-13 | As the team, we plug in the real Round-2 dataset by writing one adapter, and rerun the same harness commands | R2-FR-5, R2-FR-7 |

## 7. Success criteria

### 7.1 Round 1 (measured: public set, 100 questions, run `r5-public`; figures from WRITEUP.md and SCORE-AUDIT.md, run files are not in this checkout)

| Criterion | Target | Result |
|---|---|---|
| Concurrent execution demonstrated live | 3 columns visibly populate independently | Met |
| Verdict strip present for every query | 100% of demo queries | Met |
| Trace completeness | Every agentic run shows steps, tool calls, tokens, stop reason | Met; step tokens sum to the record total |
| Batch coverage | 100 known + 50 hidden questions fully processed, zero silent failures | Met: 0 errors in 300 and in 150 answers |
| Per-qtype metrics reported | EM, F1, precision, recall, completeness by all 5 question types | Met |
| Structured-query solvability (measured against the corpus, before the agent existed) | aggregation 21/21, superlative 10/10, lookup 19/19, multi_hop 27/28, temporal 18/22 | As stated; it bounded what the graph could answer |
| Reuse | 0 duplicated pipeline-invocation logic between UI and batch mode | Met |
| Accuracy floor | P3 EM ≥ 0.85 overall; ≥ 0.90 on aggregation, superlative and lookup | **0.98** overall; aggregation 1.00, superlative 0.90, lookup 1.00 |
| Thesis criterion | P3 − P1 EM gap on aggregation ≥ 0.50 | **+0.86** (1.00 vs 0.14) |
| Cost-honesty criterion | At least one qtype where P3 is not worth its token multiplier | lookup (RAG and Agentic both 1.00) and temporal (+0.05 at 1.05× tokens) |
| Token efficiency | not set in v0.4 | Agentic median 2,550 tokens vs RAG 6,453 (0.40×) |
| Generalization check | Paraphrase set answered through the same intent schema | **Not scored**: the 15 questions exist; no run is recorded |
| Held-out score | not set in v0.4 | **None**: 0.98 is a development-set score. The hidden set has no gold answers and was run on an earlier system |

### 7.2 Round 2 (targets; none measured live yet)

The judged quantity is the relative gain of Agentic GraphRAG over plain RAG.
Targets are set before the run so the result cannot move them. They apply
to the harness **test** split (weights fitted on dev only) until the real
Round-2 dataset replaces it.

| Criterion | Target | Status |
|---|---|---|
| Relative accuracy gain | Agentic − RAG EM ≥ +0.25 on each of the evolving, conflicting and uncertain subsets, reported with Wilson 95% intervals, absolute and relative | Not measured |
| The loop's own contribution | Agentic − GraphRAG reported per subset, whatever its sign | Not measured |
| Token efficiency | Agentic median tokens per question ≤ RAG's on the same questions; tokens per correct answer reported for all three | Not measured |
| Calibration | Agentic ECE ≤ 0.10 and Brier reported on test; reliability table in the report | Offline (oracle parse): ECE 0.01–0.09 overall; uneven per subset |
| Unanswerable items | Mean confidence on unanswerable items lower than on answerable ones | Not measured |
| Round-1 regression | Public-100 on `round-2` after the fact layer is installed: Agentic EM not below the same-day baseline by more than one question; RAG unchanged | Offline suite passes; live run not done |
| Fair baseline | Same documents, `k`, LLM, embedding model and answer prompt in all three pipelines; source and date visible in the text RAG retrieves | Built into the harness |
| Reproducibility | One command generates the harness, one fits and reports offline, one batch command per live run; seed and parameters recorded in the manifest | Built |
| Real dataset | Loaded through an adapter with no change to the reasoning code; every [ASSUMPTION] in the Round-2 documents reconciled | Dataset not released |

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
| Round-2 dataset format, guidebook and deadline | **Open** — not released. The generic adapter and the class reliability priors are labelled assumptions |
| "TG Multihop30" | **Open** — the Round-2 brief says the Round-1 output format was built against it; nothing by that name is in this repository (the Round-1 sets are public-100 and hidden-50) |
| Does the real dataset say anything about its sources? | **Open** — with no reliability information and a coordinated false majority, the resolver's offline accuracy on conflicting items stops near 0.83 |

## 10. Round 2 requirements (statement: "Extend your agent to reason over evolving, conflicting, and uncertain facts on a harder dataset")

EARS notation. "Built" means implemented and tested offline; see
`ROUND2-RESULTS.md` for the offline figures and their limits.

| Id | Requirement | Status |
|---|---|---|
| R2-FR-1 | When a question puts a time scope on a fact ("as of", "originally", "latest", before/after a revision), the agent shall answer with the value known and valid in that scope. Edition-relative wording ("the Games before 2016") shall not count as a time scope | Built; offline evolving 1.00 (oracle parse); no Round-1 question is time-scoped |
| R2-FR-2 | When sources state different values, the agent shall choose one by an inspectable score (reliability, corroboration, recency, extraction, hedging) and cite the losing values | Built; offline conflicting 0.83–1.00 by difficulty and by what is known about the sources |
| R2-FR-3 | The agent shall give a confidence with each claims-based answer, calibrated on held-out questions; it shall not abstain by default | Built (Agentic only, gate G2) |
| R2-FR-4 | When a later statement revises an earlier one, the earlier one shall be kept as superseded evidence, not deleted; a hedged statement shall not supersede a firm one | Built |
| R2-FR-5 | A new dataset shall plug in through an adapter without changes to the reasoning code | Built (`datasets/`); real format unknown |
| R2-FR-6 | Where several datasets are loaded, a run shall be able to restrict retrieval to named datasets, so that test or Round-2 data cannot change Round-1 results | Built in code (`IN_DATASET`, Q5S, Q6 dataset filter); **not yet exposed** as a run or UI setting |
| R2-FR-7 | The system shall generate a validation set of evolving, conflicting and uncertain facts with known ground truth, parameterised by difficulty, conflict rate, hedging, noise and source information, deterministic for a seed, split by event into dev and test | Built (`ogr.cli harness`) |
| R2-FR-8 | For every claims-based answer the record shall carry the time scope, the chosen value, each alternative with its score terms and sources, and the superseded values; the UI shall show them | Built (`confidence`, `temporal_scope`, `conflicts`, `TraceStep.details`) |
| R2-FR-9 | When the chosen value's share of the weight is below the margin, the agent shall run one corroborating search and then commit | Built (margin 0.6, one search) |
| R2-FR-10 | When the model's answer names a value the resolution ranked lower, the resolved value shall stand and the trace shall say so | Built |
| R2-FR-11 | Where a dataset states facts only in prose, the system shall extract claims at ingest, once, with the result cached | **Not built** (allowed by gate G4). Until then such a dataset reaches only RAG and the prose fallbacks |
| R2-FR-12 | The dashboard shall report the Round-2 subsets beside the Round-1 types, and show confidence calibration for the agentic pipeline | Subsets: built. Calibration view: **not built** (figures are in the CLI report) |
| R2-NFR-1 | Round-1 behaviour shall not regress: unchanged routes when no claims matter, unchanged shared answer prompt, unchanged Q1–Q5 | Offline suite passes; live baseline not yet re-run |
| R2-NFR-2 | Same LLM and embedding model in all three pipelines; tokens per question reported; agent loops bounded (`RUN_MAX_STEPS`, `RUN_MAX_TOKENS_PER_QUERY`, one corroborating search); no LLM call added by Round 2 | Built; tokens not yet measured |
| R2-NFR-3 | No schema change, re-ingest or provider change without the owner's confirmation | Gates logged in `ROUND2-INTERVIEW-LOG.md` |
| R2-NFR-4 | Weights, calibration and thresholds shall be fitted on the dev split only and frozen before the test split is run; nothing shall be derived from questions or gold answers | Built (`harness --offline`, `OGR_ROUND2_WEIGHTS`) |
| R2-NFR-5 | The validation set shall not weaken RAG artificially, and generated statements about real people shall be neutral | Built; a test rejects accusatory wording |
| R2-NFR-6 | Conflict resolution shall be deterministic: the same claims give the same answer, confidence and trace | Built and tested |

## 11. Risks to the Round-2 result

| Risk | Likelihood | Effect | Mitigation |
|---|---|---|---|
| No live Round-2 measurement before the deadline | High until credentials are added | No judged number at all | §12 steps 1–5 first, before any further feature |
| The fact-layer GSQL fails on first install | Medium (never run on Savanna) | Blocks every live Round-2 run | Install early; the job is additive and Q1–Q5 keep working if it fails |
| The real dataset is prose-only | Unknown | Graph pipelines have no claims; the gain over RAG shrinks to Round-1 behaviour | Build R2-FR-11 as soon as the format is known |
| The real dataset is not about Olympic events | Unknown | Subjects must link as generic entities; entity linking for them is untested | `Entity` type and `ent:` subjects exist; test on the first sample |
| The intent parse misses the subject or attribute on Round-2 wording | Medium | The resolver never runs, however good it is | Dry run first; gate G3 allows a temporal field in the parse if the rules fall short |
| Evolving cases in the harness are too easy | Known | An inflated evolving score that will not transfer | Harder generator before the reported run |
| RAG scores well on the harness because source and date are in its text | Medium | Smaller gain | Report it as it is; the comparison stays fair |
| Round-1 score moves after the fact layer is installed | Low | Regression in a judged Round-1 criterion | Same-day baseline before and after |

## 12. Readiness checklist (in order; stop anywhere and the work before it stands)

| # | Step | Needs | Status |
|---|---|---|---|
| 1 | Round-1 baseline on `round-2`: public-100, three pipelines | Credentials | Not done |
| 2 | Install the fact layer and backfill claims (`ogr.cli round2`); reinstall Q2/Q3 | Credentials | Not done |
| 3 | Build the harness corpus as its own dataset | Step 2 | Not done |
| 4 | Dry run: 10 questions × three pipelines; read the cost before going on | Step 3 | Not done |
| 5 | Harness test split × three pipelines; per-subset report with intervals, tokens and calibration | Step 4 | Not done |
| 6 | Round-1 regression after the fact layer | Step 2 | Not done |
| 7 | Expose the dataset scope as a run setting (R2-FR-6) | – | Not done |
| 8 | Harder evolving generator | – | Not done |
| 9 | Score the paraphrase set; rerun the hidden set on the final system | Credentials | Not done |
| 10 | Calibration view on the dashboard (R2-FR-12) | Step 5 | Not done |
| 11 | Demo script with one question each for US-8 to US-12 | Step 5 | Not done |
| 12 | Real dataset: adapter, reconcile assumptions, rerun steps 3–6 | Dataset release | Blocked |

