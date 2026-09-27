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
/** Same params with `run` set (or removed) — keeps the Dashboard page's ?tab=. */
function withRun(params: URLSearchParams, run: string): URLSearchParams {
  const next = new URLSearchParams(params)
  if (run) next.set('run', run)
  else next.delete('run')
  return next
}

export function useBatchRecords() {
  const [params, setParams] = useSearchParams()
  const explicitRun = params.get('run')
  // 'latest' is the fixtures' name for the newest run; live, it means "open
  // the newest run" too (live run ids are timestamps, never 'latest').
  const defaultIsNewest = !import.meta.env.VITE_DEFAULT_RUN_ID || import.meta.env.VITE_DEFAULT_RUN_ID === 'latest'
  const resolveNewest = !explicitRun && !config.useMockApi && defaultIsNewest
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
          if (runs.length) setParams((prev) => withRun(prev, runs[0].run_id), { replace: true })
          else setError('No benchmark runs yet — start one from the Run benchmark tab.')
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

  const setRunId = (next: string) => setParams((prev) => withRun(prev, next))

  // Dismissing an error leaves an empty view rather than a stuck "loading".
  const clearError = () => {
    setError(null)
    setRecords([])
  }

  return { runId, setRunId, records, error, clearError, loading: !records && !error }
}
