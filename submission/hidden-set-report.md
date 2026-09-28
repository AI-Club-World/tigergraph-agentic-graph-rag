# Run report: `final-holdout`

- Questions: **50** (0 with ground truth)
- LLM (all three pipelines): `openai_compatible/nvidia/nemotron-3-super-120b-a12b`
- Embeddings: `bge-large-en-v1.5` via `embedding_host`
- Mode: `throughput`, pool 2, k=10, max steps 6
- Started: 2026-09-28T06:32:36.133523+00:00

## Headline

| Pipeline | EM | F1 | Completeness | Grounded | Median tokens | Mean in / out | Mean latency | Errors |
|---|---|---|---|---|---|---|---|---|
| RAG | — | — | — | 0.92 | 6,732 | 5,880 / 1,072 | 45.6 s | 0 |
| GraphRAG | — | — | — | 0.40 | 3,034 | 1,632 / 2,882 | 116.5 s | 0 |
| Agentic GraphRAG | — | — | — | 0.64 | 3,129 | 2,950 / 2,681 | 191.2 s | 0 |

## Necessity routing

| Route | Questions | Median agentic tokens | Agentic EM |
|---|---|---|---|
| direct | 36 | 2,094 | — |
| loop | 14 | 12,026 | — |

*Estimate:* answering the 36 direct-route questions through the loop at the loop's median cost would have spent about **310,430** more tokens.

## Agents and tools

| Agent | Invocations | Tokens | Tokens / call | Time / call |
|---|---|---|---|---|
| orchestrator | 50 | 152,801 | 3,056 | 79,636 ms |
| entity_linking | 50 | 0 | 0 | 0 ms |
| answer_generation | 50 | 106,346 | 2,127 | 77,848 ms |
| evidence_evaluation | 30 | 22,382 | 746 | 53,438 ms |
| graph_traversal | 28 | 0 | 0 | 75 ms |
| aggregation | 26 | 0 | 0 | 106 ms |
| multi_hop_reasoning | 15 | 0 | 0 | 636 ms |
| document_retrieval | 8 | 0 | 0 | 3,884 ms |
| similarity_search | 7 | 0 | 0 | 743 ms |

Tools called: `intent_parser` ×50, `entity_linker` ×50, `generate` ×50, `evidence_evaluator` ×30, `Q1` ×17, `Q2` ×16, `Q4` ×11, `Q3` ×10, `Q4(HELD_AT)→Q1` ×8, `HAS_CHUNK` ×8, `Q1→Q4→Q1` ×7, `Q5` ×7

Stop reasons: `direct_route` ×36, `sufficient_evidence` ×9, `no_further_action_available` ×5
  
Strategy changed on **13** of 50 questions; median 4 trace steps.

