---
path: specs/003-agentic-graphrag/implementation-plan-AGENT.md
implements_tasks: AGENT
level: implementation-plan
derived_from: TECHNICAL-SPEC.md, ARCHITECTURE-SPEC.md, APPLICATION-SPEC.md
cache: volatile
tier: LOCALISED
gate: G1 -> G4
status: approved
plan_id: PLAN-003
task_tracker: ./task.md
sub_plans: []
---

# Agentic GraphRAG (P3 pipeline) — Implementation Plan

**Module name**: taken verbatim from MODULE-BREAKDOWN.md § "Module: Agentic GraphRAG (P3 pipeline)"
**Source spec**: TECHNICAL-SPEC §7, §8.3 · ARCHITECTURE-SPEC §3, §4, §5, §8 · APPLICATION-SPEC FR-5/6/7/11/12/16
**Workspace**: `backend/src/ogr/pipelines/p3_agentic/`
**Task tracker**: [task.md](./task.md)
**Stack (fixed)**: Python · **LangGraph** for the orchestrator state machine · LangChain for provider abstraction, function-calling and usage callbacks · pyTigerGraph for all graph access
**Effort (T1 scope)**: 13 pt of the 60 pt Round-1 target · **most internally sequential module**

> DELIVERY-STREAMS §2 already flags this as the likely critical path. With
> parallel code assistants the constraint changes shape but does not disappear:
> Groups 2 and 3 parallelise across assistants, Groups 1, 4 and 5 do not.
> Start Group 1 at hour zero — it has no graph dependency.

---

## Research Summary

- **Current state**: greenfield. Groups 1 and 2 depend only on the LLM provider
  and can begin before TigerGraph exists. Groups 3–5 depend on PLAN-001 G1.
- **Gaps identified**: **8 distinct** across 5 groups.
- Findings that change the plan:
  - **"Fully-specified" and "underspecified" anchor are undefined.** They are
    the entire routing criterion (ARCHITECTURE-SPEC §5, FR-11), which makes
    FR-11 untestable as written and AGENT-02 unbuildable. The innovation claim
    of the submission rests on a predicate nobody has defined. See DP-1.
  - **The intent schema is strictly more expressive than the query library.**
    §7 emits `anchor{sport, games, venue, title}` and a **list** of constraints;
    Q2 accepts one constraint and no venue, Q3 accepts no constraints at all.
    Any parse carrying a venue anchor or two constraints has nowhere to
    dispatch. Resolved upstream by widening Q2/Q3 (PLAN-001 Group 3); this plan
    depends on that widening and must not work around it locally.
  - **Q5 and document retrieval are listed as agents with no trigger.**
    ARCHITECTURE-SPEC §4 names them; no operation routes to them and no failure
    condition invokes them. They are currently unreachable code.
  - **Empirical proof the prose fallback is required**: hidden question
    `eval-001` asks about "Olympic Tennis Centre", a string appearing in **zero**
    `venue` fields across 2,162 Olympic documents. 9 of 10 hidden venue-anchored
    questions match a corpus venue verbatim; this one does not. Without a
    fallback it is an unforced zero on a scored question.
  - **Entity linking is a dictionary lookup, not a model.** All three anchor
    vocabularies are closed and small: **21** games values, **41** sports,
    **303** venues. Longest-match is required (`Olympic Oval` is a substring of
    `Richmond Olympic Oval`; `Riocentro` of `Riocentro – Pavilion 4`).
    AGENT-03 drops to S.
  - **No qtype→operation mapping exists.** Five question types, four operations.
    `qtype` is a label supplied by the eval set and must **never** be an input
    to routing, or NFR-7 is violated by construction.
  - **The Evidence Evaluator is described as deterministic while containing a
    groundedness check** (ARCHITECTURE-SPEC §3 and §4). NFR-6 constrains only
    the *scoring* loop, so this is not a contradiction — but as worded it reads
    as one, and a judge will ask.
  - **The hidden set is 50% aggregation+superlative** (15 + 10 of 50) versus 31%
    public (21 + 10 of 100). Confirmed by counting both files. The agentic path
    must be strongest exactly where the public set gives least practice.
  - **Two required trace fields are missing**: the guidebook measures "number of
    chunks and citations" per step; `TraceStep` has neither. Resolved in
    PLAN-004 DP-1.
  - **LangGraph maps onto ARCHITECTURE-SPEC §3 almost one-to-one**, which
    removes work rather than adding it: Necessity Router → conditional edge from
    the intent node · each specialised agent → a node · Evidence Evaluator →
    node · Stopping-Criteria Evaluator → conditional edge to `END` ·
    Strategy-Change Detector → a reducer over a `path_taken` list in state ·
    Trace Recorder → `astream_events`, which is already SSE-shaped. The
    guidebook's required "agent harness to manage state, tools, context,
    evidence, and stopping criteria" is `StateGraph` plus a typed state object.
  - **LangGraph's checkpointer gives batch resume close to free**, which
    overlaps with the resume behaviour PLAN-004 Group 3 builds. Use one or the
    other, not both — two resume mechanisms is a debugging trap on day 3.
  - **Token accounting through LangChain needs deliberate setup.** TECHNICAL-SPEC
    §9 requires provider-reported usage only, prompt and completion tracked
    separately, at the lowest invocation point (NFR-3). LangChain returns usage
    on `AIMessage.usage_metadata`, but several chat integrations **omit usage
    when streaming** unless usage streaming is explicitly enabled, and callback
    aggregation across a LangGraph run can double-count a retried call. This is
    the highest-probability source of a wrong headline number.
  - **Do not use LangChain's graph QA chains.** `GraphCypherQAChain` and
    text-to-query equivalents are exactly the text-to-GSQL generation
    TECHNICAL-SPEC §7 rejects by name, with the documented failure modes it
    lists. Dispatch stays `operation → Q1–Q5`.

