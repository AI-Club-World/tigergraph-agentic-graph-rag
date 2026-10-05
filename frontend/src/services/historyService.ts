import { config } from '../config'
import { get } from './http'

export type TrialKind = 'query' | 'build' | 'benchmark'

/** One attempt, as recorded by the backend (out/history.jsonl). */
export interface Trial {
  id: string
  at: string
  kind: TrialKind
  status: string
  subject?: string
  llm_provider?: string
  llm_model?: string
  embedding_model?: string
  duration_ms?: number
  tokens?: number
  error?: string | null
  dataset?: string
  failed_stage?: string
  [key: string]: unknown
}

/** GET /history — newest first. */
export async function getHistory(kind?: TrialKind): Promise<Trial[]> {
  if (config.useMockApi) return []
  return get<Trial[]>(`/history${kind ? `?kind=${kind}` : ''}`)
}
