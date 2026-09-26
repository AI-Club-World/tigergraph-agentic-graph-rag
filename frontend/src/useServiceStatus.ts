/**
 * useServiceStatus — polls /health/db, /health/llm and /health/embedding
 * periodically and on API failure. Each indicator has its own request and
 * time limit, so a slow LLM never holds up or fails the other two.
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
function toState(s: string): ServiceState {
  return s === 'ok' ? 'ok' : s === 'skip' ? 'skip' : 'error'
}

// Browser-side limits sit above the server's own (20 s, HEALTH_LLM_TIMEOUT_S
// default 120 s, 30 s) so the server reports the timeout, with detail.
const CHECKS = {
  db: { path: '/health/db', timeoutMs: 30_000 },
  llm: { path: '/health/llm', timeoutMs: config.llmHealthTimeoutMs },
  emb: { path: '/health/embedding', timeoutMs: 40_000 },
} as const
type CheckKey = keyof typeof CHECKS

async function fetchCheck(key: CheckKey): Promise<ServiceResult> {
  const { path, timeoutMs } = CHECKS[key]
  const res = await fetch(`${config.apiBaseUrl}${path}`, { signal: AbortSignal.timeout(timeoutMs) })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return (await res.json()) as ServiceResult
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
    const setters: Record<CheckKey, [(s: ServiceState) => void, (d: string) => void, ((ms: number | null) => void)?]> = {
      db: [setDb, setDbDetail, setDbLatencyMs],
      llm: [setLlm, setLlmDetail, setLlmLatencyMs],
      emb: [setEmb, setEmbDetail],
    }
    await Promise.all(
      (Object.keys(CHECKS) as CheckKey[]).map(async (key) => {
        const [setState, setDetail, setLatency] = setters[key]
        try {
          const result = await fetchCheck(key)
          if (!mounted.current) return
          setState(toState(result.status))
          setDetail(result.detail ?? '')
          setLatency?.(result.latency_ms ?? null)
        } catch (err) {
          if (!mounted.current) return
          setState('error')
          setDetail(err instanceof Error ? err.message : 'Unreachable')
        }
      }),
    )
    if (mounted.current) {
      setLastChecked(new Date())
      setChecking(false)
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
