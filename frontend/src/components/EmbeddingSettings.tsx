/**
 * Embedding model switching (config-docs/EMBEDDING-SWITCHING.md): the five
 * models with their state for the corpus, the re-embed job, and the informed
 * decision dialog. Every refusal shown here is also enforced by the server.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useDialogFocus } from './useDialogFocus'
import {
  completeEmbedding,
  fetchEmbeddingPlan,
  fetchEmbeddings,
  resumeEmbeddingJob,
  switchEmbedding,
  type EmbeddingJob,
  type EmbeddingModelStatus,
  type EmbeddingOverview,
  type EmbeddingPlan,
  type SwitchMode,
} from '../services/settingsService'
import { num } from '../format'

const POLL_MS = 3000

function stateLabel(m: EmbeddingModelStatus): string {
  switch (m.state) {
    case 'complete':
      return 'Complete'
    case 'incomplete':
      return `Incomplete · ${num(m.chunks_done)}/${num(m.chunks_total)} chunks`
    case 'building':
      return `Building · ${num(m.chunks_done)}/${num(m.chunks_total)}`
    case 'failed':
      return 'Failed · resumable'
    case 'evicting':
      return 'Being removed'
    case 'indexing':
      return 'Indexing · Complete to finish'
    default:
      return 'Not stored'
  }
}

function jobLine(job: EmbeddingJob, labels: Record<string, string>): string {
  const model = labels[job.model] ?? job.model
  if (job.status === 'complete') return `${model}: embedding complete (${num(job.chunks_total)} chunks).`
  const phase = {
    queued: 'starting',
    deleting: `removing ${job.delete.map((k) => labels[k] ?? k).join(', ')}`,
    embedding: `batch ${job.batches_done}/${job.batches_total} · ${num(job.chunks_done)}/${num(job.chunks_total)} chunks`,
    indexing: 'waiting for the vector index',
    done: 'done',
  }[job.phase]
  if (job.status === 'failed') {
    const error = (job.error ?? 'unknown error').slice(0, 160)
    return `${model}: failed while ${phase} — ${error}. Resume continues from the last finished batch.`
  }
  return `${model}: re-embedding — ${phase}.`
}

export function EmbeddingSettings() {
  const [overview, setOverview] = useState<EmbeddingOverview | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [plan, setPlan] = useState<EmbeddingPlan | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    try {
      setOverview(await fetchEmbeddings())
      setLoadError(null)
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : 'Could not load embedding state')
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  // Follow a running job or build until it ends (the switch re-enables then).
  const live = overview?.job?.status === 'running' || overview?.build_running
  useEffect(() => {
    if (!live) return
    const timer = setInterval(() => void refresh(), POLL_MS)
    return () => clearInterval(timer)
  }, [live, refresh])

  if (loadError && !overview) return <p className="muted small">{loadError}</p>
  if (!overview) return <p className="muted small">Loading embedding models…</p>

  const labels = Object.fromEntries(overview.models.map((m) => [m.key, m.label]))
  const disabledReason = overview.switch_disabled_reason
  const job = overview.job

  async function choose(key: string) {
    setActionError(null)
    try {
      setPlan(await fetchEmbeddingPlan(key))
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Could not plan the switch')
    }
  }

  async function act(run: () => Promise<unknown>) {
    setBusy(true)
    setActionError(null)
    try {
      await run()
      setPlan(null)
      await refresh()
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Request failed')
      // The refusal often means the state moved on (a build or job started).
      void refresh()
    } finally {
      setBusy(false)
    }
  }

  return (
    <fieldset className="settings-fieldset" disabled={Boolean(disabledReason) || busy}>
      <legend className="label">Knowledge Base · Embedding Model</legend>
      {disabledReason && (
        <p className="embed-disabled" role="status">
          Switching is disabled: {disabledReason}
          {overview.build_running
            ? ' It re-enables when the build ends.'
            : overview.job?.status === 'running'
              ? ' It re-enables when the job ends.'
              : ' It re-enables when the run ends.'}
        </p>
      )}
      {!overview.layout_current && (
        <p className="muted small" role="note">
          The graph uses the old one-vector-per-chunk layout. Run a build with a reset to store embeddings per model.
        </p>
      )}
      <p className="muted small settings-embed-note">
        {overview.stored.length}/{overview.cap} models stored for {num(overview.chunks_total)} chunks. A query only
        ever searches its own model's embeddings.
      </p>
      <div className="settings-embed-grid" role="radiogroup" aria-label="Embedding model">
        {overview.models.map((m) => (
          <label key={m.key} className={`settings-embed-card ${m.key === overview.active ? 'selected' : ''}`}>
            <input
              type="radio"
              name="embedding_model"
              value={m.key}
              checked={m.key === overview.active}
              onChange={() => void choose(m.key)}
            />
            <span className="settings-embed-label">
              {m.label}
              <span className={`embed-state embed-state-${m.state}`}>
                {m.key === overview.active ? 'Active · ' : ''}{stateLabel(m)}
              </span>
            </span>
            <span className="settings-embed-dim muted small">{m.dim}d</span>
            {(m.state === 'incomplete' || m.state === 'indexing') && m.key !== job?.model && (
              <button
                type="button"
                className="secondary embed-complete-btn"
                onClick={(e) => { e.preventDefault(); void act(() => completeEmbedding(m.key)) }}
              >
                Complete
              </button>
            )}
          </label>
        ))}
      </div>
      {job && job.status !== 'complete' && (
        <div className={`embed-job embed-job-${job.status}`} role="status">
          <span>{jobLine(job, labels)}</span>
          {job.status === 'failed' && (
            <button type="button" className="secondary" onClick={() => void act(resumeEmbeddingJob)}>
              Resume
            </button>
          )}
        </div>
      )}
      {actionError && !plan && <p className="error-text small" role="alert">{actionError}</p>}
      {plan && (
        <EmbeddingSwitchDialog
          plan={plan}
          labels={labels}
          busy={busy}
          error={actionError}
          onCancel={() => { setPlan(null); setActionError(null) }}
          onConfirm={(mode, evict) => void act(() => switchEmbedding(plan.target.key, mode, evict))}
        />
      )}
    </fieldset>
  )
}

interface DialogProps {
  plan: EmbeddingPlan
  labels: Record<string, string>
  busy: boolean
  error?: string | null
  onCancel: () => void
  onConfirm: (mode?: SwitchMode, evict?: string) => void
}

/** The informed decision: two options with pros/cons from the real state,
 *  nothing preselected, eviction mandatory at the cap. */