---

## Design Decisions Required Before Implementation

### DP-1 — Definition of "fully-specified anchor" (blocks AGENT-02)

**Gap**: ARCHITECTURE-SPEC §5 and FR-11 route on this predicate; nothing defines
it. Every routing test and the whole necessity-routing claim depend on it.

| # | Approach | Cost | Breaking? | Notes |
|---|---|---|---|---|
| **A** *(Recommended)* | Mechanical rule over the §7 schema: fully-specified ⇔ (`anchor.title` or `anchor.event_id` non-null) **and** `target_field` non-null **and** `constraints` empty. Everything else is underspecified | S | No | Deterministic, one line, testable, and directly defensible in Q&A against Adaptive-RAG's learned classifier |
| B | LLM judges specificity per question | M | No | Non-deterministic routing; the strategy-change and step-count metrics become noisy |
| C | Route on `qtype` | S | No | **Violates NFR-7** — `qtype` is an eval-set label, so this is branching on the eval set |

**Recommendation**: Option A. It also resolves the Q1 signature problem: Q1 takes
`title | event_id`, so a LOOKUP anchored only on sport+games has no Q1 form —
under rule A such a query is underspecified and routes to the loop, which is
correct behaviour rather than a gap.
**Selected**: **A** · **by**: `team lead` · **on**: `2026-09-21`

### DP-2 — Fallback trigger rules for similarity search and document retrieval

**Gap**: two of the seven named agents are unreachable; `eval-001` proves at
least one scored question needs them.

| # | Approach | Cost | Breaking? | Notes |
|---|---|---|---|---|
| **A** *(Recommended)* | Trigger on evidence-evaluator outcome: scope-coverage fail → Q5 similarity expansion; groundedness fail or empty anchor resolution → `HAS_CHUNK` prose retrieval. Each fallback sets `strategy_change: true` | M | No | Makes both agents reachable, gives the Strategy-Change Detector something real to detect, and covers `eval-001` |
| B | Always run Q5 alongside the structured query | S | No | Doubles token cost on every question and destroys the cost-honesty argument (US-5) |
| C | Leave them unreachable | — | No | Two of seven guidebook-named specialised agents would be dead code — visible in the repo and in Q&A |

**Recommendation**: Option A.
**Selected**: **A** · **by**: `team lead` · **on**: `2026-09-21`

### DP-3 — Loop budget and `stop_reason` vocabulary

**Gap**: AD-3 requires stopping on evidence sufficiency or budget; no budget
value and no closed `stop_reason` set exists, yet the dashboard reports a
stop-reason breakdown.

| # | Approach | Cost | Breaking? | Notes |
|---|---|---|---|---|
| **A** *(Recommended)* | `max_steps = 6`, `max_tokens_per_query = 20000`, both in `run_config`; closed vocabulary: `sufficient_evidence`, `step_budget_exhausted`, `token_budget_exhausted`, `no_further_action_available`, `disambiguation_required`, `error` | S | No | Bounded, reportable as a frequency table, and `disambiguation_required` connects to PLAN-001 DP-4 |
| B | Free-text stop reasons | S | No | Unaggregatable; the dashboard's stop-reason chart becomes a word cloud |
| C | Fixed 3-step loop | S | No | **Rejected by AD-3** — a fixed step count is not agentic per the hackathon definition |

