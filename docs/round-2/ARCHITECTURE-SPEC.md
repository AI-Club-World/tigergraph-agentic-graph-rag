# Round 2 - Architecture spec

Describes the Round-2 answering system. Brief: [PROBLEM-STATEMENT.md](PROBLEM-STATEMENT.md).
Contract: [SOLUTION-DESIGN.md](SOLUTION-DESIGN.md). Round-1 architecture
([../../archive-round-1/docs/round-1/ARCHITECTURE-SPEC.md](../../archive-round-1/docs/round-1/ARCHITECTURE-SPEC.md)) is unchanged and
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

One system answers. The three-pipeline comparison of Round 1 stays in the
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

## 3. Graph additions

| Type | Meaning |
|---|---|
| `Athlete` | One per distinct medallist name in Olympic infoboxes; id is the normalised name |
| `WON` (Athlete to OlympicEvent) | medal (gold/silver/bronze), NOC, place, event key |
| `SourceRecord` | One per LA 2028 source record: source name, authority class, publication time (ISO with offset and the original text), body text |
| `REPORTS_ON` (SourceRecord to OlympicEvent) | Deterministic link from event names, sport words and venues, with a score |
| `Entity`, `Claim` (infobox facts) | For every non-Olympic infobox (film, office holder, person): one Entity per document and one Claim per infobox key; `ASSERTS` from the document, `ABOUT` to the Entity |

Authority classes come from a general lexicon over the `Source:` line:
`official`, `operational`, `secondary`, `unreliable` (`unclassified` when no
rule fires). Source records are **not** LLM-extracted at build; the answering LLM weighs them.

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

## 7. Not on the answering path

The Agentic-vs-RAG pipelines (Round 1) and the earlier claim-resolution layer
(`ogr.reasoning`, `ogr.harness`, `ogr.datasets`, the P3 claim tools). They stay
in the repository and are tested; `ogr.r2` does not call them. The one trace of
them: `ogr.r2.build` imports helpers from `ogr.ingest.load_claims`, a module
that itself imports `ogr.reasoning` at load time; the helpers used do not call
it. The graph build also installs the earlier fact-layer types (Entity, Claim,
Source, Dataset) and reuses Entity and Claim for infobox facts. The earlier
design is in [DESIGN.md](DESIGN.md).

## 8. Checking the GSQL against the Python copy

`backend/scripts/r2_parity.py` runs each tool on TigerGraph and on
`LocalR2Graph` for a fixed set of parameters and compares the rows:
`cd backend && python3 scripts/r2_parity.py --verbose`.
