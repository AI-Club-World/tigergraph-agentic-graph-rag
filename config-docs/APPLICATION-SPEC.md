# APPLICATION-SPEC.md
Agentic GraphRAG Hackathon — Three-Pipeline Comparison System

Status: **v0.3 — synchronised with implementation plans, 2026-09-21.** Supersedes v0.2. | Standard basis: IEEE 29148 (requirements), EARS notation

> **v0.3 change summary.** §1 corpus date range corrected (measured 1900–2022,
> not 1987–2022); §3 multi-person rule corrected (the v0.2 rule mis-splits a
> real answer); §4 FR-11 now testable, FR-17…FR-19 added; §7 quantitative
> acceptance criteria added — v0.2 had none, so the project could not fail its
> own definition of success; §9 all questions closed. Traceability:
> `ISSUE-CLOSURE.md`.

---

## 1. Purpose

| Field | Value |
|---|---|
| Problem | No single view exists to compare RAG vs GraphRAG vs Agentic GraphRAG answer quality, evidence, and cost on the same query |
| Domain / corpus | Wikipedia Olympic results archive: 2,951 docs, 5,466,414 tokens, CC BY-SA 4.0. **Olympic events span 1900–2022** across 21 distinct Games (corrected in v0.3; v0.2 said 1987–2022). 73.3% Olympic event infoboxes (2,162), 18.5% film (546), 8.2% other (243) — all verified by parsing the corpus |
| Question types | lookup, multi_hop, temporal, aggregation, superlative — 100 public eval questions (verified answers), 50 hidden |
| Solution | Single query input, three pipelines executed in parallel, results rendered side by side with cost/verdict summary |
| Research thesis | Aggregation/superlative questions require exhaustive enumeration over a scoped set — a structural ceiling for top-k retrieval, not a tuning deficiency. Routing between cheap and agentic paths follows the parsed operation type, not a learned classifier |
| Primary use | Live demo to hackathon judges; secondary reuse as batch harness for required metrics dashboard |
| Out of scope | Auth, multi-turn conversation, persisted query history (v0.1); Person/NOC entity vertices (cut — no question type traverses person→events, §3 below) |

## 2. Stakeholders

| Role | Concern |
|---|---|
| Judges | Investigation accuracy, evidence quality, agentic effectiveness, engineering quality, innovation, presentation (per rubric) |
| Team (dev) | Debuggability of agent behavior during build |
| Batch runner (non-human actor) | Same execution path, headless, over 100 known + 50 hidden questions |

## 3. Scope Decisions (resolved, with basis)

| Decision | Resolution | Basis |
|---|---|---|
| Gold documents outside Olympic subset? | No — 547/547 gold references are Olympic infoboxes | Verified against eval_public.jsonl × corpus.jsonl |
| Embedding model | BAAI/bge-small-en-v1.5, 384-dim, local via sentence-transformers; provider models config-swappable | Deterministic, zero API cost, no rate limits, removes an external dependency from the reproduce path |
| TigerGraph deployment | Savanna | Guidebook-recommended, credits provided, removes ops burden in a short build window; 384-dim fits either option so this is reversible |
| Venue modeling | Venue as vertex, not secondary index | 303 distinct venues; 23% of venue+date pairs non-unique — multi-hop requires traverse-then-disambiguate |
| Person/NOC vertices + WON_MEDAL edges | Cut — medalists are string attributes on the event | No question type traverses person→events; only 2/100 answers contain concatenated multi-person names |
| Intent extraction method | Function-calling with schema validation + one retry | Strict grammar constraints measurably degrade reasoning; validate-and-retry gets structural reliability without the penalty |
| Necessity routing | Rule on parsed operation type, not a trained classifier | A classifier trained on 100 questions overfits and is indefensible in Q&A |
| Ground-truth accuracy scoring | Deterministic EM/F1 against verified gold answers — no LLM judge in the scoring loop | Gold answers already exist and are verified; a reference-free LLM judge is the tool for *absence* of ground truth, not a weaker substitute when labels exist |

## 4. Functional Requirements (EARS notation)

