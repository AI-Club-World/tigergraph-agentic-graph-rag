# Run report: `r4-public`

- Questions: **100** (100 with ground truth)
- LLM (all three pipelines): `openai_compatible/nvidia/nemotron-3-super-120b-a12b`
- Embeddings: `bge-large-en-v1.5` via `embedding_host`
- Mode: `throughput`, pool 2, k=10, max steps 6
- Started: 2026-09-28T11:18:51.117652+00:00

## Headline

| Pipeline | EM | F1 | Completeness | Grounded | Median tokens | Mean in / out | Mean latency | Errors |
|---|---|---|---|---|---|---|---|---|
| RAG | 0.61 | 0.66 | 0.74 | 0.94 | 6,449 | 6,010 / 764 | 91.2 s | 0 |
| GraphRAG | 0.66 | 0.66 | 0.56 | 0.44 | 2,490 | 1,474 / 2,673 | 130.7 s | 0 |
| Agentic GraphRAG | 0.91 | 0.91 | 0.64 | 0.78 | 2,804 | 3,042 / 2,426 | 157.1 s | 0 |

## Where the agent pays for itself

Agentic − RAG accuracy gap and its token cost per question type (the mean of per-question Agentic ÷ RAG token ratios, as on the dashboard). Verdict: gap ≥ 0.5 worth it, ≤ 0.05 overkill, else marginal.

| Type | n | RAG EM | GraphRAG EM | Agentic EM | Agentic − RAG | Agentic ÷ RAG tokens | Verdict |
|---|---|---|---|---|---|---|---|
| lookup | 19 | 1.00 | 0.95 | 1.00 | 0.00 | 0.59× | Overkill |
| aggregation | 21 | 0.19 | 1.00 | 1.00 | 0.81 | 0.29× | Worth it |
| superlative | 10 | 0.00 | 1.00 | 1.00 | 1.00 | 0.58× | Worth it |
| temporal | 22 | 1.00 | 0.68 | 1.00 | 0.00 | 1.12× | Overkill |
| multi_hop | 28 | 0.57 | 0.07 | 0.68 | 0.11 | 1.29× | Marginal |

Agentic right where RAG was wrong: **35** (pub-001, pub-003, pub-004, pub-008, pub-011, pub-010, pub-021, pub-020, pub-022, pub-024, pub-027, pub-028, pub-033, pub-037, pub-044, pub-045, pub-053, pub-058, pub-065, pub-066, pub-064, pub-067, pub-070, pub-076, pub-078, pub-082, pub-084, pub-085, pub-087, pub-088, pub-089, pub-092, pub-095, pub-096, pub-069)  
RAG right where Agentic was wrong: **5** (pub-015, pub-060, pub-073, pub-077, pub-083)

## Necessity routing

| Route | Questions | Median agentic tokens | Agentic EM |
|---|---|---|---|
| direct | 64 | 1,977 | 1.00 |
| loop | 36 | 8,658 | 0.75 |

*Estimate:* answering the 64 direct-route questions through the loop at the loop's median cost would have spent about **350,595** more tokens.

## Agents and tools

| Agent | Invocations | Tokens | Tokens / call | Time / call |
|---|---|---|---|---|
| orchestrator | 100 | 281,054 | 2,811 | 83,760 ms |
| entity_linking | 100 | 0 | 0 | 2 ms |
| answer_generation | 100 | 212,801 | 2,128 | 48,316 ms |
| answer_verification | 100 | 0 | 0 | 1 ms |
| evidence_evaluation | 68 | 52,970 | 779 | 34,298 ms |
| graph_traversal | 62 | 0 | 0 | 188 ms |
| multi_hop_reasoning | 32 | 0 | 0 | 1,008 ms |
| aggregation | 31 | 0 | 0 | 149 ms |
| document_retrieval | 18 | 0 | 0 | 1,472 ms |
| similarity_search | 9 | 0 | 0 | 890 ms |

Tools called: `intent_parser` ×100, `entity_linker` ×100, `generate` ×100, `answer_resolver` ×100, `evidence_evaluator` ×68, `Q1` ×40, `Q4(HELD_AT)→Q1` ×26, `Q4` ×22, `Q2` ×21, `HAS_CHUNK` ×18, `Q3` ×10, `Q5` ×9, `Q1→Q4→Q1` ×6

Answer verification: 90 of 100 answers supported by the graph evidence, 5 resolved to a page title, 0 with conflicting evidence flagged  
Stop reasons: `direct_route` ×64, `sufficient_evidence` ×25, `no_further_action_available` ×11
  
Strategy changed on **24** of 100 questions; median 5 trace steps.

