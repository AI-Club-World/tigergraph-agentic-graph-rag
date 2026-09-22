# ARCHITECTURE-SPEC.md
Agentic GraphRAG Hackathon — Three-Pipeline Comparison System

Status: **v0.3 — synchronised with implementation plans, 2026-09-21.** Supersedes v0.2. | Standard basis: arc42, C4 model, ISO/IEC/IEEE 42010

> **v0.3 change summary.** §2 P2 re-routed (its static rule table was not
> implementable without violating NFR-7); §5 "fully-specified anchor" now
> defined; §11 six new decision records (AD-10…AD-15); §13 the venue mitigation
> corrected — **measured, it does not work**. Traceability: `ISSUE-CLOSURE.md`.

---

## 1. Context (C4 Level 1)

| Actor/System | Interaction |
|---|---|
| Judge / user | Submits query via UI, views 3-column comparison + verdict strip |
| Batch runner | Submits question list programmatically, consumes structured records |
| TigerGraph Savanna | Graph store + vector store; five installed GSQL queries; vector index async, must poll `/restpp/vector/status` before benchmark runs |
| LLM provider API | Function-calling intent parsing, generation, evidence evaluation — no provider dependency in embeddings or scoring |
| Local embedding model | all-MiniLM-L6-v2 (384-dim, sentence-transformers) — deterministic, no external call |
| Olympic Wikipedia corpus | 2,951 docs ingested at setup; 100 known + 50 hidden question sets as query inputs |

```
        ┌────────────┐        ┌────────────────────┐
Judge ─▶│  Comparison │──────▶│  TigerGraph Savanna │
        │  System     │       │  (graph + vector)   │
Batch  ─▶│            │──────▶└────────────────────┘
Runner  │            │──────▶┌────────────────┐
        │            │──────▶│  LLM Provider   │
        └────────────┘       └────────────────┘
                       └────▶ Local embedding model (in-process)
```

## 2. Containers (C4 Level 2)

| Container | Responsibility | Notes |
|---|---|---|
| UI (Search + 3-Column Renderer) | Query input, parallel result display, trace panel, verdict strip | Consumes Result Aggregator output |
| Query Dispatcher | Fires 3 concurrent pipeline invocations per query | Shared by UI and batch mode |
| P1 — RAG Pipeline | Q5 (`hybrid_search`) vector top-k only, no type filtering | Deliberately unfiltered — its ceiling must be visible, not masked (writeup must state this explicitly) |
| P2 — GraphRAG Pipeline | **Same intent parser as P3**, then one query (Q1/Q2/Q3/Q4), single-shot, no evidence check, no fallback, no loop | Corrected in v0.3: the v0.2 "static rule table" keyed on question type is not implementable — `qtype` is an eval-set label and NFR-7 forbids question-template regex. Sharing the parser makes the comparison a clean ablation: P1 removes the graph, P2 removes the loop, P3 has both |
| P3 — Agentic GraphRAG Orchestrator | Intent parse → necessity-routed query → evidence check → optional re-query | Dynamic; only path with a step loop and stopping criteria |
| Specialised Agents (7) | Entity linking, graph traversal, similarity search, document retrieval, aggregation, multi-hop reasoning, evidence evaluation | Invoked by P3 orchestrator; several are a single query or single prompt at their defensible minimum (§4) |
| Result Aggregator | Captures answer, evidence, tokens, latency, trace per pipeline | Single implementation, used by both UI and batch mode |
| Batch Runner | Headless driver over question lists (100 known + 50 hidden) | Produces metrics-dashboard input |
| Metrics Dashboard Generator | Per-qtype matrix, accuracy-vs-tokens scatter, drill-down, trace viewer | Required deliverable |
| GSQL Query Library (5 queries) | Q1 lookup, Q2 count_where, Q3 argmax, Q4 traverse, Q5 hybrid_search | Prototyped via `INTERPRET QUERY`, installed once near the end (install blocks concurrent ops, ~1 min each) |

## 3. Components (C4 Level 3) — Agentic GraphRAG Orchestrator (P3)

