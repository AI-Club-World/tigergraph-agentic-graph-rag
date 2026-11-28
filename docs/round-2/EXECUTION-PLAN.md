# Round 2 — Execution plan (deadline 29 Nov 2026 23:59 IST = 18:29 UTC)

Orchestrator: the main Claude session. Workers report here (RUNLOG section)
and in their final messages. Never open `docs/round-2/data/questions_hidden.jsonl`
except through `run.sh` in the final hidden run (W5).

## Workstreams

| Id | Owner | Branch | Files it may change | Needs credentials | Depends on |
|---|---|---|---|---|---|
| W1 bring-up: connectivity, `build.sh`, GSQL fixes, tool parity, smoke run | Claude session (Sonnet) | `round-2` | `backend/src/ogr/graph/**`, `backend/src/ogr/r2/{graph_backend,build,local_graph}.py`, their tests, `docs/round-2/EXECUTION-PLAN.md` (RUNLOG) | yes | – |
| W2 dev baseline + error analysis + general fixes (prompt/tools) | Claude session (Sonnet review, Haiku runs) | `round-2` | `backend/src/ogr/r2/{agent,tools}.py`, tests | yes | W1 |
| W3 check-split score (once), freeze | Claude session (Haiku) | `round-2` | none (results only) | yes | W2 |
| W4 final runs: clean build, public + hidden once, metrics, query log, counts, validation, tag | Claude session (Haiku, Sonnet review) | `round-2` | `submission/round-2/**` | yes | W3, G1 |
| G1 submission validator | Gemini (Antigravity) | `r2-g1-validator` | `scripts/validate_submission.py`, `backend/tests/r2/test_validate_submission.py` | no | – |
| G2 text-mode tool calling (fallback when the model has no native tools) | Gemini (Antigravity) | `r2-g2-text-tools` | `backend/src/ogr/r2/text_tools.py`, a guarded hook in `r2/agent.py`, tests | no | – |
| G3 live-judging kit + README Round-2 polish | Gemini (Antigravity) | `r2-g3-demo-kit` | `docs/round-2/LIVE-JUDGING.md`, README Round-2 sections only | no | – |

Rules for every worker: no question-specific rules (no regex on question
wording, no qids, no built-in answers); keep `cd backend && ruff check src tests
&& python3 -m pytest -q -p no:cacheprovider` green; small commits with clear
messages; never print or commit secrets; never rewrite history.

## RUNLOG (append, newest last; UTC times)

