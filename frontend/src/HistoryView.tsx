import { Notice } from './components/Notice'
import { Fragment, useEffect, useMemo, useState } from 'react'
import { ms, num, titleCase } from './format'
import { getHistory, type Trial, type TrialKind } from './services/historyService'

const OK_STATUSES = new Set(['done', 'ready', 'complete'])

function statusTone(status: string): string {
  if (OK_STATUSES.has(status)) return 'badge-done'
  if (status === 'partial' || status === 'needs_confirmation') return 'badge-running'
  return 'badge-error'
}

/** Every query, build and benchmark attempt — including failed, refused and
 *  "asked to confirm" ones — with dataset, model, duration and error. */
export function HistoryView() {
  const [trials, setTrials] = useState<Trial[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [kind, setKind] = useState<TrialKind | 'all'>('all')
  const [status, setStatus] = useState('all')
  const [search, setSearch] = useState('')
  const [open, setOpen] = useState<string | null>(null)

  function load() {
    setError(null)
    getHistory()
      .then(setTrials)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Could not load history'))
  }
  useEffect(load, [])

  const statuses = useMemo(() => [...new Set((trials ?? []).map((t) => t.status))].sort(), [trials])
  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return (trials ?? []).filter(
      (t) =>
        (kind === 'all' || t.kind === kind) &&
        (status === 'all' || t.status === status) &&
        (!needle ||
          [t.subject, t.llm_model, t.llm_provider, t.dataset, t.error]
            .some((v) => typeof v === 'string' && v.toLowerCase().includes(needle))),
    )
  }, [trials, kind, status, search])

  return (
    <div className="view history-view">
      <header className="view-head">
        <div>
          <h2>History</h2>
          <p className="muted">
            Every query, build and benchmark attempt, newest first — successful, failed, refused or
            waiting on a rebuild decision.
          </p>
        </div>
        <button type="button" className="secondary" onClick={load}>Refresh</button>
      </header>

      <div className="history-filters">
        <label>
          Type{' '}
          <select value={kind} onChange={(e) => setKind(e.target.value as TrialKind | 'all')}>
            <option value="all">All</option>
            <option value="query">Query</option>
            <option value="build">Build</option>
            <option value="benchmark">Benchmark</option>
            <option value="embedding_job">Embedding job</option>
          </select>
        </label>
        <label>
          Status{' '}
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="all">All</option>
            {statuses.map((s) => (
              <option key={s} value={s}>{titleCase(s)}</option>
            ))}
          </select>
        </label>
        <input
          type="search"
          aria-label="Search history"
          placeholder="Search query, dataset, model, error…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <span className="muted small">{trials ? `${visible.length} of ${trials.length}` : ''}</span>
      </div>

      {error && <Notice onClose={() => setError(null)}>{error}</Notice>}
      {!trials && !error && <p className="muted">Loading…</p>}
      {trials && trials.length === 0 && <p className="muted">No attempts recorded yet.</p>}

      {visible.length > 0 && (
        <table className="history-table">
          <thead>
            <tr>
              <th scope="col">When</th>
              <th scope="col">Type</th>
              <th scope="col">Status</th>
              <th scope="col">Query / dataset</th>
              <th scope="col">Model</th>
              <th scope="col">Duration</th>
              <th scope="col">Tokens</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((t) => (
              <Fragment key={t.id}>
                <tr
                  onClick={() => setOpen(open === t.id ? null : t.id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      setOpen(open === t.id ? null : t.id)
                    }
                  }}
                  tabIndex={0}
                  aria-expanded={open === t.id}
                  className="history-row"
                >
                  <td>{new Date(t.at).toLocaleString()}</td>
                  <td>{titleCase(t.kind)}</td>
                  <td>
                    <span className={`badge ${statusTone(t.status)}`}>{titleCase(t.status)}</span>
                  </td>
                  <td className="text">
                    {t.subject ?? '—'}
                    {t.error && <span className="error-text small block">{t.error}</span>}
                  </td>
                  <td>{t.llm_model ? `${t.llm_provider ?? ''}/${t.llm_model}` : '—'}</td>
                  <td>{typeof t.duration_ms === 'number' ? ms(t.duration_ms) : '—'}</td>
                  <td>{typeof t.tokens === 'number' ? num(t.tokens) : '—'}</td>
                </tr>
                {open === t.id && (
                  <tr className="history-detail">
                    <td colSpan={7}>
                      <pre>{JSON.stringify(t, null, 2)}</pre>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