| Component | Responsibility |
|---|---|
| Intent Parser | LLM function-calling → constrained schema `{operation, anchor, constraints, target_field}`, schema-validated with one retry. No question-template regex anywhere in this path |
| Necessity Router | Maps parsed `operation` to a path per the rule in §5 below — replaces a trained classifier |
| Tool Router | Maps routed operation → GSQL query (Q1–Q4) or specialised agent invocation |
| Evidence Evaluator | Deterministic check: did the retrieved set cover the required scope? Plus one groundedness check |
| Stopping-Criteria Evaluator | Stops on sufficient evidence or hard step/token budget; emits `stop_reason` |
| Strategy-Change Detector | Flags when the router's path deviates from its initial routing decision (e.g., re-query after evidence check fails) |
| Trace Recorder | Emits step records (agent type, tool, tokens, latency, notes) to Result Aggregator in real time; optionally writes a minimal trace-as-graph (Run vertex, N ordered Step vertices) — SHOULD, no trace analytics |

## 4. The Seven Specialised Agents — Defensible Minimum

| Agent | Implementation |
|---|---|
| Entity linking | Intent parser's anchor resolution against Games/Sport/Venue vertices |
| Graph traversal | Q4 (`traverse`) |
| Similarity search | Q5 (`hybrid_search`) |
| Document retrieval | `HAS_CHUNK` expansion for prose fallback |
| Aggregation | Q2 (`count_where`) / Q3 (`argmax`) |
| Multi-hop reasoning | Planner chaining Q4 → Q1 |
| Evidence evaluation | Deterministic scope-coverage check + one groundedness check |

Several agents are a single query or single prompt — stated explicitly as the correct amount of machinery for five question types, not an implementation shortfall.

## 5. Necessity Routing Rule (replaces a trained classifier)

| Operation | Path | Rationale |
|---|---|---|
| LOOKUP with fully-specified anchor | Direct Q1 — no agent loop | Single retrieval suffices. **Fully-specified ⇔ (`anchor.title` or `anchor.event_id` non-null) and `target_field` non-null and `constraints` empty.** v0.2 left this undefined, which made FR-11 untestable and AGENT-02 unbuildable |
| COUNT / ARGMAX | One scoped aggregation query (Q2/Q3) | Needs exhaustive enumeration, not iteration |
| TRAVERSE / underspecified anchor | Multi-step agentic loop | Genuine dependency chain |

Positioned against prior art in the writeup: Adaptive-RAG routes on a learned complexity classifier; Self-RAG on reflection tokens; this routes on parsed operation type — no training data required, defensible in Q&A.

## 6. Data-Bearing Design: Why TigerGraph Is Load-Bearing

Aggregation and superlative questions require exhaustive enumeration over a scoped set, then a numeric operation over up to 43 documents (median 2, mean 5.5 gold docs per question). Top-k retrieval has no notion of "all events in this sport at these Games" — no value of k makes this correct, only values that make it expensive. This is a structural ceiling, not a tuning deficiency, and it is the architecture's central demo argument.

| Capability | Why it matters |
|---|---|
| In-database aggregation over a traversed set | What vector search cannot do at all |
| Traverse-then-disambiguate on venue | 23% of venue+date pairs are ambiguous — median 4 events per venue, "Olympic Stadium" alone hosts 115 |
| `PREV_EDITION` as a first-class edge | Temporal questions become one hop instead of date arithmetic |
| Vector and graph in one query | `vectorSearch()` returns a vertex set that graph blocks traverse directly |

## 7. Schema Summary (full detail in TECHNICAL-SPEC §4)

| Vertex | Vector? | Note |
|---|---|---|
| Document | — | `doc_id` = wikidata QID, matches `gold_doc_ids` exactly — no ID mapping layer needed for retrieval scoring |
| OlympicEvent | emb (384, COSINE) | `competitors`/`nations` typed INT — native predicate, not parse-at-query-time |
| Games, Sport, Venue | — | Venue as vertex (not secondary index) — required for disambiguation |
| Chunk | emb (384, COSINE) | Prose fallback path |
| Run / Step | — | SHOULD, minimal trace write-back only |

Cut from schema: Person/NOC vertices and `WON_MEDAL` edges — no question type traverses person→events; medalists are string attributes on the event.

## 8. Runtime View — Single Query Flow

