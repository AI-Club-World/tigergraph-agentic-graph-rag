import { config } from '../../config'
import type { BatchRecord, BuildEvent, PipelineId, QueryLevelRecord } from '../../types'
import queryResults from '../../fixtures/queryResults.json'
import buildEvents from '../../fixtures/buildEvents.json'
import latestRecords from '../../fixtures/batchRecords.latest.json'
import hiddenRecords from '../../fixtures/batchRecords.hidden.json'

const SCENARIOS = queryResults as unknown as Record<string, QueryLevelRecord>
const BUILD_EVENTS = buildEvents as unknown as BuildEvent[]
const RUNS: Record<string, BatchRecord[]> = {
  latest: latestRecords as unknown as BatchRecord[],
  hidden: hiddenRecords as unknown as BatchRecord[],
}

/** Keyword routing from a free-text query to a fixture scenario. */
const MATCHERS: Array<[string, RegExp]> = [
  ['aggregation', /\bhow many\b|\bcount\b|\bnumber of\b|\btotal\b/i],
  ['superlative', /\bmost\b|\bfewest\b|\blargest\b|\bhighest\b|\bbiggest\b/i],
  ['multi_hop', /\bbefore\b|\bafter\b|\bpreceding\b|\bimmediately\b|\bfollowed\b/i],
  ['lookup', /\bwho\b|\bwhich nation\b|\bgold\b|\bsilver\b|\bbronze\b/i],
]

export function scenarioFor(query: string): QueryLevelRecord {
  // Superlative and multi_hop share the aggregation/lookup wording, so the more
  // specific patterns are tested first and the first hit wins.
  const ordered = ['multi_hop', 'superlative', 'aggregation', 'lookup']
  for (const id of ordered) {
    const matcher = MATCHERS.find(([mid]) => mid === id)
    if (matcher && matcher[1].test(query) && SCENARIOS[id]) return SCENARIOS[id]
  }
  return SCENARIOS.default
}

export function mockBuildEvents(): BuildEvent[] {
  return BUILD_EVENTS
}

export function mockRun(runId: string): BatchRecord[] | undefined {
  return RUNS[runId]
}

/** Imported or mock-executed runs join the fixture runs for this session. */
export function registerMockRun(runId: string, records: BatchRecord[]): void {
  RUNS[runId] = records
}

const scaled = (ms: number) => Math.max(0, ms * config.mockLatencyScale)

/**
 * Replays timed items against a wall clock, returning a cancel function.
 * `at` is the item's offset from the start of the replay in unscaled ms.
 */
export function replay<T>(
  items: T[],
  at: (item: T) => number,
  emit: (item: T) => void,
  onComplete: () => void,
): () => void {
  const timers: ReturnType<typeof setTimeout>[] = []
  let last = 0

  for (const item of items) {
    const delay = scaled(at(item))
    last = Math.max(last, delay)
    timers.push(setTimeout(() => emit(item), delay))
  }
  timers.push(setTimeout(onComplete, last + scaled(120)))

  return () => timers.forEach(clearTimeout)
}

export function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, scaled(ms)))
}

export const PIPELINE_ORDER: readonly PipelineId[] = ['rag', 'graphrag', 'agentic_graphrag']
