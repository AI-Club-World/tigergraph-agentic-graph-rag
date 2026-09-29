# Run report: `r5-public`

- Questions: **100** (100 with ground truth)
- LLM (all three pipelines): `openai_compatible/nvidia/nemotron-3-super-120b-a12b`
- Embeddings: `bge-large-en-v1.5` via `embedding_host`
- Mode: `throughput`, pool 2, k=10, max steps 6
- Started: 2026-09-29T02:19:54.636178+00:00

## Headline

| Pipeline | EM | F1 | Completeness | Grounded | Median tokens | Mean in / out | Mean latency | Errors |
|---|---|---|---|---|---|---|---|---|
| RAG | 0.59 | 0.65 | 0.74 | 0.93 | 6,453 | 6,010 / 785 | 22.9 s | 0 |
| GraphRAG | 0.63 | 0.63 | 0.59 | 0.41 | 2,522 | 1,527 / 2,514 | 49.8 s | 0 |
| Agentic GraphRAG | 0.98 | 0.99 | 0.72 | 0.79 | 2,550 | 2,505 / 2,272 | 53.7 s | 0 |

## Where the agent pays for itself

Agentic − RAG accuracy gap and its token cost per question type (the mean of per-question Agentic ÷ RAG token ratios, as on the dashboard). Verdict: gap ≥ 0.5 worth it, ≤ 0.05 overkill, else marginal.

| Type | n | RAG EM | GraphRAG EM | Agentic EM | Agentic − RAG | Agentic ÷ RAG tokens | Verdict |
|---|---|---|---|---|---|---|---|
| lookup | 19 | 1.00 | 0.95 | 1.00 | 0.00 | 0.30× | Overkill |
| aggregation | 21 | 0.14 | 1.00 | 1.00 | 0.86 | 0.30× | Worth it |
| superlative | 10 | 0.00 | 0.90 | 0.90 | 0.90 | 0.94× | Worth it |
| temporal | 22 | 0.95 | 0.59 | 1.00 | 0.05 | 1.05× | Overkill |
| multi_hop | 28 | 0.57 | 0.07 | 0.96 | 0.39 | 1.02× | Marginal |

Agentic right where RAG was wrong: **39** (pub-001, pub-003, pub-004, pub-008, pub-010, pub-011, pub-019, pub-020, pub-022, pub-021, pub-024, pub-027, pub-028, pub-030, pub-033, pub-037, pub-038, pub-045, pub-044, pub-053, pub-058, pub-064, pub-065, pub-066, pub-069, pub-070, pub-072, pub-076, pub-078, pub-082, pub-084, pub-085, pub-087, pub-089, pub-092, pub-095, pub-096, pub-099, pub-098)  
RAG right where Agentic was wrong: **0** (—)

## Necessity routing

| Route | Questions | Median agentic tokens | Agentic EM |
|---|---|---|---|
| direct | 62 | 1,924 | 1.00 |
| loop | 38 | 7,416 | 0.95 |

*Estimate:* answering the 62 direct-route questions through the loop at the loop's median cost would have spent about **277,469** more tokens.

## Agents and tools

| Agent | Invocations | Tokens | Tokens / call | Time / call |
|---|---|---|---|---|
| orchestrator | 100 | 276,561 | 2,766 | 34,180 ms |
| entity_linking | 100 | 0 | 0 | 1 ms |
| answer_generation | 100 | 160,723 | 1,607 | 12,408 ms |
| answer_verification | 100 | 0 | 0 | 0 ms |
| graph_traversal | 61 | 0 | 0 | 68 ms |
| evidence_evaluation | 59 | 40,450 | 686 | 10,739 ms |
| multi_hop_reasoning | 33 | 0 | 0 | 588 ms |
| aggregation | 30 | 0 | 0 | 55 ms |
| document_retrieval | 14 | 0 | 0 | 518 ms |
| similarity_search | 10 | 0 | 0 | 752 ms |

Tools called: `intent_parser` ×100, `entity_linker` ×100, `generate` ×100, `answer_resolver` ×100, `evidence_evaluator` ×59, `Q1` ×42, `Q4(HELD_AT)→Q1` ×26, `Q2` ×21, `Q4` ×19, `HAS_CHUNK` ×14, `Q5` ×10, `Q3` ×9, `Q1→Q4→Q1` ×7

Answer verification: 90 of 100 answers supported by the graph evidence, 7 resolved to a page title, 11 with conflicting evidence flagged  
Stop reasons: `direct_route` ×62, `sufficient_evidence` ×35, `no_further_action_available` ×3
  
Strategy changed on **21** of 100 questions; median 5 trace steps.

