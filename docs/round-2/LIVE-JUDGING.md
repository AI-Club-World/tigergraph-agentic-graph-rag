# Round 2 — Live reproduction runbook

How to start the system, ask it a new question, and reproduce a submitted answer
with TigerGraph running and the full corpus loaded. Operational steps only; the
architecture is described in the README ("Round 2 architecture") and in
`docs/round-2/SOLUTION-DESIGN.md`.

Results are not repeated here: see `submission/round-2/metrics.json` (once
generated) for the numbers of the submitted runs.

## 1. Before the call

1. `.env` at the repo root (copy of `.env.example`) with the TigerGraph (`TG_*`) and LLM (`LLM_*`)
   settings used for the submission runs. Use the same `LLM_MODEL`, `R2_MAX_STEPS` (default `8`)
   and `R2_TOOL_MODE` (unset = native tool calling) as for the submission.
2. TigerGraph workspace running (a stopped workspace answers HTTP 500/502 on `/api/restpp/echo`).
3. Corpus loaded: `./build.sh docs/round-2/data/corpus.jsonl`; compare `out/r2/graph_counts.json`
   with the live counts.
4. Checkout the submission tag `round2-submission` with a clean working tree.
5. Backend and UI:
   ```bash
   python -m uvicorn ogr.api.main:app --app-dir backend/src --host 127.0.0.1 --port 8000
   cd frontend && npm run dev          # http://localhost:5173
   curl -s http://127.0.0.1:8000/r2/status   # expect "schema_installed": true
   ```

## 2. Ask a new question

- UI: open `http://localhost:5173/round2` (page "Round 2 agent"), type the question, press Ask.
  The result shows status, answer, citations and the full trace (LLM steps with tokens; graph
  steps marked `TigerGraph` with query, params, rows, ms).
- API:
  ```bash
  curl -s -X POST http://127.0.0.1:8000/r2/ask -H "Content-Type: application/json" \
    -d '{"question": "<QUESTION>", "backend": "tigergraph"}'
  ```
- Batch file instead of one question:
  `cd backend && python3 -m ogr.cli r2-run --questions <q.jsonl> --out /tmp/new.jsonl --query-log /tmp/new_tg_log.jsonl`

## 3. Reproduce a submitted answer

Write to scratch paths so the submitted files stay untouched:

```bash
cd backend && python3 -m ogr.cli r2-run \
  --questions ../docs/round-2/data/questions_hidden.jsonl \
  --out /tmp/repro.jsonl --qids <QID> --query-log /tmp/repro_tg_log.jsonl
```

Compare `/tmp/repro.jsonl` with the `<QID>` line of `answers_hidden.jsonl` (status, answer,
citations, trace tools, `query`, `params`, `rows`) and `/tmp/repro_tg_log.jsonl` with the
`<QID>` lines of `out/r2/tg_query_log.jsonl`. LLM wording and token counts can differ between
runs even at temperature 0; graph rows for the same query and parameters do not.

Check the submission files at any time:
`python3 scripts/validate_submission.py` (see `--help` for paths).

## 4. Notes

- `--backend local` (in-process copy of the corpus) is development only: its steps carry
  `tigergraph: false` and write no query log. It is never a live TigerGraph run.
- `R2_TOOL_MODE=text` switches the agent to prompt-based JSON tool calls for models without
  native tool calling (`backend/src/ogr/r2/text_tools.py`); the guards in `_finalize` still apply.
