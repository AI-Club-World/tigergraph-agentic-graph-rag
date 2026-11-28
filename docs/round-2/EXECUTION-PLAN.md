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
