/**
 * ServiceStatus — header indicators for Knowledge Base (TigerGraph) and
 * Intelligent Engine (LLM) availability.
 *
 * Shows two icon badges with color-coded dot indicators. Full names appear
 * on hover via title/aria-label. A "⟳" button triggers an immediate recheck.
 * RequiresServices wraps features that need a live service and shows a clear
 * blocked state + mailto link when unavailable.
 */

import { createContext, useContext, type ReactNode } from 'react'
import { Icon, type IconName } from './components/Icon'
import { config } from './config'
import { type ServiceState, type ServiceStatus, useServiceStatus } from './useServiceStatus'

// ── Context ─────────────────────────────────────────────────────────────────

const ServiceContext = createContext<ServiceStatus | null>(null)

export function ServiceStatusProvider({ children }: { children: ReactNode }) {
  const status = useServiceStatus()
  return <ServiceContext.Provider value={status}>{children}</ServiceContext.Provider>
}

export function useServiceContext(): ServiceStatus {
  const ctx = useContext(ServiceContext)
  if (!ctx) throw new Error('useServiceContext used outside ServiceStatusProvider')
  return ctx
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const SERVICE_META = {
  db: { label: 'Knowledge Base (TigerGraph)', icon: 'hub' },
  llm: { label: 'Intelligent Engine (LLM)', icon: 'bot' },
  emb: { label: 'Embedding Model', icon: 'layers' },
} as const satisfies Record<string, { label: string; icon: IconName }>

type ServiceKey = keyof typeof SERVICE_META

function stateLabel(s: ServiceState): string {
  return s === 'ok' ? 'Online' : s === 'skip' ? 'Degraded / skipped' : s === 'unknown' ? 'Checking…' : 'Offline'
}

function stateClass(s: ServiceState): string {
  return s === 'ok' ? 'svc-ok' : s === 'skip' ? 'svc-skip' : s === 'unknown' ? 'svc-unknown' : 'svc-error'
}

function buildMailto(downServices: string[]): string {
  const subject = encodeURIComponent(`[OGR] Service unavailable: ${downServices.join(', ')}`)
  const body = encodeURIComponent(
    `Hi Admin,\n\nThe following service(s) appear to be unavailable in the Agentic GraphRAG app:\n\n` +
      downServices.map((s) => `  - ${s}`).join('\n') +
      `\n\nPlease investigate.\n\nTimestamp: ${new Date().toISOString()}\n`,
  )
  return `mailto:${config.adminEmail}?subject=${subject}&body=${body}`
}

// ── Pill indicator ────────────────────────────────────────────────────────────

function Pill({
  serviceKey,
  state,
  detail,
}: {
  serviceKey: ServiceKey
  state: ServiceState
  detail: string
}) {
  const { label, icon } = SERVICE_META[serviceKey]
  const tooltip = `${label}: ${stateLabel(state)}${detail ? `\n${detail}` : ''}`

  return (
    <span
      className={`svc-pill ${stateClass(state)}`}
      title={tooltip}
      aria-label={tooltip}
      role="status"
    >
      <span className="svc-dot" aria-hidden="true" />
      <span className="svc-icon" aria-hidden="true"><Icon name={icon} size={15} /></span>
    </span>
  )
}

// ── Status bar (header) ───────────────────────────────────────────────────────

export function ServiceStatusBar() {
  const { db, llm, emb, dbDetail, llmDetail, embDetail, checking, lastChecked, recheck } = useServiceContext()

  return (
    <div className="svc-bar" aria-label="Service availability">
      <Pill serviceKey="db" state={db} detail={dbDetail} />
      <Pill serviceKey="llm" state={llm} detail={llmDetail} />
      <Pill serviceKey="emb" state={emb} detail={embDetail} />
      <button
        type="button"
        className="svc-recheck"
        onClick={recheck}
        disabled={checking}
        aria-label="Re-check service availability now"
        title={lastChecked ? `Last checked: ${lastChecked.toLocaleTimeString()}` : 'Click to check now'}
      >
        {checking ? '↻' : '⟳'}
      </button>
    </div>
  )
}

// ── Blocked-feature overlay ───────────────────────────────────────────────────

interface BlockedProps {
  needs: ServiceKey[]
  children: ReactNode
}

export function RequiresServices({ needs, children }: BlockedProps) {
  const status = useContext(ServiceContext)

  // In mock mode there is no live service polling, and with no provider
  // mounted (a view rendered on its own) there is no status — never block.
  if (config.useMockApi || !status) return <>{children}</>

  const downNeeds = needs.filter((s) => status[s] === 'error')
  if (!downNeeds.length) return <>{children}</>

  const downLabels = downNeeds.map((s) => SERVICE_META[s].label)
  const mailto = buildMailto(downLabels)

  return (
    <div className="svc-blocked" role="status" aria-live="polite">
      <span className="svc-blocked-icon" aria-hidden="true">⚠</span>
      <div className="svc-blocked-body">
        <strong>Feature unavailable</strong>
        <p>
          {downLabels.join(' and ')} {downLabels.length === 1 ? 'is' : 'are'} currently offline.
          This feature requires {downLabels.length === 1 ? 'it' : 'them'} to operate.
        </p>
        <a href={mailto} className="svc-contact-link">
          Contact Admin
        </a>
      </div>
    </div>
  )
}