```
1. UI submits query → Query Dispatcher
2. Dispatcher fires concurrently:
     a. P1 RAG:      Q5 vector top-k, no filtering → single generation
     b. P2 GraphRAG:  static rule table → Q1/Q4/Q5, single-shot → single generation
     c. P3 Agentic:   Intent Parser → Necessity Router → routed path:
                        - LOOKUP  → Q1 direct, no loop
                        - COUNT/ARGMAX → Q2/Q3, one scoped query
                        - TRAVERSE/underspecified → agentic loop:
                            Tool Router → Specialised Agent → Evidence Evaluator
                            → (loop while insufficient, within budget)
                            → Stopping-Criteria Evaluator → generate
                     Each loop iteration streams a trace record to Result Aggregator
3. Result Aggregator merges all 3 outcomes, computes verdict strip (token multipliers, EM/F1-based accuracy delta)
4. UI renders columns independently as each arrives; verdict strip renders once all 3 complete
```

## 9. Runtime View — Batch Mode

```
1. Batch Runner reads question list (100 known / 50 hidden — hidden set's ID field is `qid`)
2. For each question: same Dispatcher → 3 pipelines → Aggregator path as interactive mode
3. Aggregator output scored: EM, F1, Recall@k, Precision@k, Completeness (|retrieved ∩ gold| / |gold|)
4. Records appended to structured store (TECHNICAL-SPEC §4.4)
5. Metrics Dashboard Generator produces per-qtype matrix, accuracy-vs-tokens scatter, drill-down, trace viewer
```

## 10. Cross-Cutting Concerns

| Concern | Approach |
|---|---|
| Concurrency | Async/parallel invocation at Dispatcher level; no sequential awaits across pipelines |
| Fault isolation | Each pipeline call wrapped independently; one failure does not block others (UI) or halt the batch run |
| Observability | Trace Recorder + per-step token/latency capture built into orchestrator from v0.1 |
| Reproducibility | Local embedding **encoder** (no provider drift; vectors stored in TigerGraph) + deterministic EM/F1 + full `run_config` logged per run (provider, model, base URL, temperature, seed, `k`, chunking, budgets, latency mode) + pinned dependency lockfile; single `make reproduce` target |
| Explainability | Every answer path carries citations scorable as a set against `gold_doc_ids`; Agentic path additionally carries full step trace |
| Anti-overfitting | No question-template regex in the answer path; routing goes through the constrained intent schema only; ~15-question hand-authored paraphrase set validates generalization |

## 11. Architecture Decisions (MADR-style, abbreviated)

| ID | Decision | Rationale | Alternative considered |
|---|---|---|---|
| AD-1 | Shared Result Aggregator for UI and batch mode | Avoids drift between demo behavior and submitted metrics | Separate implementations — rejected, doubles maintenance |
| AD-2 | Trace streamed live per step, not assembled post-hoc | Judges see cost accumulate in real time during demo | Post-hoc trace render — rejected, less demo-able |
| AD-3 | Orchestrator owns stopping criteria via evidence sufficiency + budget, not a fixed step count | Brief requires the system to "decide when enough evidence exists" | Fixed N-step loop — rejected, not agentic per hackathon definition |
| AD-4 | Ground-truth accuracy scoring: deterministic EM/F1, no LLM judge in the loop | Verified gold answers exist; reference-free LLM judges are for the *absence* of ground truth, not a weaker substitute when labels exist | LLM-judged scoring — rejected, non-deterministic and less credible to judges |
| AD-5 | Necessity routing by parsed operation type, not a trained classifier | A classifier trained on 100 questions overfits and is indefensible in Q&A; a stated rule is stronger, not weaker | Trained necessity classifier — rejected |
| AD-6 | Local embedding model (all-MiniLM-L6-v2, 384-dim), provider-swappable via config | Deterministic, zero API cost, no rate limits/drift; removes an external dependency from the reproduce path | Provider embedding API — kept as config option only |
| AD-7 | Exactly five installed GSQL queries; prototype via `INTERPRET QUERY`, install once near the end | Installation blocks concurrent operations (~1 min each); a small parameterized library avoids repeated install cost during iteration | Larger ad hoc query set — rejected |
| AD-8 | Person/NOC vertices and `WON_MEDAL` edges cut from schema | No question type traverses person→events; only 2/100 answers contain concatenated multi-person names | Full person-entity graph — rejected as unused complexity |
| AD-9 | P1 (RAG) receives no type filtering, and **all 2,951 documents are embedded**, not only the Olympic subset | Its ceiling must be visible, not masked. Embedding only Olympic documents would type-filter P1 *by ingestion* and quietly rig the comparison | Filtered/optimized P1 — rejected |
| AD-10 | Shared answer contract: every pipeline returns `{answer, explanation}` from a byte-identical prompt; EM/F1 score `answer` | Without it a correct answer phrased as a sentence scores EM = 0 for all three pipelines and the benchmark is flat | Free-form generation — rejected, the metric cannot register a correct answer |
| AD-11 | P2 shares P3's intent parser | Makes the three arms differ by one variable each; the v0.2 rule table would have required reading the test label or regexing the question | Static rule table — rejected as unimplementable under NFR-7 |
| AD-12 | Pluggable LLM behind one boundary, pinned within a run | Local or free-tier cloud without code change; a run whose model changed midway measures a model difference dressed as an architecture difference | Single hard-coded provider — rejected, fails the portability requirement |
| AD-13 | Capability probe for tool-calling and usage reporting, with JSON-schema and local-tokenizer fallbacks | Many local models lack reliable tool-calling or omit usage; assuming either breaks P3 or silently zeroes the cost axis | Assume provider capability — rejected |
| AD-14 | Two latency run modes (`--throughput`, `--timing`) | Up to 18 concurrent provider calls make latency incomparable across pipelines; tokens are pool-invariant, latency is not | Single mode — rejected, latency would be noise |
| AD-15 | Disambiguation request as the primary venue path | Measured, filtering venue+date by Games year resolves nothing (23.0% → 22.9%). Guessing on 23% of venue questions corrupts the headline number | Highest-similarity guess — rejected |