**Recommendation**: Option A.
**Selected**: **A** · **by**: `team lead` · **on**: `2026-09-21`

### DP-4 — Groundedness check: LLM or deterministic

**Gap**: the Evidence Evaluator is called deterministic while performing a
groundedness check.

| # | Approach | Cost | Breaking? | Notes |
|---|---|---|---|---|
| **A** *(Recommended)* | Deterministic scope-coverage gate + **one** LLM groundedness call, clearly labelled; README states that no LLM sits in the **scoring** path | M | No | Preserves NFR-6 exactly as written and removes the apparent contradiction; groundedness is a retrieval decision, not a score |
| B | Deterministic only — assert every answer token appears in retrieved evidence | S | No | Cheap and fully reproducible, but brittle on paraphrased generation |
| C | LLM-only evaluation | M | No | Reintroduces non-determinism into the agentic loop and weakens AD-4's argument |

**Recommendation**: Option A, with B implemented first as the gate and the LLM
call added only if time allows.
**Selected**: **A** · **by**: `team lead` · **on**: `2026-09-21`

### DP-5 — Token accounting through LangChain

**Gap**: the headline comparison is a token ratio. LangChain can under-report
usage when streaming and can double-count retried calls, and the spec requires
provider-reported figures split into prompt and completion.

| # | Approach | Cost | Breaking? | Notes |
|---|---|---|---|---|
| **A** *(Recommended)* | One accounting module wrapping every model call; read `usage_metadata` off each `AIMessage`, enable usage-on-stream explicitly, attribute each figure to a `step_n`, and reconcile the sum of `TraceStep.tokens` against the record total with an assertion | M | No | Satisfies NFR-3 and §9; the reconciliation assertion is what catches under-reporting before a judge does |
| B | `get_openai_callback`-style aggregate per run | S | No | Gives a run total but no per-step attribution, so the agentic step-cost chart cannot be built |
| C | Estimate with a tokenizer post-hoc | S | No | §11 forbids it — estimated, not provider-reported |

**Recommendation**: Option A. The reconciliation assertion is non-negotiable:
without it, a silently-zero usage field reads as "the agentic path is free."
**Selected**: **A** · **by**: `team lead` · **on**: `2026-09-21`

---

## Open Questions (non-blocking)

- Whether to use LangGraph's checkpointer or PLAN-004's JSONL resume. Pick one.
- Exact function-calling tool definition wording for the intent parser.
- Whether the multi-hop planner chains Q4→Q1 or Q4→Q2 for venue-anchored
  questions (mechanical once DP-1 lands).
- Retry count on schema-validation failure: spec says one; no reason to change.

---

## Proposed Changes

### Group 1 — Intent parsing (3 pt) · **starts hour zero, no graph dependency**

#### ADD `backend/src/ogr/pipelines/p3_agentic/intent.py`
- Emits `{operation, anchor, constraints, target_field}` per TECHNICAL-SPEC §7,
  Pydantic-validated with **one** retry on failure.
- **Two extraction paths, one output** (PLAT-08). The capability probe in
  `LLM-01` decides at startup: native tool-calling where the configured model
  supports it, JSON-schema prompting where it does not — which is the common
  case for locally-hosted models. Both paths produce the identical intent object
  and share the same validation and retry, so routing behaviour does not change
  with the provider. The run header records which path was active, because a
  comparison across runs that silently switched extraction method is not a
  comparison.
- Explicit `qtype → operation` mapping documented in the module docstring, with
  a stated rule that `qtype` is never read at runtime (NFR-7).
- No regex, no template matching, no eval-string branching anywhere.
- **Requirement**: `FR-12`, `NFR-7` · **Gate**: `G4`
- **Rollback**: revert; P3 cannot run, P1/P2 unaffected.

#### ADD `backend/src/ogr/pipelines/p3_agentic/router.py`
- Necessity routing per ARCHITECTURE-SPEC §5, with "fully-specified" resolved
  by DP-1. Emits the initial routing decision as a recorded value so the
  Strategy-Change Detector has a baseline to compare against.
- **Requirement**: `FR-11`, `AD-5` · **Gate**: `G4`
- **Rollback**: revert to always-loop; correct but expensive, and it destroys
  the cost-honesty comparison (US-5).

### Group 2 — Anchor resolution (1 pt) · **parallelisable**

#### ADD `backend/src/ogr/pipelines/p3_agentic/agents/entity_linking.py`
- Longest-match dictionary resolution against the closed vocabularies:
  21 games, 41 sports, 303 venues. Built once at startup from the graph.