| ID | Requirement |
|---|---|
| FR-1 | The system shall accept a single free-text query via one input field |
| FR-2 | Upon submission, the system shall invoke RAG, GraphRAG, and Agentic GraphRAG pipelines concurrently |
| FR-3 | While any pipeline is running, the system shall render that pipeline's column in a running state independent of the other two |
| FR-4 | When a pipeline completes, the system shall render its answer, evidence/citations, tokens used, and latency in its column |
| FR-5 | While the Agentic GraphRAG pipeline is running, the system shall append each investigation step to a visible trace panel as it occurs |
| FR-6 | If the orchestrator deviates from its initial plan, the system shall mark that step as a strategy change in the trace |
| FR-7 | When the Agentic GraphRAG pipeline stops, the system shall display the stop reason |
| FR-8 | When all three pipelines have completed, the system shall compute and display a verdict strip showing token multipliers (Agentic ÷ RAG, Agentic ÷ GraphRAG) and accuracy delta (EM/F1-based) where ground truth is available |
| FR-9 | Where ground truth is not available for a query, the verdict strip shall display "N/A" for accuracy delta rather than omit the field |
| FR-10 | Every rendered answer shall include citations traceable to source chunks or graph entities, scorable as a set against gold_doc_ids |
| FR-11 | The system shall route each query by parsed operation type: LOOKUP with fully-specified anchor → direct single-query path (no agent loop); COUNT/ARGMAX → one scoped aggregation query; TRAVERSE or underspecified anchor → multi-step agentic loop. **Fully-specified ⇔ (`anchor.title` or `anchor.event_id` non-null) and `target_field` non-null and `constraints` empty** — added in v0.3; without it FR-11 was untestable |
| FR-12 | The intent parser shall emit a constrained schema — operation, anchor, constraints, target_field — via LLM function-calling, validated with one retry on schema failure |
| FR-13 | The system shall expose the same pipeline-invocation and metrics-capture logic in a headless batch mode, callable without the UI |
| FR-14 | In batch mode, the system shall accept a list of questions and produce one structured record per question per pipeline, scored by EM, F1, Recall@k, Precision@k, and Completeness against gold_doc_ids |
| FR-15 | The system shall run against the 100 known evaluation questions and the 50 hidden evaluation questions, producing metrics-dashboard input for both, broken out per question type |
| FR-16 | The system shall support a hand-authored paraphrase set (~15 questions, same intents via different surface forms) as a generalization check, distinct from the scored eval sets |
| FR-17 | Every pipeline shall return a structured answer `{answer, explanation}` from a prompt byte-identical across pipelines apart from retrieved context; EM and F1 shall score `answer` only |
| FR-18 | The LLM shall be selectable by configuration — local or hosted — without code change, with provider, model, base URL and API key supplied by configuration and environment |
| FR-19 | All backend routes except `/health` shall require an API key supplied by configuration; SSE routes shall use a short-lived single-use stream token, since `EventSource` cannot send headers |
| FR-20 | The metrics dashboard shall present both an aggregate benchmark view and a per-question table covering all 100 evaluation questions across all three pipelines, with a "pipelines disagree" filter and trace drill-down |

## 5. Non-Functional Requirements

| ID | Requirement | Rationale |
|---|---|---|
| NFR-1 | Pipeline calls shall execute concurrently, not sequentially | Cost/time comparison is only meaningful if latency isn't inflated by serial waits |
| NFR-2 | Failure or timeout in one pipeline shall not block rendering of the other two | Demo resilience |
| NFR-3 | Token and time capture shall be instrumented at the pipeline-invocation layer from initial implementation | Trace data is directly judged (agentic effectiveness, 15%); retrofitting risks incomplete data |
| NFR-4 | Batch mode output shall be reproducible: fixed local embedding model (no provider drift) + logged config/seed per run, runnable end-to-end via a single reproduce command | Reproducibility is a named rubric item; a local embedding model removes an external dependency from the reproduce path |
| NFR-5 | UI and batch mode shall share one aggregator implementation | Avoids drift between demo behavior and submitted metrics |
| NFR-6 | Evaluation scoring shall be deterministic, run-to-run identical for identical inputs | No LLM sits in the scoring loop — more credible to judges than an LLM-judged number |
| NFR-7 | No question-template regex shall appear anywhere in the answer path | Anti-overfitting: routing must go through the constrained intent schema, not branch on eval-set phrasings |

