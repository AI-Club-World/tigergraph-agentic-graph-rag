# Live TigerGraph run: dev and check splits (2026-11-28)

**Public split only. Backend `tigergraph`, model `nvidia/nemotron-3.5-super-vl-120b-a12b`, native tool calls. Not a submission.** Hidden file not opened; `build.sh` not run (graph `OlympicGraphRAG` already built). Check split run exactly once, no iteration.

Commands: `r2-run --backend tigergraph` (dev 36 qids, then check 14 qids), `r2-score --split dev|check --split-file docs/round-2/data/public_split.json`, `scripts/validate_submission.py` on the combined public answers. Answers and query log are untracked (`out/r2/`).

## Headline

| Split | Questions | Accuracy | Status match | Tokens mean / median | Latency mean / p50 / p95 | TG calls per question |
|---|---:|---:|---:|---:|---:|---:|
| dev (live TG) | 36 | 86.2 | 32/36 | 12,746 / 9,464 | 10.9 s / 9.5 s / 19.5 s | 3.0 |
| check (live TG, once) | 14 | 81.3 | 12/14 | 12,930 / 11,325 | 11.8 s / 9.2 s / 26.1 s | 3.9 |

- Tokens = input + output per question. Latency = per-question wall time recorded by the agent.
- Comparison: local-backend dev run of W2 (same model, same code) scored 90.8% with status match 34/36. Live TigerGraph dev scores 86.2% with 32/36. The gap (4.6 points, 2 status misses) is larger than the 1-3 point noise seen between local iterations, so the live backend is treated as a real difference to investigate (retrieval misses on 020, 021, 024 are the main cause).
- Thresholds: dev >= 80% and validator clean on the public answers, so Part B ran.

## Validator

`scripts/validate_submission.py` on the 50 public answers (dev + check): **0 public errors** (fields, statuses, token sums, citations, query-log match all passed for public).
Remaining errors are only the artifacts this step does not produce: `answers_hidden.jsonl` missing, hidden qids missing, `metrics.json` missing, `graph_counts.json` missing. Query log: 163 entries.

## Per-question table: dev

| qid | status | gold status | score | tokens | ms | steps | reason (score < 1) |
|---|---|---|---:|---:|---:|---|---|
| r2-pub-001 | answered | answered | 1.00 | 6,911 | 9,822 | 3 (1 TG) |  |
| r2-pub-002 | answered | answered | 1.00 | 8,535 | 10,869 | 4 (1 TG) |  |
| r2-pub-003 | answered | answered | 0.78 | 9,459 | 9,181 | 3 (1 TG) | row set/fields differ from gold list (partial credit) |
| r2-pub-005 | answered | answered | 1.00 | 8,205 | 6,558 | 3 (1 TG) |  |
| r2-pub-006 | answered | answered | 1.00 | 8,893 | 23,991 | 4 (1 TG) |  |
| r2-pub-008 | answered | answered | 1.00 | 9,469 | 8,987 | 3 (1 TG) |  |
| r2-pub-009 | answered | answered | 0.97 | 19,514 | 22,156 | 6 (2 TG) | all years and counts match; extra annotation on the 2028 row |
| r2-pub-011 | answered | answered | 1.00 | 15,113 | 12,550 | 6 (3 TG) |  |
| r2-pub-012 | answered | answered | 1.00 | 6,890 | 5,933 | 3 (1 TG) |  |
| r2-pub-013 | answered | answered | 0.99 | 6,818 | 6,466 | 3 (1 TG) | includes a team event (Mixed/team) that gold lists only as individual events |
| r2-pub-014 | answered | answered | 0.93 | 6,490 | 6,034 | 4 (2 TG) | row set/fields differ from gold list (partial credit) |
| r2-pub-015 | answered | answered | 0.86 | 6,486 | 7,297 | 3 (1 TG) | counts a team event (Mixed team) that gold does not list |
| r2-pub-017 | answered | answered | 1.00 | 7,727 | 7,632 | 3 (1 TG) |  |
| r2-pub-018 | answered | answered | 1.00 | 10,302 | 7,472 | 6 (3 TG) |  |
| r2-pub-022 | answered | answered | 1.00 | 10,984 | 8,042 | 5 (2 TG) |  |
| r2-pub-023 | answered | answered | 1.00 | 17,519 | 9,122 | 9 (5 TG) |  |
| r2-pub-024 | not_in_corpus | answered | 0.00 | 18,449 | 11,614 | 13 (8 TG) | status not_in_corpus, gold answered: the basis is in the corpus but retrieval missed it |
| r2-pub-025 | answered | answered | 1.00 | 14,265 | 11,498 | 3 (1 TG) |  |
| r2-pub-026 | answered | answered | 1.00 | 9,592 | 8,282 | 3 (1 TG) |  |
| r2-pub-028 | not_in_corpus | not_in_corpus | 1.00 | 48,155 | 18,095 | 13 (8 TG) |  |
| r2-pub-029 | partial | partial | 0.86 | 16,581 | 13,718 | 12 (8 TG) | 2008 shown as null row, gold uses found/not_in_corpus split; shape differs |
| r2-pub-030 | answered | answered | 1.00 | 21,087 | 10,446 | 10 (5 TG) |  |
| r2-pub-032 | answered | answered | 0.90 | 19,734 | 18,679 | 14 (8 TG) | all three athletes present; field shape differs from gold |
| r2-pub-033 | answered | answered | 1.00 | 8,435 | 5,993 | 4 (1 TG) |  |
| r2-pub-036 | answered | answered | 1.00 | 7,845 | 6,419 | 4 (1 TG) |  |
| r2-pub-037 | answered | answered | 1.00 | 6,500 | 5,005 | 4 (2 TG) |  |
| r2-pub-038 | answered | answered | 1.00 | 7,399 | 6,783 | 4 (1 TG) |  |
| r2-pub-042 | answered | answered | 1.00 | 7,511 | 6,930 | 4 (2 TG) |  |
| r2-pub-043 | answered | answered | 0.83 | 8,727 | 17,100 | 4 (2 TG) | correct No, but basis cites the non-authoritative directory entry and draft; does not name the signed July 1 assignment |
| r2-pub-044 | answered | answered | 0.33 | 13,430 | 10,442 | 7 (4 TG) | venue correct, but temporal basis (effective from signed July 1 allocation) missing |
| r2-pub-045 | answered | answered | 0.67 | 7,265 | 13,449 | 4 (2 TG) | entries 42 and competitors 40 correct; nations (31) omitted |
| r2-pub-046 | not_in_corpus | not_in_corpus | 1.00 | 21,438 | 13,062 | 12 (7 TG) |  |
| r2-pub-047 | partial | answered | 0.50 | 27,571 | 17,195 | 12 (8 TG) | status partial vs gold answered; explanation hedges on timing instead of stating population vs authority |
| r2-pub-048 | answered | partial | 0.40 | 16,999 | 15,257 | 11 (7 TG) | status answered vs gold partial; states a duration narrative instead of "no verified duration" |
| r2-pub-049 | answered | not_in_corpus | 0.00 | 11,512 | 13,564 | 7 (4 TG) | status answered vs gold not_in_corpus; the answer itself says no confirmed stoppage exists |
| r2-pub-050 | answered | answered | 1.00 | 7,032 | 6,855 | 4 (2 TG) |  |

