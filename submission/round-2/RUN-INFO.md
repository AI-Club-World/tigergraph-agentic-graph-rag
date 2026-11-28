# Round 2 submission run info

- Date (UTC): 2026-11-28
- Code commit that produced the answers: 11144501cd2d10abed0663464917321894663b28. The tag round2-submission sits on the packaging commit that adds submission/round-2/ (code unchanged).
- LLM model: nvidia/nemotron-3.5-super-vl-120b-a12b (native tool calls)
- TigerGraph: release_4.2.6_11-06-2026 (graph name OlympicGraphRAG)
- Commands (from the repo root, after `python3 -m pip install -q -e "backend[dev]"`):
  1. `./build.sh docs/round-2/data/corpus.jsonl` (clean build; reset and reload the graph)
  2. `FRESH=1 ./run.sh docs/round-2/data/questions_public.jsonl answers_public.jsonl` (run, self-score, metrics; exit 0, no resume)
  3. `FRESH=1 ./run.sh docs/round-2/data/questions_hidden.jsonl answers_hidden.jsonl` (run once; exit 0, no resume)
  - Both run steps used `R2_QUERY_LOG=<repo>/out/r2/tg_query_log.jsonl` so the query log lands at the repo root.
  - Validation: `python3 scripts/validate_submission.py` with the submission paths.
- Wall times: build 753 s (about 12.5 min); public run 608 s (about 10 min); hidden run 712 s (about 12 min).
- Public accuracy: 88.8% over 50 questions (own fact-level scorer, see metrics.json accuracy_method). Hidden accuracy: not computed (null).
- Hidden status counts: answered 42, partial 3, not_in_corpus 5.
- Files: answers_public.jsonl, answers_hidden.jsonl, metrics.json, tg_query_log.jsonl, graph_counts.json, score_public.json (public score).
