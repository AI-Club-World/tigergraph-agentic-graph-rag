import { config } from '../config'
import { getBatchRecords } from './batchService'
import { get, post } from './http'
import { delay, mockRun } from './mock/transport'
import { addMockRun, MOCK_DATASETS, mockRunConfig, mockRunSummaries } from './mock/runs'
import type { BatchRecord, RunExport, RunSummary } from '../types'

/** GET /runs — the benchmark history, newest first. */
export async function listRuns(): Promise<RunSummary[]> {
  if (!config.useMockApi) return get<RunSummary[]>('/runs')
  await delay(180)
  return mockRunSummaries()
}

/** GET /datasets — question sets a benchmark can be executed over. */
export async function listDatasets(): Promise<string[]> {
  if (!config.useMockApi) return get<string[]>('/datasets')
  return MOCK_DATASETS
}

/** POST /batch — execute a benchmark; it joins the history as it runs. */
export async function startBenchmark(dataset: string): Promise<{ run_id: string; status: string }> {
  if (!config.useMockApi) return post('/batch', { dataset })

  // Mock: replay the matching fixture run under a fresh id.
  await delay(400)
  const runId = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d+/, '')
  const source = dataset === 'eval_hidden' ? 'hidden' : 'latest'
  addMockRun(runId, { ...mockRunConfig(source), dataset, started_at: new Date().toISOString() }, mockRun(source) ?? [])
  return { run_id: runId, status: 'complete' }
}

/** POST /runs/import — store a previously executed run. */
export async function importRun(payload: unknown): Promise<RunSummary> {
  if (!config.useMockApi) return post<RunSummary>('/runs/import', payload)

  await delay(120)
  const body: Partial<RunExport> = Array.isArray(payload) ? { records: payload } : (payload as Partial<RunExport>)
  const records = body?.records
  if (!Array.isArray(records) || !records.length || !records.every((r) => r && typeof r === 'object' && 'record' in r)) {
    throw new Error('Expected a list of records, each with a "record" object')
  }
  const runId = body.run_id ?? (records[0] as BatchRecord).run_id ?? `import-${Date.now()}`
  return addMockRun(runId, { ...(body.run_config ?? {}), imported_at: new Date().toISOString() }, records as BatchRecord[])
}

/** A run as re-importable JSON: config header plus every scored record. */
export async function exportRun(run: RunSummary): Promise<RunExport> {
  return { run_id: run.run_id, run_config: run.run_config, records: await getBatchRecords(run.run_id) }
}

/** Accepts an export (.json), a bare record list, or the backend's native JSONL run file. */
export function parseRunFile(text: string): unknown {
  try {
    return JSON.parse(text)
  } catch {
    const lines = text
      .split('\n')
      .filter((line) => line.trim())
      .map((line) => JSON.parse(line) as Record<string, unknown>)
    const [head, ...rest] = lines
    return head && 'run_config' in head ? { run_config: head.run_config, records: rest } : lines
  }
}