export function EmbeddingSwitchDialog({ plan, labels, busy, error, onCancel, onConfirm }: DialogProps) {
  const [mode, setMode] = useState<SwitchMode | null>(null)
  const [evict, setEvict] = useState<string | null>(null)
  const ref = useRef<HTMLDivElement>(null)
  useDialogFocus(ref, true, onCancel)
  const target = plan.target
  const name = (k: string | null) => (k ? labels[k] ?? k : '')
  const storedList = plan.stored.map((k) => `${name(k)}${k === plan.active ? ' (active)' : ''}`).join(', ') || 'none'
  const option = mode ? plan[mode] : null
  const needsEviction = Boolean(option?.needs_eviction)
  const canConfirm = !busy && (plan.instant || (mode !== null && (!needsEviction || evict !== null)))
  const chunks = num(plan.chunks_total)

  return (
    <div className="embed-dialog-backdrop" role="presentation">
      <div className="embed-dialog" role="dialog" aria-modal="true" aria-labelledby="embed-dialog-title" ref={ref}>
        <h3 id="embed-dialog-title">Switch embeddings to {target.label}</h3>
        <p className="embed-cap" data-testid="cap-status">
          {plan.stored.length}/{plan.cap} models currently stored: {storedList}.
          {' '}{target.label} is {target.dim}-dim, {stateLabel(target).toLowerCase()}.
        </p>

        {plan.instant ? (
          <p>{target.label} already has complete embeddings for all {chunks} chunks — the switch is instant.</p>
        ) : (
          <div className="embed-options" role="radiogroup" aria-label="How to switch">
            <label className={`embed-option ${mode === 'replace' ? 'selected' : ''}`}>
              <input type="radio" name="switch-mode" checked={mode === 'replace'} onChange={() => { setMode('replace'); setEvict(null) }} />
              <span>
                <strong>Force full re-embed</strong>
                <ul>
                  <li className="pro">
                    No extra storage:{' '}
                    {plan.replace.deletes
                      ? `${name(plan.replace.deletes)}'s embeddings are deleted before re-embedding.`
                      : 'nothing to delete; only one index is built.'}
                  </li>
                  {plan.replace.keeps.length > 0 && (
                    <li className="pro">{plan.replace.keeps.map(name).join(', ')} stays stored and queryable.</li>
                  )}
                  <li className="con">
                    Blocking: queries with {target.label} wait until all {chunks} chunks are embedded.
                  </li>
                  {plan.replace.deletes && (
                    <li className="con">
                      No quick fallback: returning to {name(plan.replace.deletes)} means re-embedding it again.
                    </li>
                  )}
                </ul>
              </span>
            </label>
            <label className={`embed-option ${mode === 'parallel' ? 'selected' : ''}`}>
              <input type="radio" name="switch-mode" checked={mode === 'parallel'} onChange={() => { setMode('parallel'); setEvict(null) }} />
              <span>
                <strong>Keep parallel indices</strong>
                <ul>
                  <li className="pro">
                    {name(plan.active)} stays queryable while {target.label} builds; switching back later is instant.
                  </li>
                  <li className="con">
                    Extra TigerGraph storage and index-build time: one more {target.dim}-dim HNSW index over {chunks}{' '}
                    chunks.
                  </li>
                  <li className="con">
                    Capped at {plan.cap} models:{' '}
                    {plan.parallel.needs_eviction
                      ? `${plan.stored.length}/${plan.cap} stored — adding ${target.label} requires evicting one.`
                      : `${plan.parallel.stored_after}/${plan.cap} stored afterwards.`}
                  </li>
                </ul>
              </span>
            </label>
          </div>
        )}

        {needsEviction && option && (
          <fieldset className="embed-evict">
            <legend>Evict one model first (required)</legend>
            <p className="muted small">
              Deletes only that model's embeddings, index and HAS_EMBEDDING edges — never the chunks or the other
              model's data. This runs before {target.label} is embedded.
            </p>
            {option.evictable.map((k) => (
              <label key={k}>
                <input type="radio" name="evict" checked={evict === k} onChange={() => setEvict(k)} />
                {' '}{name(k)}{k === plan.active ? ' (active — queries then wait for the new model)' : ''}
              </label>
            ))}
          </fieldset>
        )}

        {error && <p className="error-text small" role="alert">{error}</p>}
        <div className="confirm-actions">
          <button type="button" className="secondary" onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className="btn-primary"
            disabled={!canConfirm}
            onClick={() => onConfirm(plan.instant ? undefined : mode ?? undefined, evict ?? undefined)}
          >
            {plan.instant ? 'Switch' : mode === 'replace' ? 'Re-embed' : mode === 'parallel' ? 'Build alongside' : 'Choose an option'}
          </button>
        </div>
      </div>
    </div>
  )
}