- Date anchors normalized via `backend/src/ogr/common/dates.py` — the **same**
  normalizer ingestion uses (PLAN-001 DP-1). Do not write a second one.
- Returns unresolved anchors explicitly rather than guessing; an unresolved
  venue is the `eval-001` case and must reach the DP-2 fallback.
- **Requirement**: ARCHITECTURE-SPEC §4 · **Gate**: `G4`
- **Rollback**: revert; anchors fall through to similarity search.

### Group 3 — Tool agents (2 pt) · **fully parallelisable across assistants**

#### ADD `agents/graph_traversal.py`, `agents/similarity_search.py`, `agents/document_retrieval.py`, `agents/aggregation.py`, `agents/multi_hop.py`
- Thin wrappers over Q4, Q5, `HAS_CHUNK` expansion, Q2/Q3, and a Q4→Q1 chain
  respectively. Each returns a uniform `AgentResult` carrying evidence,
  `chunks_returned`, `citations_count`, tokens and latency.
- Several are a single query. That is the correct amount of machinery for five
  question types and is stated as such, not apologised for.
- **Requirement**: ARCHITECTURE-SPEC §4 · **Gate**: `G4`
- **Rollback**: per-agent; the router degrades to the remaining tools.

### Group 4 — Evidence, stopping, strategy (4 pt) · **sequential**

#### ADD `p3_agentic/evidence.py`
- Deterministic scope-coverage gate (did retrieval cover the anchor's required
  scope?), plus the groundedness check per DP-4.
- Surfaces the `parse_confidence` exclusion count from Q2/Q3 in `notes` — this
  is what makes "the system tells you what it could not parse" demonstrable.
- **Requirement**: ARCHITECTURE-SPEC §3 · **Gate**: `G4`
- **Rollback**: revert to always-sufficient; loop becomes single-shot.

#### ADD `p3_agentic/stopping.py`
- Sufficiency or budget per DP-3; emits a `stop_reason` from the closed set.
- **Requirement**: `FR-7`, `AD-3` · **Gate**: `G4`
- **Rollback**: none — removing this makes P3 unbounded.

#### ADD `p3_agentic/strategy.py`
- Compares the executed path against the router's recorded initial decision;
  sets `strategy_change: true` on the deviating step and `strategy_changed` on
  the record.
- **Requirement**: `FR-6` · **Gate**: `G4`
- **Rollback**: field defaults to `false`; dashboard chart empties.

#### ADD `p3_agentic/trace.py`
- Emits `TraceStep` records per PLAN-004 DP-1, including `chunks_returned` and
  `citations_count`, and the reconciled per-step tokens from DP-5.
- Built on LangGraph `astream_events`, so the same generator serves both the
  live SSE trace panel (PLAN-004 Group 4) and the collected `trace` array in
  the batch record. **One emitter, two consumers** — assembling the trace twice
  is how the demo and the submitted metrics drift apart (AD-1, AD-2).
- **Requirement**: `FR-5`, `NFR-3` · **Gate**: `G4`
- **Rollback**: revert; `trace` field becomes null and agentic-effectiveness
  evidence (15% of the rubric) is lost — treat removal as escalation-worthy.

### Group 5 — Orchestrator assembly (3 pt) · **not splittable across assistants**

#### ADD `backend/src/ogr/pipelines/p3_agentic/orchestrator.py`
- LangGraph `StateGraph` implementing the ARCHITECTURE-SPEC §8 runtime view.
  Typed state: `question, intent, route_initial, path_taken[], evidence[],
  steps[], tokens, strategy_changed, stop_reason`.
- Nodes: `parse_intent` · `link_entities` · one node per tool agent ·
  `evaluate_evidence` · `generate`.
  Conditional edges: after `parse_intent` the necessity router picks
  `lookup_direct | scoped_aggregate | loop`; after `evaluate_evidence` the
  stopping criteria picks `continue | generate | END`.
- `path_taken` is an append-only reducer; `strategy_changed` is derived by
  comparing it against `route_initial` rather than being set imperatively in
  five places.
- Generation uses the shared answer contract (`CORE-02`), prompt byte-identical
  to P1's and P2's apart from retrieved context — any prompt difference between
  pipelines becomes a confound in the measured accuracy gap.
- Emits a `PipelineRecord` with full trace, `strategy_changed`, `stop_reason`.
- **LOOKUP must traverse zero loop edges.** If the graph is built so that every
  question passes through `evaluate_evidence`, necessity routing exists on
  paper only and US-5 (agentic costs 10× for no gain on simple lookups) cannot
  be demonstrated.
