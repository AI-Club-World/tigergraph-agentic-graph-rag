# Round 2 - Run history

Dated engineering log of the Round-2 bring-up, development runs and the final submission
run (all 2026-11-28, times UTC). Per-run reports are in [`runs/`](runs/). The submitted
numbers are in `submission/round-2/metrics.json`; this page only narrates how they came about.
Model for every LLM run below: `nvidia/nemotron-3.5-super-vl-120b-a12b` (native tool calls).

| When | Step | Result |
|---|---|---|
| Build 1 | First `./build.sh` on the TigerGraph workspace | Succeeded after fixes: the edge `DESCRIBES` renamed `OG_DESCRIBES` (the global edge name was already used by another graph in the workspace); `SumAccum<STRING>` instead of `StringAccum`; list-parameter size via `FOREACH`; the schema cache is refreshed after schema-change jobs; counts are read after the asynchronous upserts settle (the first snapshot was about half). Settled counts equalled the offline model. About 11.5 minutes. |
| Parity | `backend/scripts/r2_parity.py`: each tool on TigerGraph and on the in-process copy, 26 parameter sets | 17 of 22 identical at first; 26 of 26 after four fixes: the `WON` edge keeps the athlete name as each event writes it (`athlete_name`); `repeat_winners` groups by athlete id; `event_series` tie-break on the matching edition is the same on both sides; gold order is `(place, name)` on both sides. One of 10,764 modelled `WON` rows merges with another on the server (10,763 stored). |
| Smoke | 3 public questions on TigerGraph | Token sums per answer equal the LLM steps; every TigerGraph step matched a query-log line; answers validated. |
| Dev baseline | Local backend, `dev` split (36) | 77.0% / 80.5% on two runs ([report](runs/dev-local-baseline.md)). |
| Dev fixes | General prompt and tool changes from error analysis (medal scope, NOC codes, series answer shape, status policy, stating the basis, redundant-field trimming; prompt `r2-agent-v2`) | Dev accuracy 80.5 to 90.8% on the local backend, status match 32 to 34 of 36; run-to-run noise about 3 points ([report](runs/dev-local-after-fixes.md)). |
| Dev and check | Live TigerGraph, public split, `check` run once | dev 86.2% (status 32/36), check 81.3% (status 12/14); tokens mean about 12.7k to 12.9k per question; TigerGraph calls per question 3.0 and 3.9 ([report](runs/live-tg-dev-check.md)). |
| Final | Clean build, then `FRESH=1 ./run.sh` for the public set and once for the hidden set; code commit `1114450`, files committed under `submission/round-2/` | Build 753 s. Public run 608 s: 88.8% on our own scorer. Hidden run 712 s: answered 42, partial 3, `not_in_corpus` 5; hidden accuracy not computed. The validator passed with 0 errors and 0 warnings over 338 query-log entries. |

Final-run figures (from `submission/round-2/metrics.json`): tokens per question 13.2k (public)
and 18.6k (hidden); latency p50 / p95 9.5 s / 27.4 s (public) and 12.2 s / 24.9 s (hidden);
TigerGraph queries per question 3.34 and 3.42; LLM calls per question 3.06 and 3.12.

Notes: the query log and outputs are relative to the working directory, so the final run
set `R2_QUERY_LOG` to an absolute path and moved the outputs to `out/r2/` (no code change).
`cost_usd_total` is 0 because no price variables were set. The graph has no rows for
`Source`, `Dataset`, `SUPERSEDES`, `CONTRADICTS`, `FROM_SOURCE`, `IN_DATASET` or the
embedding types: the earlier claim-resolution layer is not used in Round 2.
