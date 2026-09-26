/**
 * useServiceStatus — polls /health/status periodically and on API failure.
 *
 * Single endpoint, both services checked in one round-trip.
 * Polling interval: configurable via VITE_POLL_INTERVAL_MS (default 10 min).
 * Additionally, any component can call `triggerRecheck()` to force an
 * immediate check — used by the HTTP layer when a backend call fails.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { config } from './config'

export type ServiceState = 'unknown' | 'ok' | 'error' | 'skip'

export interface ServiceStatus {
  db: ServiceState
  llm: ServiceState
  emb: ServiceState
  dbDetail: string
  llmDetail: string
  embDetail: string
  dbLatencyMs: number | null
  llmLatencyMs: number | null
  checking: boolean
  lastChecked: Date | null
  recheck: () => void
}

interface ServiceResult {
  status: string
  detail?: string
  latency_ms?: number
}
interface StatusResponse {
  db: ServiceResult
  llm: ServiceResult
  embedding?: ServiceResult
}

function toState(s: string): ServiceState {
  return s === 'ok' ? 'ok' : s === 'skip' ? 'skip' : 'error'
}

async function fetchStatus(): Promise<StatusResponse> {
  const res = await fetch(`${config.apiBaseUrl}/health/status`, {
    // The LLM probe is one real completion (no retries server-side); a cold
    // large model can take >15 s, which would mark both services offline.
    signal: AbortSignal.timeout(30_000),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return (await res.json()) as StatusResponse
}

// Module-level callback set by useServiceStatus so http.ts can trigger it
// without importing React hooks. Cleared when the component unmounts.
let _globalRecheck: (() => void) | null = null

/** Called by the HTTP layer when any backend request fails. */
export function triggerRecheckOnFailure(): void {
  _globalRecheck?.()
}

export function useServiceStatus(): ServiceStatus {
  const [db, setDb] = useState<ServiceState>('unknown')
  const [llm, setLlm] = useState<ServiceState>('unknown')
  const [emb, setEmb] = useState<ServiceState>('unknown')
  const [dbDetail, setDbDetail] = useState('')
  const [llmDetail, setLlmDetail] = useState('')
  const [embDetail, setEmbDetail] = useState('')
  const [dbLatencyMs, setDbLatencyMs] = useState<number | null>(null)
  const [llmLatencyMs, setLlmLatencyMs] = useState<number | null>(null)
  const [checking, setChecking] = useState(false)
  const [lastChecked, setLastChecked] = useState<Date | null>(null)

  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      _globalRecheck = null
    }
  }, [])

  const doCheck = useCallback(async () => {
    if (!mounted.current) return
    setChecking(true)
    try {
      const result = await fetchStatus()
      if (!mounted.current) return
      setDb(toState(result.db.status))
      setDbDetail(result.db.detail ?? '')
      setDbLatencyMs(result.db.latency_ms ?? null)
      setLlm(toState(result.llm.status))
      setLlmDetail(result.llm.detail ?? '')
      setLlmLatencyMs(result.llm.latency_ms ?? null)
      setEmb(result.embedding ? toState(result.embedding.status) : 'unknown')
      setEmbDetail(result.embedding?.detail ?? '')
      setLastChecked(new Date())
    } catch (err) {
      if (!mounted.current) return
      const msg = err instanceof Error ? err.message : 'Unreachable'
      setDb('error')
      setDbDetail(msg)
      setLlm('error')
      setLlmDetail(msg)
      setEmb('error')
      setEmbDetail(msg)
      setLastChecked(new Date())
    } finally {
      if (mounted.current) setChecking(false)
    }
  }, [])

  // Register for global poll-on-failure trigger
  useEffect(() => {
    _globalRecheck = () => { void doCheck() }
    return () => { _globalRecheck = null }
  }, [doCheck])

  // Initial check + interval; skip entirely in mock mode
  useEffect(() => {
    if (config.useMockApi) return
    void doCheck()
    const interval = setInterval(() => { void doCheck() }, config.pollIntervalMs)
    return () => clearInterval(interval)
  }, [doCheck])

  return {
    db,
    llm,
    emb,
    dbDetail,
    llmDetail,
    embDetail,
    dbLatencyMs,
    llmLatencyMs,
    checking,
    lastChecked,
    recheck: doCheck,
  }
}
