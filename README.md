# tigergraph-agentic-graph-rag

## P1 Baseline (Honest Unfiltered RAG)

The P1 baseline pipeline implements standard, unfiltered Retrieval-Augmented Generation (RAG) over the entire document corpus. By architectural decision (AD-9), P1 receives **no type filtering, no candidate sets, no relevance thresholds, and no re-ranking**. Because the corpus contains 26.7% non-Olympic documents (including films, officeholder biographies, and tennis tournaments), unfiltered dense retrieval exposes the fundamental ceiling of standard text vector search on complex multi-hop, aggregation, and domain-specific questions. P1's ceiling is deliberately visible rather than masked; masking or type-filtering this baseline would quietly rig the three-way comparison against GraphRAG (P2) and Agentic GraphRAG (P3).