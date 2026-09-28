# Run report: `r2-public`

- Questions: **100** (100 with ground truth)
- LLM (all three pipelines): `openai_compatible/nvidia/nemotron-3-super-120b-a12b`
- Embeddings: `bge-large-en-v1.5` via `embedding_host`
- Mode: `throughput`, pool 2, k=10, max steps 6
- Started: 2026-09-27T15:57:59.654766+00:00

## Headline

| Pipeline | EM | F1 | Completeness | Grounded | Median tokens | Mean in / out | Mean latency | Errors |
|---|---|---|---|---|---|---|---|---|
| RAG | 0.62 | 0.67 | 0.74 | 0.92 | 6,404 | 6,010 / 655 | 39.5 s | 0 |
| GraphRAG | 0.49 | 0.53 | 0.50 | 0.38 | 2,335 | 1,526 / 1,850 | 91.3 s | 0 |
| Agentic GraphRAG | 0.80 | 0.83 | 0.68 | 0.75 | 4,516 | 4,526 / 1,954 | 127.4 s | 0 |

## Where the agent pays for itself

Agentic − RAG accuracy gap and its token cost per question type (the mean of per-question Agentic ÷ RAG token ratios, as on the dashboard). Verdict: gap ≥ 0.5 worth it, ≤ 0.05 overkill, else marginal.

| Type | n | RAG EM | GraphRAG EM | Agentic EM | Agentic − RAG | Agentic ÷ RAG tokens | Verdict |
|---|---|---|---|---|---|---|---|
| lookup | 19 | 1.00 | 0.89 | 1.00 | 0.00 | 0.53× | Overkill |
| aggregation | 21 | 0.19 | 0.86 | 0.86 | 0.67 | 0.33× | Worth it |
| superlative | 10 | 0.00 | 0.20 | 0.20 | 0.20 | 0.94× | Marginal |
| temporal | 22 | 1.00 | 0.45 | 1.00 | 0.00 | 1.16× | Overkill |
| multi_hop | 28 | 0.61 | 0.07 | 0.68 | 0.07 | 1.75× | Marginal |

Agentic right where RAG was wrong: **19** (pub-001, pub-003, pub-004, pub-010, pub-011, pub-020, pub-024, pub-027, pub-033, pub-037, pub-045, pub-058, pub-064, pub-065, pub-069, pub-076, pub-078, pub-087, pub-089)  
RAG right where Agentic was wrong: **1** (pub-083)

## Necessity routing

| Route | Questions | Median agentic tokens | Agentic EM |
|---|---|---|---|
| direct | 56 | 1,945 | 0.84 |
| loop | 44 | 11,668 | 0.75 |

*Estimate:* answering the 56 direct-route questions through the loop at the loop's median cost would have spent about **514,884** more tokens.

## Agents and tools

| Agent | Invocations | Tokens | Tokens / call | Time / call |
|---|---|---|---|---|
| orchestrator | 100 | 240,625 | 2,406 | 70,432 ms |
| entity_linking | 100 | 0 | 0 | 0 ms |
| answer_generation | 100 | 341,429 | 3,414 | 41,297 ms |
| evidence_evaluation | 86 | 65,871 | 766 | 14,288 ms |
| graph_traversal | 75 | 0 | 0 | 89 ms |
| multi_hop_reasoning | 38 | 0 | 0 | 392 ms |
| aggregation | 29 | 0 | 0 | 87 ms |
| similarity_search | 26 | 0 | 0 | 686 ms |
| document_retrieval | 18 | 0 | 0 | 1,960 ms |

Tools called: `intent_parser` ×100, `entity_linker` ×100, `generate` ×100, `evidence_evaluator` ×86, `Q1` ×47, `Q4` ×28, `Q5` ×26, `Q2` ×22, `Q4(HELD_AT)→Q1` ×19, `Q1→Q4→Q1` ×19, `HAS_CHUNK` ×18, `Q3` ×7

Stop reasons: `direct_route` ×56, `sufficient_evidence` ×28, `no_further_action_available` ×16
  
Strategy changed on **35** of 100 questions; median 4 trace steps.

