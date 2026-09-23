import { mean, median } from '../../format'
import { PIPELINE_IDS, type BatchRecord, type PipelineSummary, type RunConfigValue, type RunSummary } from '../../types'
import { mockRun, registerMockRun } from './transport'

// Mock stand-in for the backend's history.summarize_run. It only aggregates
// fixture scores, which the backend scorer produced; it never scores.

type RunConfig = Record<string, RunConfigValue>

const BASE_CONFIG: RunConfig = {
  llm_provider: 'openai_compatible',
  llm_model: 'qwen2.5:7b-instruct',
  temperature: 0,
  embedding_model: 'all-MiniLM-L6-v2',
  k: 10,
  chunk_tokens: 300,
  chunk_overlap: 50,
  max_steps: 6,
  max_tokens_per_query: 20000,
}

const CONFIGS: Record<string, RunConfig> = {
  latest: { ...BASE_CONFIG, dataset: 'eval_public', started_at: '2026-09-21T11:00:00Z' },
  hidden: { ...BASE_CONFIG, dataset: 'eval_hidden', started_at: '2026-09-21T14:30:00Z' },
}

export const MOCK_DATASETS = ['eval_public', 'eval_hidden']

const orNull = (xs: number[]) => (xs.length ? mean(xs) : null)

function summarize(runId: string, runConfig: RunConfig, records: BatchRecord[]): RunSummary {
  const pipelines: RunSummary['pipelines'] = {}
  for (const id of PIPELINE_IDS) {
    const runs = records.map((r) => r.record.pipelines[id]).filter(Boolean)
    if (!runs.length) continue
    const scores = records.flatMap((r) => (r.scores?.[id] ? [r.scores[id]] : []))
    const tokens = runs.map((p) => p.tokens.total)
    const f1 = orNull(scores.map((s) => s.f1))
    const meanTokens = mean(tokens)
    const summary: PipelineSummary = {
      em: orNull(scores.map((s) => s.em)),
      f1,
      precision: orNull(scores.map((s) => s.precision)),
      recall: orNull(scores.map((s) => s.recall)),
      mean_tokens: meanTokens,
      median_tokens: median(tokens),
      total_tokens: tokens.reduce((a, b) => a + b, 0),
      mean_latency_ms: mean(runs.map((p) => p.latency_ms)),
      errors: runs.filter((p) => p.status === 'error').length,
      f1_per_1k_tokens: f1 !== null && meanTokens ? f1 / (meanTokens / 1000) : null,
    }
    pipelines[id] = summary
  }
  const timestamps = records.map((r) => r.record.timestamp).filter(Boolean).sort()
  return {
    run_id: runId,
    status: 'complete',
    started_at: String(runConfig.started_at ?? timestamps[0] ?? new Date().toISOString()),
    dataset: (runConfig.dataset as string | undefined) ?? null,
    run_config: runConfig,
    n_questions: records.length,
    scored: records.some((r) => r.scores !== null),
    pipelines,
  }
}

export function mockRunSummaries(): RunSummary[] {
  return Object.entries(CONFIGS)
    .map(([id, cfg]) => summarize(id, cfg, mockRun(id) ?? []))
    .sort((a, b) => b.started_at.localeCompare(a.started_at))
}

export function mockRunConfig(runId: string): RunConfig {
  return CONFIGS[runId] ?? {}
}

export function addMockRun(runId: string, runConfig: RunConfig, records: BatchRecord[]): RunSummary {
  if (CONFIGS[runId]) throw new Error(`Run '${runId}' already exists`)
  const stored = records.map((r) => ({ ...r, run_id: runId }))
  CONFIGS[runId] = runConfig
  registerMockRun(runId, stored)
  return summarize(runId, runConfig, stored)
}
