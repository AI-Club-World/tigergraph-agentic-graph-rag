# Round 2 - Architecture spec

Describes the Round-2 answering system as built on branch `round-2` (offline
tested; never run live). Brief: [PROBLEM-STATEMENT.md](PROBLEM-STATEMENT.md).
Contract: [SOLUTION-DESIGN.md](SOLUTION-DESIGN.md). Decisions:
[INTERVIEW-LOG.md](INTERVIEW-LOG.md). Round-1 architecture
([../round-1/ARCHITECTURE-SPEC.md](../round-1/ARCHITECTURE-SPEC.md)) is unchanged and
shares only the graph, the loader and the LLM client.

## 1. Overview

```
corpus.jsonl --(build.sh: ogr.cli r2-build; no LLM, no embeddings)--> TigerGraph graph + graph_counts.json

question --(run.sh: ogr.cli r2-run)--> agent loop (LLM, native tool calling, temperature 0)
              |  plan -> tool calls -> results -> ... (at most R2_MAX_STEPS tool calls)
              |  each tool = one installed GSQL query (or the local helper rank_rows)
              v
          finish(status, answer, explanation, citations) -> guards -> answer record
              |                                                         |
              +--> trace (written as it runs)       out/r2/tg_query_log.jsonl (one line per TigerGraph call)
          answers.jsonl --> r2-score (public) --> r2-metrics --> out/r2/metrics.json
```

One system answers (D2). The three-pipeline comparison of Round 1 stays in the
demo UI and is not part of `run.sh`.

## 2. Components

| Component | Module | Role |
|---|---|---|
| Corpus model | `ogr.r2.corpus_model` | One deterministic pass over `corpus.jsonl`: events and medallists (with NOCs), athletes, one Entity and Fact per non-Olympic infobox key, the 39 LA 2028 source records with authority and publication time, `REPORTS_ON` links, text chunks. No LLM, no network |
| Build | `ogr.r2.build`, `build.sh` | Reset graph, install Round-1 schema, the earlier fact layer, `schema_r2_answer.gsql`, the ten `r2_*` queries and Round-1 Q1-Q5; load documents, chunks (without embeddings) and the Round-2 layer; write vertex and edge counts |
| Graph | TigerGraph | Round-1 types (Document, Chunk, OlympicEvent, Games, Sport, Venue) plus Athlete, WON, SourceRecord, REPORTS_ON, Entity, Claim, ASSERTS, ABOUT |
| Tools | `ogr.r2.tools`, `graph_backend` | Ten read tools, one GSQL query each, behind the `R2Graph` interface; `TigerGraphR2` calls the server, `LocalR2Graph` (dev and tests) returns the same rows in Python |
| Agent | `ogr.r2.agent` | The loop, the system prompt, the guards |
| Output | `ogr.r2.output`, `trace`, `querylog`, `metrics` | Answer record and validator, trace recorder, query log, `metrics.json` |
| Evaluation | `ogr.r2.score`, `split` | Fact-level public scorer; deterministic dev/check split |

## 3. Graph additions (D3)

| Type | Meaning |
|---|---|
| `Athlete` | One per distinct medallist name in Olympic infoboxes; id is the normalised name |
| `WON` (Athlete to OlympicEvent) | medal (gold/silver/bronze), NOC, place, event key |
| `SourceRecord` | One per LA 2028 source record: source name, authority class, publication time (ISO with offset and the original text), body text |
| `REPORTS_ON` (SourceRecord to OlympicEvent) | Deterministic link from event names, sport words and venues, with a score |
| `Entity`, `Claim` (infobox facts) | For every non-Olympic infobox (film, office holder, person): one Entity per document and one Claim per infobox key; `ASSERTS` from the document, `ABOUT` to the Entity |

Authority classes come from a general lexicon over the `Source:` line:
`official`, `operational`, `secondary`, `unreliable` (`unclassified` when no
rule fires). Source records are **not** LLM-extracted at build (deviation from
D4); the answering LLM weighs them.

## 4. Tools

`find_events`, `medals_by_nation`, `event_series`, `athlete_medals`,
`repeat_winners`, `entity_facts`, `find_entities`, `source_records`,
`text_search`, `read_document`. Local helper `rank_rows` sorts an earlier
result (a `tigergraph: false` step). `finish` ends the loop. Parameters and
row shapes: [TECHNICAL-SPEC.md](TECHNICAL-SPEC.md) section 2.