- 2026-11-28 11:05 — plan written; credentials present in the environment (TG_*, LLM_*, EMBEDDING_HOST_URL).
- 2026-11-28 W1 — offline suite green (928 passed, ruff clean). TG_GRAPHNAME=OlympicGraphRAG (ok).
- 2026-11-28 W1 — **BLOCKER (TigerGraph)**: the workspace is stopped. `https://<id>.tg-2635877100.i.tgcloud.io/api/restpp/echo` (and every other `/api/*` path) returns HTTP 500 `{"message": "Auto start is not enabled for this workspace"}`; pyTigerGraph calls (echo/getVertexTypes/getVersion) get the Cloud Workspace HTML page. Same cause as Round 1 (SCORE-AUDIT #5): the owner must start the workspace in TigerGraph Cloud (or enable auto-start). Steps 2–4 cannot proceed until then; no credentials issue, nothing tried can fix it from here.
- 2026-11-28 W1 — **BLOCKER (LLM)**: `GET /models` ok (30 models). `POST /chat/completions` with LLM_MODEL=`nvidia/nemotron-3-super-120b-a12b` returns HTTP 410 "has reached its end of life on 2026-10-03 and is no longer available". Tool-call probe (no config changed; same one-function request) on listed models: `nvidia/nemotron-3-ultra-550b-a55b` ok 1.8 s, tool_calls + usage present; `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` ok 2.2 s, tool_calls + usage; `nvidia/nemotron-3.5-bolt-e4b` ok 0.8 s, tool_calls + usage. Orchestrator must pick a replacement LLM_MODEL (ask the owner; the rules may require a specific model).
- 2026-11-28 11:32 W1 — LLM probe with LLM_MODEL=nvidia/nemotron-3.5-super-vl-120b-a12b: HTTP 200, 1.4 s, tool_calls present (get_weather{city:Paris}), usage present (281 in / 115 out, incl. 89 reasoning tokens). Native tool calls OK. TigerGraph still down (HTTP 502 auto-start); polling every 5 min.
- 2026-11-28 11:38 W1 — TigerGraph workspace UP (echo ok; first poll that passed was 11:37 UTC). Starting build.
- 2026-11-28 11:38 W1 — **BLOCKER (TigerGraph privileges)**: workspace is up, auth works, but graph `OlympicGraphRAG` does not exist (`SHOW GRAPH` → 'doesn't exist'; build.sh fails with HTTP 404 on /gsql/v1/schema/graphs/OlympicGraphRAG) and user `tg-hackathon` cannot create it: `CREATE GRAPH` → 'does not have the permission ... Required privilege on global: WRITE_SCHEMA'. `LS`/`SHOW ROLE` also denied (READ_SCHEMA/READ_ROLE). schema.gsql runs at global scope (DROP GRAPH ... CASCADE, CREATE GRAPH, global vertex/edge types) so it needs a superuser or a role with WRITE_SCHEMA (+ query-install rights). Owner must either grant this user the superuser/admin role (preferred) or run schema.gsql + schema_round2.gsql + schema_r2_answer.gsql once as admin. Steps 2–4 blocked; I am stopping.
- 2026-11-28 11:44 W1 — **BLOCKER (graph name/privileges), question for orchestrator**: env now TG_GRAPHNAME=tigergraph-rag, LLM_MODEL=nvidia/nemotron-3.5-super-vl-120b-a12b; echo ok. `SHOW GRAPH *` → 'No graph available. Please create a graph first.' (no graphs exist at all). getVertexTypes on 'tigergraph-rag' → 404 .../gsql/v1/schema/graphs/tigergraph-rag; `USE GRAPH tigergraph-rag` is a GSQL parse error (hyphen invalid). `CREATE GRAPH` still denied: user tg-hackathon lacks global WRITE_SCHEMA. So nothing can be built: the user needs admin/WRITE_SCHEMA, and the graph name must be a valid identifier (the GSQL hard-codes OlympicGraphRAG). Stopped; not renaming anything.
- 2026-11-28 11:44 — H1 dev baseline (backend=local, dev only, not a submission; model nvidia/nemotron-3.5-super-vl-120b-a12b): dev accuracy 77.0% over 36; status match 31/36; tokens/question mean 13.2k (median 9.3k); latency mean 13.1 s, p50 9.3 s, p95 24.9 s; 16 imperfect (medal scope 2, format 3, shape 3, status 4, missing items 4). See docs/round-2/runs/dev-local-baseline.md.
- 2026-11-28 reviewer — G1 r2-g1-validator MERGED unchanged: fields/statuses/token sums/not_in_corpus null/metrics recompute/query-log match checked against the brief and ogr.r2 modules; accepted real `--backend local` output of 2 dev questions (0 errors; only the expected "no TigerGraph step" warnings). Not run on the hidden file.
- 2026-11-28 reviewer — G2 r2-g2-text-tools MERGED unchanged: default path in agent.py untouched (hook only when R2_TOOL_MODE=text); text loop reuses `_call`/`run_tool`/`_finalize` so citation, not_in_corpus, token and max-step guards apply; one retry on malformed reply, then forced finish, then partial with the raw text. Not exercised against a live model.
- 2026-11-28 reviewer — G3 r2-g3-demo-kit MERGED with fixes: LIVE-JUDGING.md rewritten as a reproduction runbook (removed call plan, walkthrough script, "likely judge questions" Q&A, mid-call fallback script, Kaggle specifics, unverifiable anti-overfitting claim); README heading restored to "Round 2: build, run, submit" (SUBMISSION.md links to it). Commands/paths/routes checked (/round2, /r2/ask, /r2/status, build.sh, run.sh, r2-* subcommands). Suite: 948 passed, ruff clean.