- **Requirement**: `FR-2`, `FR-4`, `FR-5`, `FR-6`, `FR-7`, `FR-11` · **Gate**: `G4`
- **Rollback**: revert to router-direct (no loop); P3 becomes a second P2 and
  the submission loses its thesis — escalate rather than ship this silently.

#### ADD `acceptance/paraphrase/paraphrase_set.jsonl`
- ~15 hand-authored paraphrases of public questions: same intents, different
  surface forms. Scored separately from the eval sets.
- This is the anti-overfitting evidence and it is a MUST, unlike the synthetic
  aggregation set which is cut under T0.
- **Requirement**: `FR-16`, `NFR-7` · **Gate**: `G5`
- **Rollback**: none; without it the anti-overfitting claim is unevidenced.

---

## Verification Plan

### Automated

```
pytest -q backend/tests/pipelines/p3
python -m ogr.cli ask "<one question per operation type>" --pipelines agentic --show-trace
```

| Group | New tests | Command | Verdict |
|---|---|---|---|
| 1 | `test_intent_schema_validates`, `test_retry_once_on_invalid_schema`, `test_no_qtype_read_at_runtime` | `pytest -q backend/tests/pipelines/p3/test_intent.py` | `unmeasured` |
| 1 | `test_routing_lookup_direct`, `test_routing_count_scoped`, `test_routing_traverse_loops` | `pytest -q backend/tests/pipelines/p3/test_router.py` | `unmeasured` |
| 2 | `test_longest_match_venue` (Richmond Olympic Oval, not Olympic Oval), `test_unresolved_venue_returns_none` (the `eval-001` shape) | `pytest -q backend/tests/pipelines/p3/test_entity_linking.py` | `unmeasured` |
| 3 | one conformance test per agent returning `AgentResult` | `pytest -q backend/tests/pipelines/p3/test_agents.py` | `unmeasured` |
| 4 | `test_stop_reason_in_closed_vocabulary`, `test_budget_exhaustion_stops_loop`, `test_strategy_change_flagged_on_refallback` | `pytest -q backend/tests/pipelines/p3/test_loop.py` | `unmeasured` |
| 5 | `test_p3_conforms_to_pipeline_record_and_tracestep`, `test_paraphrase_set_same_intents` | `pytest -q backend/tests/pipelines/p3/test_orchestrator.py` | `unmeasured` |

- **Anti-overfitting review is a named verification step, not a vibe**: grep the
  whole answer path for eval-set strings and for any `qtype` read at runtime.
  ARCHITECTURE-SPEC §13 calls this the highest-probability failure mode, so it
  gets a command, not an intention.
- **Holdout**: no test in this module reads `acceptance/holdout/`. The
  paraphrase set is deliberately a *separate* directory from the holdout.
- **Unmeasured is a real outcome.**

### Manual

- Run one question per operation (LOOKUP, COUNT, ARGMAX, TRAVERSE) and read the
  trace end to end. Confirm the LOOKUP question takes **no** loop iterations —
  if everything loops, necessity routing is not doing anything and the central
  claim is unsupported.
- Run the `eval-001`-shaped venue question and confirm it reaches the prose
  fallback rather than returning nothing.

---

## Execution Order

1. Group 1 → **verify**: routing tests pass against mocked parses (starts at
   hour zero, before any graph exists)
2. Group 2 → **verify**: longest-match and unresolved-anchor tests
3. Group 3 → **verify**: per-agent conformance (parallel across assistants)
4. Group 4 → **verify**: loop terminates on both sufficiency and budget
5. Group 5 → **verify**: full P3 record conforms; one question per operation
   traced by hand (**G4**)
6. Final re-analysis pass: per-qtype P3 results reviewed for any qtype where P3
   loses to P2 — that is either a bug or a finding, and it must be named either
   way

---

## Sub-plan externalization

| Sub-plan | Scope | File | Status |
|---|---|---|---|
| PLAN-003-a | Group 3 tool agents, if handed to separate assistants in parallel | ./plans/group-3-agents.md | not created |

---

## Stop conditions

- DP-1 reached unselected — AGENT-02 cannot be written without it
- Any eval-set phrasing or `qtype` read appears in the answer path
- The loop fails to terminate within budget on any question
- A change would weaken `max_steps` or `max_tokens_per_query` in order to make a
  question pass — that is weakening the gate that judges the work
- P3 is about to ship without a working loop (router-direct only) — escalate;
  this is the submission's thesis, not an optimisation
- Group 5 not started by midday of day 3 — cut to LOOKUP/COUNT/ARGMAX paths
  only, report TRAVERSE as a stated limitation, and ship something honest
