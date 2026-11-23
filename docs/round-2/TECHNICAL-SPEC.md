# Round 2 — Technical spec

Extends [../round-1/TECHNICAL-SPEC.md](../round-1/TECHNICAL-SPEC.md) (stack,
Round-1 schema, Q1–Q5, record contracts, evaluation), which still applies.

Design, plan, gate decisions and results: [DESIGN.md](DESIGN.md),
[PLAN.md](PLAN.md), [INTERVIEW-LOG.md](INTERVIEW-LOG.md), [RESULTS.md](RESULTS.md). Summary
of what is implemented:

| Area | Module | Notes |
|---|---|---|
| Dataset adapters | `datasets/` (`base`, `olympic`, `block_records`) | `SourceRecord`/`ClaimRecord`; `detect_adapter` picks one per dataset (sidecar `adapter`, else record metadata). `block_records` is an **[ASSUMPTION]** about the Round-2 format |
| Temporal scope | `pipelines/temporal.py` | deterministic; modes `none, as_of, before, after, between, latest, original`; before/after/since/between scope a fact only next to a revision cue or "as of" |
| Relations | `reasoning/relations.py` | `SUPERSEDES` (later + revision cue or same source; a hedged statement never supersedes a firm one), `CONTRADICTS` (different values, overlapping validity) |
| Reliability | `reasoning/reliability.py` | dataset prior, else class prior **[ASSUMPTION]** (`CLASS_PRIORS`), else agreement-based estimate |
| Resolution and confidence | `reasoning/resolve.py` | scope filter → drop superseded → score each value (reliability, corroboration, recency, extraction, hedging) → softmax share × noisy-or support → Platt; numbers answered without qualifiers |
| Calibration | `eval/calibration.py` | ECE (10 bins), Brier, Platt fit with Platt's smoothed targets |
| Harness | `harness/` | `python -m ogr.cli harness [--offline]` (see [RESULTS.md](RESULTS.md)) |
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

**Status:** the GSQL has not been installed on Savanna yet; tests run
against fakes.