## 12. Quality Attribute Scenarios

| Attribute | Scenario | Response |
|---|---|---|
| Performance | Judge submits query during live demo | P1/P2 columns populate within a few seconds; P3 populates progressively via trace, total time visibly bounded |
| Resilience | LLM provider call fails mid-agentic-loop | Column shows error state; P1/P2 columns unaffected; batch mode logs failure and continues to next question |
| Explainability | Judge asks "why did it stop here" | `stop_reason` field directly answers without follow-up digging |
| Reproducibility | Team reruns batch mode after a pipeline change | Output diffable against prior run via logged config; embedding step introduces no drift (local, deterministic) |
| Structural ceiling (core thesis) | Aggregation question run through P1 at increasing k | Answer stays wrong; k only raises cost. P3 scopes by Games/Sport, aggregates in-database, returns exact count with full source set — demonstrates "no k fixes this," not a marginal win |
| Cost honesty | Simple lookup question run through P1 and P3 | Both correct; P3 costs materially more tokens for the same answer — the verdict strip must show this loss plainly, not just agentic wins |

## 13. Risks

| Risk | Mitigation |
|---|---|
| Team over-fits to eval-set phrasings — highest-probability failure | Hard rule: no regex/template branching in answer path; paraphrase generalization set; code review specifically for eval-string branching |
| Savanna provisioning delayed | Provision on day 0; Community Edition fallback (384-dim fits both) |
| Vector index lag → silently incomplete results | Poll `/restpp/vector/status` for `Ready_for_query` before every benchmark run |
| GSQL install blocks operations (~1 min each) | Five queries only; `INTERPRET` during dev, install once |
| `PREV_EDITION` resolution below target | Year-arithmetic fallback on Games cadence; log which resolution path fired |
| Venue+date ambiguity (23% non-unique pairs) | **Corrected in v0.3 — the v0.2 mitigation does not work.** Adding Games year moves non-uniqueness from 353/1,538 (23.0%) to 353/1,540 (22.9%), because same-venue same-date collisions occur *within* one Games by construction. Real discriminators are sport and event name. Where the question supplies neither, return a disambiguation request naming the candidates and count how often it fires |
| Aggregation under-tested on public set (31 examples) vs hidden set (50%) | Synthetic aggregation test set generated from corpus |
| Infobox parser misses edge-case formats | `parse_confidence` field + coverage report; fail loudly on unparseable `competitors` rather than silently returning a wrong count |
| Dashboard build eats remaining time | Static build; CLI + screenshots fallback — numbers are judged, not CSS |