## 6. User Stories

| ID | Story | Acceptance |
|---|---|---|
| US-1 | As a judge, I submit one query and see three answers side by side | FR-1, FR-2, FR-4 |
| US-2 | As a judge, I see how much more the agentic approach cost in tokens/time for its answer | FR-8 |
| US-3 | As a judge, I can inspect why the agent took each step and why it stopped | FR-5, FR-6, FR-7 |
| US-4 | As a judge, I can see a question (e.g. aggregation) where top-k retrieval is structurally wrong regardless of k, and where the agentic path resolves it exactly with full citations | FR-10, FR-11 |
| US-5 | As a judge, I can see a question (e.g. simple lookup) where the agentic path is correct but wastes ~10x the tokens for no accuracy gain | FR-8, FR-11 |
| US-6 | As the team, we run the same logic in batch to produce the required dashboard without rebuilding pipelines | FR-13, FR-14, FR-15 |

## 7. Success Criteria

| Criterion | Target |
|---|---|
| Concurrent execution demonstrated live | 3 columns visibly populate independently, not in lockstep |
| Verdict strip present for every query | 100% of demo queries |
| Trace completeness | Every agentic run shows steps, tool calls, tokens, stop reason |
| Batch coverage | 100 known + 50 hidden questions fully processed, zero silent failures |
| Structured-query solvability (internal validation, pre-agent) | aggregation 21/21, superlative 10/10, lookup 19/19, multi_hop 27/28, temporal 18/22 against the graph directly |
| Per-qtype metrics reported | EM, F1, Recall@k, Precision@k, Completeness — each broken out by all 5 question types |
| Generalization check | Hand-authored paraphrase set (~15 questions) answered correctly through the same intent schema, not template-matched |
| Reuse | 0 duplicated pipeline-invocation logic between UI and batch mode |
| **Accuracy floor** (added in v0.3 — v0.2 had no numeric target) | P3 EM ≥ 0.85 overall; ≥ 0.90 on aggregation, superlative and lookup |
| **Thesis criterion** | P3 − P1 EM gap on aggregation ≥ 0.50. This is the core research question expressed as a number: below it, the claim that agentic investigation beats top-k retrieval on enumeration is not evidenced |
| **Cost-honesty criterion** | At least one qtype reported where P3 is *not* worth its token multiplier. A benchmark that finds the agent always wins has not been run honestly |

## 8. Dependencies

| Dependency | Notes |
|---|---|
| TigerGraph Savanna (or Community Edition fallback) | Graph + vector backend; 384-dim embedding fits either |
| LLM API (any provider) | Intent parsing (function-calling), generation, evidence evaluation |
| Local embedding model | BAAI/bge-small-en-v1.5, 384-dim, sentence-transformers — provider-swappable via config |
| Provided dataset | Corpus (corpus.jsonl) + 100 known (eval_public.jsonl) + 50 hidden (eval_hidden.jsonl, field name is `qid` not `question_id`) questions |

## 9. Open Questions

| Question | Owner | Status |
|---|---|---|
| Ground-truth scoring method | Team | **Resolved** — deterministic EM/F1 (SQuAD-style normalization), no LLM judge |
| Persisted query history — needed for judge replay? | Team | **Resolved** — out of scope for Round 1; batch records already provide replay for every scored question |
| Multi-person answer scoring | Team | **Resolved, corrected in v0.3** — split on lowercase→uppercase boundaries **with a prefix guard** (`Mc`, `Mac`, `O'`, `Di`, `De`, `Van`, `Le`, `La`). The unguarded v0.2 rule mis-splits `Rosannagh MacLennan` (pub-067). Genuine concatenations are pub-015 and pub-099 |
