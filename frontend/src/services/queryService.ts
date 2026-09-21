import { config } from '../config'
import { get, openSse, post } from './http'
import { PIPELINE_ORDER, replay, scenarioFor, delay } from './mock/transport'
import type { PipelineRecord, QueryAccepted, QueryLevelRecord, TraceStep } from '../types'

export interface QueryStreamHandlers {
  /** One agentic trace step (TECHNICAL-SPEC §6.3). */
  onTrace: (step: TraceStep) => void
  /** One pipeline finished; its column can render without waiting for the others. */
  onPipeline: (record: PipelineRecord) => void
  /** All three pipelines settled; the full record is now fetchable. */
  onDone: () => void
  onError: (message: string) => void
}

/** POST /query -> 202 {query_id, stream_token} (TECHNICAL-SPEC §4.1, §5). */
export async function submitQuery(query: string): Promise<QueryAccepted> {
  if (!config.useMockApi) return post<QueryAccepted>('/query', { query })

  await delay(120)
  const scenario = scenarioFor(query)
  const queryId = `mock-${Date.now()}`
  mockPending.set(queryId, { ...scenario, query_id: queryId, query_text: query })
  return { query_id: queryId, stream_token: `mock-token-${queryId}` }
}

/** GET /query/{id}/stream?token=… (SSE). Returns a cancel function. */
export function openQueryStream(
  accepted: QueryAccepted,
  handlers: QueryStreamHandlers,
): () => void {
  if (!config.useMockApi) {
    return openSse(
      `/query/${accepted.query_id}/stream`,
      accepted.stream_token,
      {
        trace: (data) => handlers.onTrace(data as TraceStep),
        pipeline: (data) => handlers.onPipeline(data as PipelineRecord),
        done: () => handlers.onDone(),
        error: (data) => handlers.onError(String((data as { detail?: string }).detail ?? 'Pipeline error')),
      },
      handlers.onError,
    )
  }
  return mockQueryStream(accepted, handlers)
}

/** GET /query/{id}/result (TECHNICAL-SPEC §4.2). */
export async function getQueryResult(queryId: string): Promise<QueryLevelRecord> {
  if (!config.useMockApi) return get<QueryLevelRecord>(`/query/${queryId}/result`)

  await delay(80)
  const record = mockPending.get(queryId)
  if (!record) throw new Error(`Unknown query_id ${queryId}`)
  return record
}

// ── Mock transport ───────────────────────────────────────────────────────────

const mockPending = new Map<string, QueryLevelRecord>()

type MockEvent =
  | { at: number; kind: 'trace'; step: TraceStep }
  | { at: number; kind: 'pipeline'; record: PipelineRecord }

function mockQueryStream(accepted: QueryAccepted, handlers: QueryStreamHandlers): () => void {
  const record = mockPending.get(accepted.query_id)
  if (!record) {
    handlers.onError(`Unknown query_id ${accepted.query_id}`)
    return () => undefined
  }

  const events: MockEvent[] = []

  // Trace steps arrive as the agentic run accumulates them, so the panel fills
  // while the other two columns are still running (AD-2).
  const agentic = record.pipelines.agentic_graphrag
  let elapsed = 0
  for (const step of agentic.trace ?? []) {
    elapsed += step.latency_ms
    events.push({ at: elapsed, kind: 'trace', step })
  }

  for (const pipeline of PIPELINE_ORDER) {
    events.push({
      at: record.pipelines[pipeline].latency_ms,
      kind: 'pipeline',
      record: record.pipelines[pipeline],
    })
  }

  return replay(
    events,
    (e) => e.at,
    (e) => (e.kind === 'trace' ? handlers.onTrace(e.step) : handlers.onPipeline(e.record)),
    handlers.onDone,
  )
}