## 5. How the agent decides

The model is given a short general prompt and the question, plans, and calls
tools, several at once when independent. It sees each result (compact JSON, at
most 60 rows, truncation stated) and decides the next call. It ends with
`finish`. After `R2_MAX_STEPS` tool calls (default 8) a final `finish` is
forced. There is no hand-written router: the choice of tools is the model's.

Prompt rules (general, no question-specific content): corpus only; complete
lists; the three statuses; unknown is not negative; authority order official >
operational > secondary > unreliable; a later publication does not override a
more authoritative one; provisional is not final; effective time differs from
publication time; registered is not competed; cite supporting doc_ids.

Guards applied to the model's `finish` (deterministic):
citations are kept only if a tool returned that doc_id in this question; status
`not_in_corpus` forces a null answer; an unknown status becomes `partial`; an
empty answer with another status becomes `not_in_corpus`; a JSON-looking string
answer is parsed. An exception on one question yields a record with an error that
is not written, so a rerun retries it.

## 6. Trace, log, metrics

Every LLM call is a trace step with the provider's token counts (an estimate is
marked in `note`). Every graph call is a step with `query`, `params`, `rows`,
`ms` and a line in the query log (start time in UTC to the millisecond, run id,
qid, step). Answer token totals are the sum over LLM steps; the validator checks
it. `metrics.json` is recomputed from the answer files only.

## 7. Decisions

D1-D7 and the D4 deviation: [INTERVIEW-LOG.md](INTERVIEW-LOG.md). Not on the
answering path: the Agentic-vs-RAG pipelines and the claim-resolution layer
(section E below).

## 8. Open points

Model choice (D5); GSQL never installed; parity between `LocalR2Graph` and the
GSQL unchecked on a server; see [RESULTS.md](RESULTS.md) sections 3-4.

---

## Earlier work, not on the answering path

Round-2 architecture from before the real brief (claim resolver, temporal
scope, harness). It is still in the repository and tested, but `ogr.r2` does
not call it: `ogr.r2` imports no module of `ogr.reasoning`, `ogr.harness` or
`ogr.pipelines`. The one trace of it: `ogr.r2.build` imports helpers from
`ogr.ingest.load_claims`, a module that itself imports `ogr.reasoning` at load
time; the helpers used (`_claim_attrs`, `_upsert_vertices`, `_upsert_edges`)
do not call it. The Round-2 graph build also still installs the earlier fact
layer types (Entity, Claim, Source, Dataset) via `install_round2`, and reuses
Entity and Claim for infobox facts. The text below is the earlier spec,
unchanged except for heading levels.

Extends [../round-1/ARCHITECTURE-SPEC.md](../round-1/ARCHITECTURE-SPEC.md):
the Round-1 containers, agents, routing and decision log are unchanged and
still apply.

### E1. Overview

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

### E2. Decision log (Round 2)

Gate decisions with their full context: [INTERVIEW-LOG.md](INTERVIEW-LOG.md).

| Id | Decision | Status |
|---|---|---|
| R2-G1 | Round-2 fact layer in the same graph, scoped by dataset (Option A), additive types, Q1–Q5 untouched | Decided by the user 2026-10-24 ([INTERVIEW-LOG.md](INTERVIEW-LOG.md)) |
| R2-G2 | Answer confidence computed by the agent from the claims (P3 only); shared answer prompt unchanged | Decided 2026-10-24 |
| R2-G3 | Optional LLM temporal field in the intent parse, only if the dev split shows the deterministic detector falls short | Allowed 2026-10-24; not built |
| R2-G4 | LLM claim extraction at ingest, Round-2 datasets only, only if needed | Allowed 2026-10-24; not built |
| R2-5 | Conflict resolution is deterministic and inspectable; the LLM phrases the answer; when the model answers a value the resolution ranked lower, the resolved value stands (logged on the trace) | Followed (`orchestrator.node_generate`) |
| R2-6 | One corroborating search when the resolved value's share is below `MARGIN` (0.6); then commit (answer policy: always answer, with confidence and cited losers) | Followed |
