// Data model — TECHNICAL-SPEC §6, with the DP-1 (Option A) amendments:
// data field names verbatim (qid/question/qtype), ground_truth as a list,
// citations carrying both source_id and chunk_id, and chunks_returned +
// citations_count on both PipelineRecord and TraceStep.

export type PipelineId = 'rag' | 'graphrag' | 'agentic_graphrag'

export const PIPELINE_IDS: readonly PipelineId[] = ['rag', 'graphrag', 'agentic_graphrag']

export const PIPELINE_LABELS: Record<PipelineId, string> = {
  rag: 'RAG',
  graphrag: 'GraphRAG',
  agentic_graphrag: 'Agentic GraphRAG',
}

export type QType = 'lookup' | 'multi_hop' | 'temporal' | 'aggregation' | 'superlative'

export const QTYPES: readonly QType[] = [
  'lookup',
  'multi_hop',
  'temporal',
  'aggregation',
  'superlative',
]

export type PipelineStatus = 'running' | 'done' | 'error'

export type AgentType =
  | 'entity_linking'
  | 'graph_traversal'
  | 'similarity_search'
  | 'document_retrieval'
  | 'aggregation'
  | 'multi_hop_reasoning'
  | 'evidence_evaluation'

export interface TokenUsage {
  input: number
  output: number
  total: number
}

export interface Citation {
  /** Parent doc_id = wikidata QID. This is the field scored against gold_doc_ids. */
  source_id: string
  /** Displayed only, never scored. */
  chunk_id: string | null
  ref_type: 'chunk' | 'entity' | 'relationship'
}

export interface TraceStep {
  step_n: number
  agent_type: AgentType
  tool_called: string
  tokens: { input: number; output: number }
  chunks_returned: number
  citations_count: number
  latency_ms: number
  strategy_change: boolean
  notes: string
}

export interface PipelineRecord {
  pipeline: PipelineId
  /** Shortest span answering the question — this is what EM/F1 score. */
  answer: string
  /** Prose with citations — displayed, never scored. */
  explanation: string
  citations: Citation[]
  chunks_returned: number
  citations_count: number
  tokens: TokenUsage
  token_source: 'provider' | 'local_tokenizer' | 'estimated'
  latency_ms: number
  trace: TraceStep[] | null
  strategy_changed: boolean | null
  stop_reason: string | null
  status: 'done' | 'error'
  error_detail: string | null
}

export interface Verdict {
  token_multiplier_vs_rag: number
  token_multiplier_vs_graphrag: number
  accuracy_delta_vs_rag: number | 'n/a'
  accuracy_delta_vs_graphrag: number | 'n/a'
  summary_line: string
}

export interface QueryLevelRecord {
  query_id: string
  query_text: string
  qtype: QType | null
  timestamp: string
  pipelines: Record<PipelineId, PipelineRecord>
  verdict: Verdict
}

/**
 * Per-pipeline scores produced by the backend scorer (TECHNICAL-SPEC §9).
 * Completeness is an explicit alias of Recall (DP-2 Option A).
 */
export interface PipelineScores {
  em: number
  f1: number
  precision: number
  recall: number
  completeness: number
}

export interface BatchRecord {
  run_id: string
  qid: string
  question: string
  qtype: QType
  /** Gold variants, scored max-over-variants. Empty for the hidden set. */
  ground_truth: string[]
  gold_doc_ids: string[]
  record: QueryLevelRecord
  scores: Record<PipelineId, PipelineScores> | null
}

export interface BuildEvent {
  stage: string
  pipeline_affected: PipelineId[]
  status: 'running' | 'done' | 'error' | 'ready'
  items_done: number
  items_total: number
  elapsed_ms: number
  /** Always 0 — ingestion is deterministic parsing plus a local encoder (DP-7). */
  tokens: number
  note: string
}

export interface QueryAccepted {
  query_id: string
  stream_token: string
}

export interface BuildAccepted {
  build_id: string
  stream_token: string
}

/** One pipeline's aggregate over a benchmark run (GET /runs). Accuracy is null without ground truth. */
export interface PipelineSummary {
  em: number | null
  f1: number | null
  precision: number | null
  recall: number | null
  mean_tokens: number | null
  median_tokens: number | null
  total_tokens: number
  mean_latency_ms: number | null
  errors: number
  f1_per_1k_tokens: number | null
}

export type RunConfigValue = string | number | boolean | null

/** One benchmark execution in the history (GET /runs). */
export interface RunSummary {
  run_id: string
  status: 'running' | 'complete' | 'failed'
  error?: string // why a failed run stopped, e.g. the selected LLM's rate limit
  started_at: string
  dataset: string | null
  run_config: Record<string, RunConfigValue>
  n_questions: number
  scored: boolean
  pipelines: Partial<Record<PipelineId, PipelineSummary>>
}

/** The JSON a run is exported as, and accepted back by POST /runs/import. */
export interface RunExport {
  run_id: string
  run_config: Record<string, RunConfigValue>
  records: BatchRecord[]
}