## Per-question table: check

| qid | status | gold status | score | tokens | ms | steps | reason (score < 1) |
|---|---|---|---:|---:|---:|---|---|
| r2-pub-004 | answered | answered | 0.80 | 10,487 | 11,310 | 7 (5 TG) | all four winners correct; object shape with NOC codes differs from gold rows |
| r2-pub-007 | answered | answered | 1.00 | 19,227 | 15,373 | 6 (2 TG) |  |
| r2-pub-010 | answered | answered | 0.92 | 21,315 | 38,772 | 9 (5 TG) | all counts match; extra note on the 2028 row |
| r2-pub-016 | answered | answered | 0.91 | 6,319 | 4,988 | 3 (1 TG) | event and year right; medal field omitted from rows |
| r2-pub-019 | answered | answered | 1.00 | 7,024 | 5,400 | 4 (2 TG) |  |
| r2-pub-020 | not_in_corpus | answered | 0.00 | 14,987 | 11,173 | 13 (8 TG) | status not_in_corpus, gold answered: the cause is in the corpus but retrieval missed it |
| r2-pub-021 | not_in_corpus | answered | 0.00 | 15,292 | 14,841 | 13 (8 TG) | status not_in_corpus, gold answered: the cause is in the corpus but retrieval missed it |
| r2-pub-027 | answered | answered | 1.00 | 8,102 | 5,354 | 3 (1 TG) |  |
| r2-pub-031 | not_in_corpus | not_in_corpus | 1.00 | 23,709 | 10,154 | 12 (7 TG) |  |
| r2-pub-034 | answered | answered | 0.75 | 6,340 | 5,494 | 4 (2 TG) | event names only, no year/medal per row |
| r2-pub-035 | answered | answered | 1.00 | 12,163 | 8,321 | 3 (1 TG) |  |
| r2-pub-039 | answered | answered | 1.00 | 7,593 | 6,653 | 5 (3 TG) |  |
| r2-pub-040 | answered | answered | 1.00 | 7,829 | 8,221 | 5 (3 TG) |  |
| r2-pub-041 | answered | answered | 1.00 | 20,633 | 19,280 | 9 (6 TG) |  |

Score < 1 reasons are one line each and paraphrase the gold; gold answers are not copied here.

## Notes

- First dev scoring attempt failed because `r2-score` resolves the split file relative to cwd (run from `backend/`); re-run with `--split-file`. Scores are unaffected.
- The first run wrote the query log to `backend/out/r2/`; moved to `out/r2/tg_query_log.jsonl` (repo root, as the runbook says). The check run wrote to the same log via `R2_QUERY_LOG`.
- Status misses: 020, 021, 024 (gold answered, agent not_in_corpus, retrieval); 047, 048, 049 (partial/answered/not_in_corpus policy). 
