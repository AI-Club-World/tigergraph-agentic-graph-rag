import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { config } from './config'
import { getBatchRecords } from './services/batchService'
import { listRuns } from './services/benchmarkService'
import type { BatchRecord } from './types'

/**
 * Loads one batch run. The run id comes from `?run=` so a dashboard or eval
 * table view is linkable. Without one, a live backend opens its newest run
 * (GET /runs is newest first) — live run ids are timestamps, so the fixture
 * default 'latest' never exists there.
 */
export function useBatchRecords() {
  const [params, setParams] = useSearchParams()
  const explicitRun = params.get('run')
  const resolveNewest = !explicitRun && !config.useMockApi && !import.meta.env.VITE_DEFAULT_RUN_ID
  const runId = explicitRun ?? config.defaultRunId
  const [records, setRecords] = useState<BatchRecord[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setRecords(null)
    setError(null)

    if (resolveNewest) {
      listRuns()
        .then((runs) => {
          if (cancelled) return
          if (runs.length) setParams({ run: runs[0].run_id }, { replace: true })
          else setError('No benchmark runs yet — start one from the Benchmarks view.')
        })
        .catch((e: unknown) => {
          if (!cancelled) setError(e instanceof Error ? e.message : 'Could not list runs')
        })
      return () => {
        cancelled = true
      }
    }

    getBatchRecords(runId)
      .then((loaded) => {
        if (!cancelled) setRecords(loaded)
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Could not load records')
      })

    return () => {
      cancelled = true
    }
  }, [runId, resolveNewest, setParams])

  const setRunId = (next: string) => setParams(next ? { run: next } : {})

  return { runId, setRunId, records, error, loading: !records && !error }
}
