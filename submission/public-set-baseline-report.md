# Run report: `r1-public`

- Questions: **100** (100 with ground truth)
- LLM (all three pipelines): `openai_compatible/nvidia/nemotron-3-super-120b-a12b`
- Embeddings: `bge-large-en-v1.5` via `embedding_host`
- Mode: `throughput`, pool 2, k=10, max steps 6
- Started: 2026-09-27T14:55:35.857686+00:00

## Headline

| Pipeline | EM | F1 | Completeness | Grounded | Median tokens | Mean in / out | Mean latency | Errors |
|---|---|---|---|---|---|---|---|---|
| RAG | 0.62 | 0.67 | 0.74 | 0.92 | 6,433 | 6,010 / 706 | 16.1 s | 0 |
| GraphRAG | 0.37 | 0.40 | 0.28 | 0.29 | 2,616 | 1,476 / 1,975 | 31.5 s | 0 |
| Agentic GraphRAG | 0.74 | 0.78 | 0.70 | 0.72 | 4,700 | 4,865 / 1,953 | 54.1 s | 0 |

## Where the agent pays for itself

Agentic − RAG accuracy gap and its token cost per question type (the mean of per-question Agentic ÷ RAG token ratios, as on the dashboard). Verdict: gap ≥ 0.5 worth it, ≤ 0.05 overkill, else marginal.

| Type | n | RAG EM | GraphRAG EM | Agentic EM | Agentic − RAG | Agentic ÷ RAG tokens | Verdict |
|---|---|---|---|---|---|---|---|
| lookup | 19 | 1.00 | 0.68 | 0.74 | -0.26 | 0.59× | Overkill |
| aggregation | 21 | 0.19 | 0.76 | 0.71 | 0.52 | 0.33× | Worth it |
| superlative | 10 | 0.00 | 0.00 | 0.00 | 0.00 | 0.61× | Overkill |
| temporal | 22 | 1.00 | 0.32 | 0.95 | -0.05 | 1.45× | Overkill |
| multi_hop | 28 | 0.61 | 0.04 | 0.86 | 0.25 | 1.77× | Marginal |

Agentic right where RAG was wrong: **20** (pub-001, pub-003, pub-010, pub-011, pub-020, pub-024, pub-027, pub-030, pub-033, pub-038, pub-058, pub-065, pub-064, pub-069, pub-076, pub-078, pub-089, pub-096, pub-095, pub-098)  
RAG right where Agentic was wrong: **8** (pub-025, pub-048, pub-052, pub-061, pub-060, pub-068, pub-074, pub-093)

## Necessity routing

| Route | Questions | Median agentic tokens | Agentic EM |
|---|---|---|---|
| direct | 53 | 2,109 | 0.60 |
| loop | 47 | 11,461 | 0.89 |

*Estimate:* answering the 53 direct-route questions through the loop at the loop's median cost would have spent about **471,162** more tokens.

## Agents and tools

| Agent | Invocations | Tokens | Tokens / call | Time / call |
|---|---|---|---|---|
| orchestrator | 100 | 221,679 | 2,217 | 25,530 ms |
| entity_linking | 100 | 0 | 0 | 0 ms |
| answer_generation | 100 | 381,154 | 3,812 | 9,749 ms |
| evidence_evaluation | 99 | 78,940 | 797 | 3,649 ms |
| graph_traversal | 75 | 0 | 0 | 52 ms |
| multi_hop_reasoning | 43 | 0 | 0 | 419 ms |
| aggregation | 33 | 0 | 0 | 56 ms |
| similarity_search | 27 | 0 | 0 | 2,729 ms |
| document_retrieval | 25 | 0 | 0 | 2,644 ms |

Tools called: `intent_parser` ×100, `entity_linker` ×100, `generate` ×100, `evidence_evaluator` ×99, `Q1` ×44, `Q4` ×31, `Q5` ×27, `HAS_CHUNK` ×25, `Q2` ×24, `Q1→Q4→Q1` ×23, `Q4(HELD_AT)→Q1` ×20, `Q3` ×9

Stop reasons: `direct_route` ×53, `sufficient_evidence` ×27, `no_further_action_available` ×20
  
Strategy changed on **42** of 100 questions; median 4 trace steps.

