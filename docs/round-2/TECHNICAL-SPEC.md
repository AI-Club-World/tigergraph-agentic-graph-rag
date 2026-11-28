# Round 2 - Technical spec

How the Round-2 answering system is built. Contract:
[SOLUTION-DESIGN.md](SOLUTION-DESIGN.md); overview:
[ARCHITECTURE-SPEC.md](ARCHITECTURE-SPEC.md). Round-1 stack and schema:
[../../archive-round-1/docs/round-1/TECHNICAL-SPEC.md](../../archive-round-1/docs/round-1/TECHNICAL-SPEC.md).

## 1. Code map (`backend/src/ogr/r2/`)

| Module | Content |
|---|---|
| `corpus_model` | Parser and in-memory model; `classify_authority`, `build_model` |
| `build` | `build(corpus, client, counts_path)`, `load_r2_layer`, `graph_counts` |
| `graph_backend` | `R2Graph` protocol, `QueryResult`, `TigerGraphR2`, `QUERY_NAMES`, `series_extremes` |
| `local_graph` | `LocalR2Graph`, same rows in Python (dev and tests) |
| `tools` | Tool specs for the LLM, `run_tool`, `rank_rows`, `ToolContext` (doc_ids seen) |
| `agent` | `SYSTEM_PROMPT` (`PROMPT_VERSION`), `answer_question` |
| `run` | `run_questions` (resumable, optional threads), model and graph factories |
| `output`, `trace`, `querylog`, `metrics` | Record and validator, recorder, log, metrics |
| `score`, `split` | Public scorer, dev/check split |
| `cmds` | CLI subcommands `r2-build`, `r2-run`, `r2-score`, `r2-metrics` (wired in `ogr.cli`) |

GSQL: `backend/src/ogr/graph/schema_r2_answer.gsql` and
`backend/src/ogr/graph/queries/r2_*.gsql`, installed by `ogr.graph.schema`
(`install_r2_answer`).

## 2. Tools

One installed query each; the query name is the trace `query`. Matching is
case-insensitive; `*_contains` matches at a word boundary of the normalised text.
Counts are per medal awarded (a relay is one medal).

| Tool / query | Parameters | Rows |
|---|---|---|
| `find_events` / `r2_find_events` | sport, year (0 = any), season, event_contains | event: ids, title, event name, sport, games, year, date, venue, competitors, nations, gold/silver/bronze with NOCs, synthetic |
| `medals_by_nation` / `r2_medals_by_nation` | sport, year, season, medal | noc, count, events |
| `event_series` / `r2_event_series` | event_contains, sport, season | one row per edition; wrapper adds max and min |
| `athlete_medals` / `r2_athlete_medals` | name | medal, NOC, event, year, doc_id |
| `repeat_winners` / `r2_repeat_winners` | sport, medal, season | athlete, event, years, doc_ids (same event, 2+ Games) |
| `entity_facts` / `r2_entity_facts` | name_contains, entity_type | entity, type, doc_id, facts {key: value} |
| `find_entities` / `r2_find_entities` | entity_type, predicate, value_contains | entities with all facts |
| `source_records` / `r2_source_records` | event_contains, year | doc_id, title, source name, authority, published_at, text |
| `text_search` / `r2_text_search` | terms (all must occur), limit | chunks: doc_id, title, chunk_id, text |
| `read_document` / `r2_read_document` | doc_id | title and chunks in order |

`rank_rows` and `series_extremes` are local, deterministic and recorded as
`tigergraph: false`. The GSQL compares lower-cased raw text; `LocalR2Graph`
compares normalised text, so accents and apostrophes can differ (apostrophes
are straightened before the query).

## 3. Agent loop

Native tool calling through `ogr.common.llm`, temperature 0, answer budget at
least 4096 tokens. Loop: model call (`plan` for the first, then `llm_step`),
execute its tool calls (each recorded), append results, repeat until `finish`
or `R2_MAX_STEPS` (default 8); then one forced `finish` (`llm_answer`). Rate
limits are retried with bounded backoff by `invoke_and_count`. Guards: see
[ARCHITECTURE-SPEC.md](ARCHITECTURE-SPEC.md) section 5. No qid, no question
wording and no answer is used in code.

## 4. Output formats

- **Answer line:** `qid, status, answer, explanation, citations, input_tokens,
  output_tokens, latency_ms, trace`.
- **Trace step:** `step, tool, tigergraph, ms`; TigerGraph steps add `query,
  params, rows`; LLM steps add `input_tokens, output_tokens`; optional `note`.
- **Query log** (`out/r2/tg_query_log.jsonl`, `R2_QUERY_LOG`): `ts, run_id, qid,
  step, query, params, rows, ms, ok, error`; `ts` is the call's start. Append-only.
- **`metrics.json`:** per set the fields of the brief's example; percentiles by
  nearest rank; cost from `R2_LLM_INPUT_USD_PER_M` and `R2_LLM_OUTPUT_USD_PER_M`
  (0 if unset, noted in `metrics_notes.json`).
- **`graph_counts.json`:** server `getVertexCount('*')` and `getEdgeCount('*')`.
- **`out/r2/score_public.json`:** per-question scores and the method.

## 5. Scripts and configuration

