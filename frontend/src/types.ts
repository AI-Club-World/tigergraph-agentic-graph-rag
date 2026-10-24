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

export type Round1QType = 'lookup' | 'multi_hop' | 'temporal' | 'aggregation' | 'superlative'
/** Round-2 harness subsets (config-docs/ROUND2-DESIGN.md §8). */
export type Round2QType = 'evolving' | 'conflicting' | 'uncertain'
export type QType = Round1QType | Round2QType

export const ROUND1_QTYPES: readonly QType[] = [
  'lookup',
  'multi_hop',
  'temporal',
  'aggregation',
  'superlative',
]

export const QTYPES: readonly QType[] = [...ROUND1_QTYPES, 'evolving', 'conflicting', 'uncertain']

/** The Round-1 types always, a Round-2 type only when some row has it. */
export function qtypesShown(rows: readonly { qtype?: string | null }[]): QType[] {
  return QTYPES.filter((q) => ROUND1_QTYPES.includes(q) || rows.some((r) => r.qtype === q))
}

export type PipelineStatus = 'running' | 'done' | 'error'

export type AgentType =
  | 'orchestrator'
  | 'entity_linking'
  | 'graph_traversal'
  | 'similarity_search'
  | 'document_retrieval'
  | 'aggregation'
  | 'multi_hop_reasoning'
  | 'evidence_evaluation'
  | 'answer_generation'
  | 'answer_verification'
  | 'conflict_resolution'

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
  /** The cited evidence text (truncated); what the grounding score checks against. */
  snippet?: string | null
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
  /** Round 2: structured working of the step (a conflict resolution's candidates). */
  details?: Record<string, unknown> | null
}

/** Round 2: the time scope a question puts on the fact it asks for. */
export interface TemporalScope {
  mode: 'none' | 'as_of' | 'before' | 'after' | 'between' | 'latest' | 'original'
  t1: string | null
  t2: string | null
  cue: string
  ambiguous: boolean
}

export interface ResolvedValue {
  value: string
  score: number
  probability: number
  support: number
  sources: string[]
  observed_at: string[]
  doc_ids: string[]
}

/** Round 2: the values the agent weighed for one attribute; losers stay as cited evidence. */
export interface ConflictResolution {
  subject: string
  predicate: string
  chosen: ResolvedValue | null
  alternatives: ResolvedValue[]
  superseded: { value: string; source: string; observed_at: string | null; doc_id: string }[]
  confidence: number
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
  /** With stop_reason "disambiguation_required": the venues or events to choose between. */
  candidates?: string[] | null
  /** Round 2 (agentic only): calibrated confidence computed from the weighed claims. */
  confidence?: number | null
  temporal_scope?: TemporalScope | null
  conflicts?: ConflictResolution[] | null
}

export interface Verdict {
  /** null when undefined: a pipeline errored, or the baseline spent no tokens. */
  token_multiplier_vs_rag: number | null
  token_multiplier_vs_graphrag: number | null
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
  /** Share of the answer's names found in its cited evidence (0 when nothing cited). */
  grounded?: number
}

export interface BatchRecord {
  run_id: string
  qid: string
  question: string
  qtype: QType | null // Question.qtype is optional backend-side
  /** Gold variants, scored max-over-variants. Empty for the hidden set. */
  ground_truth: string[]
  gold_doc_ids: string[]
  record: QueryLevelRecord
  scores: Record<PipelineId, PipelineScores> | null
  /** Grounding per pipeline, computed for every run (needs no ground truth). */
  grounding?: Partial<Record<PipelineId, number>>
}

export interface BuildEvent {
  stage: string
  pipeline_affected: PipelineId[]
  status: 'running' | 'done' | 'error' | 'ready'
  items_done: number
  items_total: number
  elapsed_ms: number
  /** Always 0 — ingestion is deterministic parsing plus an embedding model, never an LLM (DP-7). */
  tokens: number
  note: string
}

export interface QueryAccepted {
  query_id: string
}

export interface BuildAccepted {
  build_id: string
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
