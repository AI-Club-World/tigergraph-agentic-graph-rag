import { config } from '../config'
import { get } from './http'
import { delay, mockRun } from './mock/transport'
import type { BatchRecord } from '../types'

/** GET /batch/{run_id}/records (TECHNICAL-SPEC §4.4). */
export async function getBatchRecords(runId: string): Promise<BatchRecord[]> {
  if (!config.useMockApi) return get<BatchRecord[]>(`/batch/${runId}/records`)

  await delay(220)
  const records = mockRun(runId)
  if (!records) throw new Error(`No mock fixture for run "${runId}" (try "latest" or "hidden")`)
  return records
}