`build.sh corpus.jsonl` runs `ogr.cli r2-build`. `run.sh questions answers`
runs `r2-run`, then for a questions file with gold answers `r2-score` and
`r2-metrics`; the set name comes from the file name. Dependencies:
`backend/requirements.lock`. Keys: `.env.example` (TigerGraph, LLM, `R2_MAX_STEPS`,
`R2_LLM_*_USD_PER_M`, `R2_QUERY_LOG`). `r2-run` is resumable (skips qids already
in the output file); `--backend local` is dev only.

## 6. Earlier work, not on the answering path

The claim-resolution layer built before the real brief: dataset adapters
(`datasets/`), temporal scope (`pipelines/temporal.py`), relations,
reliability, resolution and calibration (`reasoning/`, `eval/calibration.py`),
the synthetic harness (`harness/`), the P3 claim tools. `ogr.r2` does not
import any of them (checked 2026-11-23 by searching its imports), except that
`ogr.r2.build` imports `ogr.ingest.load_claims` and `ogr.datasets.base`
(`ClaimRecord`), and `load_claims` imports `ogr.reasoning` at load time without
the build calling it. The graph types Entity and Claim (from
`graph/schema_round2.gsql`) are shared. Earlier spec, unchanged except
heading levels:

Extends [../../archive-round-1/docs/round-1/TECHNICAL-SPEC.md](../../archive-round-1/docs/round-1/TECHNICAL-SPEC.md) (stack,
Round-1 schema, Q1–Q5, record contracts, evaluation), which still applies.

Design: [DESIGN.md](DESIGN.md); older notes: [../archive/](../archive/README.md).
Summary of what is implemented:

| Area | Module | Notes |
|---|---|---|
| Dataset adapters | `datasets/` (`base`, `olympic`, `block_records`) | `SourceRecord`/`ClaimRecord`; `detect_adapter` picks one per dataset (sidecar `adapter`, else record metadata). `block_records` is an **[ASSUMPTION]** about the Round-2 format |
| Temporal scope | `pipelines/temporal.py` | deterministic; modes `none, as_of, before, after, between, latest, original`; before/after/since/between scope a fact only next to a revision cue or "as of" |
| Relations | `reasoning/relations.py` | `SUPERSEDES` (later + revision cue or same source; a hedged statement never supersedes a firm one), `CONTRADICTS` (different values, overlapping validity) |
| Reliability | `reasoning/reliability.py` | dataset prior, else class prior **[ASSUMPTION]** (`CLASS_PRIORS`), else agreement-based estimate |
| Resolution and confidence | `reasoning/resolve.py` | scope filter → drop superseded → score each value (reliability, corroboration, recency, extraction, hedging) → softmax share × noisy-or support → Platt; numbers answered without qualifiers |
| Calibration | `eval/calibration.py` | ECE (10 bins), Brier, Platt fit with Platt's smoothed targets |
| Harness | `harness/` | `python -m ogr.cli harness [--offline]` (see [DESIGN.md](DESIGN.md)) |
| Agent | `pipelines/p3_agentic/agents/claims.py`, `orchestrator.py`, `router.py` | probe → `claims` tool → deterministic evaluation (corroborate once below `MARGIN` 0.6) → answer kept to the resolved value → `conflict_resolved` |
| P2 | `p2_graphrag.py` | the same probe; claims as its one query; no confidence |

**Graph (additive, `graph/schema_round2.gsql`, local SCHEMA_CHANGE JOB, no drop):**
vertices `Dataset(dataset_id, title, adapter)`, `Source(source_id, name,
source_class, reliability_prior, has_prior, reliability_est)`,
`Entity(entity_id, name, entity_type)`, `Claim(claim_id, dataset_id, doc_id,
subject_id, subject_name, predicate, value_text, value_num, has_num,
valid_from, valid_to, observed_at, source_id, extraction_conf, hedged,
hedge_terms, revision)`; edges `IN_DATASET` (Document/Chunk/Claim/Source/Entity
→ Dataset), `ASSERTS` (Document → Claim), `FROM_SOURCE` (Document → Source),
`ABOUT` (Claim → OlympicEvent | Entity), `SUPERSEDES(reason)`,
`CONTRADICTS(reason)`. Dates are ISO strings (`""` = unknown).

**Queries:** `q6_claims(SET<STRING> subject_ids, STRING predicate, SET<STRING>
dataset_ids)` returns claim rows; relations are recomputed in Python by the
same code that wrote the edges. `q5s_search(query_vector, k, emb_type,
SET<STRING> dataset_ids)` is Q5 seeded from the datasets' chunks, used only
when a run passes `dataset_ids`; an unscoped run calls Q5 exactly as in Round 1.

**Loading:** `ingest/load_claims.py` (upserts only, `ABOUT` only to existing
events, relations and reliability weighed against the claims already in the
graph). API builds load claims inside the `install_graph_queries` stage when
the graph has the Round-2 types. `python -m ogr.cli round2` installs the
types and queries and backfills every registered dataset. A full CLI
`build` resets the graph and so removes the fact layer; run `round2` again
after it.

**Configuration:** `OGR_ROUND2_WEIGHTS` names a weights JSON written by
`harness --offline` (fitted on the dev split); defaults otherwise.

**Status:** this layer is not used by the Round-2 answering path; its tests
run against fakes.
