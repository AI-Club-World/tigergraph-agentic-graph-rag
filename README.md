# tigergraph-agentic-graph-rag

## P1 Baseline (Honest Unfiltered RAG)

The P1 baseline pipeline implements standard, unfiltered Retrieval-Augmented Generation (RAG) over the entire document corpus. By architectural decision (AD-9), P1 receives **no type filtering, no candidate sets, no relevance thresholds, and no re-ranking**. Because the corpus contains 26.7% non-Olympic documents (including films, officeholder biographies, and tennis tournaments), unfiltered dense retrieval exposes the fundamental ceiling of standard text vector search on complex multi-hop, aggregation, and domain-specific questions. P1's ceiling is deliberately visible rather than masked; masking or type-filtering this baseline would quietly rig the three-way comparison against GraphRAG (P2) and Agentic GraphRAG (P3).

## Where the LLM is, and is not

**No LLM sits in the scoring path.** Exact match and token F1 are computed
deterministically against the verified gold answers (SQuAD-style normalization),
so the reported numbers are reproducible run-to-run for identical inputs
(NFR-6, AD-4). Verified gold answers already exist; a reference-free LLM judge
is the tool for the *absence* of ground truth, not a weaker substitute when
labels are present.

The Agentic pipeline (P3) does make **one** LLM call inside its evidence
evaluator, a groundedness check that asks whether the retrieved evidence can
answer the question (DP-4). That is a **retrieval decision** — it determines
whether the agent keeps investigating — and it never contributes to a score.
The evaluator's first stage, the scope-coverage gate, is fully deterministic.
Stating this plainly because the Evidence Evaluator is described elsewhere as
"deterministic" while performing a groundedness check, which reads as a
contradiction until the two roles are separated.

Every model call in P3 is routed through one accounting module and attributed
to a numbered trace step, and the sum of per-step tokens is reconciled against
the record total. Where a provider reports no usage, the model's own tokenizer
is used and the figure is labelled `local_tokenizer`; where the model exposes
no tokenizer either, the figure is labelled `estimated` rather than being
presented as a count.