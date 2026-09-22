import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { config } from './config'
import { getBatchRecords } from './services/batchService'
import type { BatchRecord } from './types'

/**
 * Loads one batch run. The run id comes from `?run=` so a dashboard or eval
 * table view is linkable; there is no list-runs endpoint in the API surface.
 */
export function useBatchRecords() {
  const [params, setParams] = useSearchParams()
  const runId = params.get('run') ?? config.defaultRunId
  const [records, setRecords] = useState<BatchRecord[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setRecords(null)
    setError(null)

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
  }, [runId])

  const setRunId = (next: string) => setParams(next ? { run: next } : {})

  return { runId, setRunId, records, error, loading: !records && !error }
}
