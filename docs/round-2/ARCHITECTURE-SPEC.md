# Round 2 — Architecture spec

Extends [../round-1/ARCHITECTURE-SPEC.md](../round-1/ARCHITECTURE-SPEC.md):
the Round-1 containers, agents, routing and decision log are unchanged and
still apply.

## 1. Overview

Full design in [DESIGN.md](DESIGN.md); results in [RESULTS.md](RESULTS.md).

```
question ─► intent parse (LLM) ─► entity linking ─► temporal scope (rules) ─► claim probe (Q6, 0 tokens)
                                                                                │
                      claims matter (time-scoped, disagreeing or hedged)? ─────┤
                      no  ─► Round-1 route, unchanged                           │
                      yes ─► loop: claims tool ─► resolution (scope → supersession → score → confidence)
                                     │ share < MARGIN ─► one corroborating Q5 search
                                     ▼
                     shared answer prompt (context = labelled candidate values, chosen first)
                                     ▼
                     answer kept to the resolved value · confidence · conflicts · conflict_resolved
```

- **Dataset adapter layer** (`datasets/`): a new dataset needs a new
  adapter; the reasoning code reads only `ClaimRecord`/`SourceRecord`.
- **Fact layer** in the graph (`Dataset, Source, Entity, Claim` and
  `IN_DATASET, ASSERTS, FROM_SOURCE, ABOUT, SUPERSEDES, CONTRADICTS`), next
  to the unchanged Round-1 types.
- **Where the LLM is used in Round 2:** nowhere new. Temporal scope,
  relations, reliability, resolution and confidence are deterministic; the
  existing intent parse and answer generation are unchanged.
- **Known limitations:** see [RESULTS.md](RESULTS.md) §4 (synthetic harness, the
  evolving subset is easy once parsed, a coordinated false majority without
  reliability information, per-subset calibration, block-only claim
  extraction, GSQL not yet installed on Savanna).

## 2. Decision log (Round 2)

Gate decisions with their full context: [INTERVIEW-LOG.md](INTERVIEW-LOG.md).

| Id | Decision | Status |
|---|---|---|
| R2-G1 | Round-2 fact layer in the same graph, scoped by dataset (Option A), additive types, Q1–Q5 untouched | Decided by the user 2026-10-24 ([INTERVIEW-LOG.md](INTERVIEW-LOG.md)) |
| R2-G2 | Answer confidence computed by the agent from the claims (P3 only); shared answer prompt unchanged | Decided 2026-10-24 |
| R2-G3 | Optional LLM temporal field in the intent parse, only if the dev split shows the deterministic detector falls short | Allowed 2026-10-24; not built |
| R2-G4 | LLM claim extraction at ingest, Round-2 datasets only, only if needed | Allowed 2026-10-24; not built |
| R2-5 | Conflict resolution is deterministic and inspectable; the LLM phrases the answer; when the model answers a value the resolution ranked lower, the resolved value stands (logged on the trace) | Followed (`orchestrator.node_generate`) |
| R2-6 | One corroborating search when the resolved value's share is below `MARGIN` (0.6); then commit (answer policy: always answer, with confidence and cited losers) | Followed |
