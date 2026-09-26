import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react'
import { Link } from 'react-router-dom'
import { ScatterPlot, type ScatterSeries } from './components/Charts'
import { PIPELINE_COLORS } from './components/colors'
import { dec, ms, num, signed } from './format'
import {
  exportRun,
  importRun,
  listDatasets,
  listRuns,
  parseRunFile,
  startBenchmark,
} from './services/benchmarkService'
import { RequiresServices } from './ServiceStatus'
import { PIPELINE_IDS, PIPELINE_LABELS, type PipelineSummary, type RunSummary } from './types'

type Metric = {
  key: keyof PipelineSummary
  label: string
  better: 'high' | 'low'
  fmt: (n: number) => string
  delta: (d: number, base: number) => string
}

const score = (n: number) => dec(n)
const rel = (d: number, base: number) => (base ? `${signed((d / base) * 100, 0)}%` : signed(d, 0))

const METRICS: Metric[] = [
  { key: 'em', label: 'EM', better: 'high', fmt: score, delta: (d) => signed(d) },
  { key: 'f1', label: 'F1', better: 'high', fmt: score, delta: (d) => signed(d) },
  { key: 'precision', label: 'Precision', better: 'high', fmt: score, delta: (d) => signed(d) },
  { key: 'recall', label: 'Recall', better: 'high', fmt: score, delta: (d) => signed(d) },
  { key: 'median_tokens', label: 'Median tokens', better: 'low', fmt: (n) => num(Math.round(n)), delta: rel },
  { key: 'mean_latency_ms', label: 'Mean latency', better: 'low', fmt: ms, delta: rel },
  { key: 'f1_per_1k_tokens', label: 'F1 per 1k tokens', better: 'high', fmt: (n) => dec(n, 3), delta: (d) => signed(d, 3) },
  { key: 'errors', label: 'Errors', better: 'low', fmt: (n) => String(n), delta: (d) => signed(d, 0) },
]

const CONFIG_KEYS: Array<[string, string]> = [
  ['llm_provider', 'Provider'],
  ['llm_model', 'Model'],
  ['embedding_model', 'Embeddings'],
  ['dataset', 'Dataset'],
  ['k', 'k'],
  ['chunk_tokens', 'Chunk tokens'],
  ['max_steps', 'Max steps'],
  ['max_tokens_per_query', 'Token budget'],
  ['temperature', 'Temperature'],
  ['seed', 'Seed'],
  // Latency is only comparable across 'timing' runs (pool 1); 'throughput'
  // runs are for accuracy and tokens.
  ['latency_mode', 'Latency mode'],
  ['pool_size', 'Pool size'],
]

const value = (run: RunSummary, pipeline: (typeof PIPELINE_IDS)[number], key: keyof PipelineSummary) =>
  run.pipelines[pipeline]?.[key] ?? null

const when = (iso: string) => new Date(iso).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' })

function download(name: string, data: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

export function BenchmarksView() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null)
  const [datasets, setDatasets] = useState<string[]>([])
  const [dataset, setDataset] = useState('')
  const [busy, setBusy] = useState(false)
  const [filter, setFilter] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const fileRef = useRef<HTMLInputElement>(null)

  const refresh = useCallback(() => {
    listRuns()
      .then((loaded) => {
        setRuns(loaded)
        setError(null)
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Could not load the benchmark history'))
  }, [])

  useEffect(() => {
    refresh()
    listDatasets()
      .then((names) => {
        setDatasets(names)
        setDataset((current) => current || names[0] || '')
      })
      .catch(() => setDatasets([]))
  }, [refresh])

  // Executing runs grow as questions complete; poll until none is running.
  const anyRunning = runs?.some((r) => r.status === 'running') ?? false
  useEffect(() => {
    if (!anyRunning) return
    const timer = setInterval(refresh, 3000)
    return () => clearInterval(timer)
  }, [anyRunning, refresh])

  async function act(work: () => Promise<string>) {
    setBusy(true)
    setMessage(null)
    try {
      setMessage({ tone: 'ok', text: await work() })
      refresh()
    } catch (e) {
      setMessage({ tone: 'error', text: e instanceof Error ? e.message : 'Request failed' })
    } finally {
      setBusy(false)
    }
  }

  const run = () =>
    act(async () => {
      const started = await startBenchmark(dataset)
      return `Benchmark ${started.run_id} started on ${dataset}.`
    })

  function onFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    act(async () => {
      const imported = await importRun(parseRunFile(await file.text()))
      setSelected((s) => [...s, imported.run_id])
      return `Imported ${imported.run_id} (${imported.n_questions} questions).`
    })
  }

  const exportOne = (summary: RunSummary) =>
    act(async () => {
      download(`${summary.run_id}.json`, await exportRun(summary))
      return `Exported ${summary.run_id}.json`
    })

  const toggle = (id: string) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]))

  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase()
    if (!runs || !q) return runs ?? []
    return runs.filter((r) =>
      [r.run_id, r.dataset, r.run_config.llm_model, r.run_config.embedding_model, r.run_config.llm_provider]
        .some((v) => String(v ?? '').toLowerCase().includes(q)),
    )
  }, [runs, filter])

  const compared = useMemo(
    () => selected.flatMap((id) => runs?.filter((r) => r.run_id === id) ?? []),
    [runs, selected],
  )

  const tiles = useMemo(() => {
    const all = runs ?? []
    const best = (key: keyof PipelineSummary) =>
      all.reduce<{ run: RunSummary; v: number } | null>((top, r) => {
        const v = value(r, 'agentic_graphrag', key)
        return v !== null && (!top || v > top.v) ? { run: r, v } : top
      }, null)
    const tokens = all.reduce(
      (sum, r) => sum + Object.values(r.pipelines).reduce((s, p) => s + (p?.total_tokens ?? 0), 0),
      0,
    )
    return { f1: best('f1'), eff: best('f1_per_1k_tokens'), tokens }
  }, [runs])

  const scatter: ScatterSeries[] = useMemo(
    () =>
      PIPELINE_IDS.map((pipeline) => ({
        name: PIPELINE_LABELS[pipeline],
        color: PIPELINE_COLORS[pipeline],
        points: (compared.length ? compared : (runs ?? [])).flatMap((r) => {
          const x = value(r, pipeline, 'median_tokens')
          const y = value(r, pipeline, 'f1')
          return x !== null && y !== null ? [{ x, y, label: r.run_id }] : []
        }),
      })),
    [runs, compared],
  )

  return (
    <div className="view">
      <header className="view-head bench-head">
        <div>
          <h2>Benchmarks</h2>
          <p className="muted">
            Every benchmark execution is kept as history with its model, dataset and embedding
            metadata. Select two or more runs to compare them against the first one selected.
          </p>
        </div>
        <div className="bench-actions">
          <label htmlFor="bench-dataset" className="label">Dataset</label>
          <select id="bench-dataset" value={dataset} onChange={(e) => setDataset(e.target.value)} disabled={busy}>
            {datasets.map((d) => (
              <option key={d}>{d}</option>
            ))}
          </select>
          <RequiresServices needs={['db', 'llm', 'emb']}>
            <button type="button" onClick={run} disabled={busy || !dataset}>
              Run benchmark
            </button>
          </RequiresServices>
          <button type="button" className="secondary" onClick={() => fileRef.current?.click()} disabled={busy}>
            Import JSON
          </button>
          <input ref={fileRef} type="file" accept=".json,.jsonl,application/json" hidden onChange={onFile} aria-label="Import run file" />
        </div>
      </header>

      {message && (
        <p className={message.tone === 'ok' ? 'flash' : 'error-box pad'} role="status">
          {message.text}
        </p>
      )}
      {error && <p className="error-box pad">{error}</p>}
      {!runs && !error && <p className="muted pad">Loading benchmark history…</p>}

      {runs && (
        <>
          <div className="bench-tiles">
            <div className="metric">
              <span className="metric-value">{runs.length}</span>
              <span className="metric-label">runs in history</span>
            </div>
            <div className="metric">
              <span className="metric-value">{tiles.f1 ? dec(tiles.f1.v) : '—'}</span>
              <span className="metric-label">best agentic F1{tiles.f1 && ` · ${tiles.f1.run.run_id}`}</span>
            </div>
            <div className="metric">
              <span className="metric-value">{tiles.eff ? dec(tiles.eff.v, 3) : '—'}</span>
              <span className="metric-label">best agentic F1 / 1k tokens{tiles.eff && ` · ${tiles.eff.run.run_id}`}</span>
            </div>
            <div className="metric">
              <span className="metric-value">{num(tiles.tokens)}</span>
              <span className="metric-label">tokens spent, all runs</span>
            </div>
          </div>

          <section className="panel">
            <div className="panel-head">
              <h3>History</h3>
              <input
                type="text"
                placeholder="Filter by run, model, dataset, embeddings"
                aria-label="Filter runs"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              />
            </div>
            {!runs.length ? (
              <p className="muted">No benchmark runs yet. Run one, or import a past run's JSON.</p>
            ) : (
              <div className="matrix-scroll">
                <table className="matrix runs">
                  <thead>
                    <tr>
                      <th rowSpan={2} aria-label="Compare" />
                      <th rowSpan={2}>Run</th>
                      <th rowSpan={2}>Dataset</th>
                      <th rowSpan={2}>Model · embeddings</th>
                      <th rowSpan={2}>n</th>
                      <th colSpan={3}>F1</th>
                      <th colSpan={2}>Agentic GraphRAG</th>
                      <th rowSpan={2}>Explore</th>
                    </tr>
                    <tr>
                      {PIPELINE_IDS.map((p) => (
                        <th key={p} className="sub">
                          <i className="swatch" style={{ background: PIPELINE_COLORS[p] }} />
                          {PIPELINE_LABELS[p]}
                        </th>
                      ))}
                      <th className="sub">Median tokens</th>
                      <th className="sub">F1 / 1k tok</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visible.map((r) => {
                      const on = selected.includes(r.run_id)
                      const agentic = r.pipelines.agentic_graphrag
                      return (
                        <tr key={r.run_id} className={on ? 'selected' : undefined}>
                          <td className="center">
                            <input type="checkbox" checked={on} onChange={() => toggle(r.run_id)} aria-label={`Compare ${r.run_id}`} />
                          </td>
                          <th scope="row">
                            <code>{r.run_id}</code>
                            {r.status !== 'complete' && <span className={`badge badge-${r.status === 'running' ? 'running' : 'error'}`}>{r.status}</span>}
                            {r.error && <span className="error-box small block">{r.error}</span>}
                            <span className="muted small block">{when(r.started_at)}</span>
                          </th>
                          <td className="text">{r.dataset ?? '—'}</td>
                          <td className="text">
                            {String(r.run_config.llm_model ?? '—')}
                            <span className="muted small block">{String(r.run_config.embedding_model ?? '—')}</span>
                          </td>
                          <td>{r.n_questions}</td>
                          {PIPELINE_IDS.map((p) => {
                            const f1 = value(r, p, 'f1')
                            return <td key={p}>{f1 === null ? '—' : dec(f1)}</td>
                          })}
                          <td>{agentic?.median_tokens != null ? num(Math.round(agentic.median_tokens)) : '—'}</td>
                          <td>{agentic?.f1_per_1k_tokens != null ? dec(agentic.f1_per_1k_tokens, 3) : '—'}</td>
                          <td className="text nowrap">
                            <Link to={`/dashboard?run=${encodeURIComponent(r.run_id)}`}>Dashboard</Link>
                            {' · '}
                            <Link to={`/eval?run=${encodeURIComponent(r.run_id)}`}>Eval</Link>
                            {' · '}
                            <button type="button" className="link" onClick={() => exportOne(r)} disabled={busy}>
                              Export
                            </button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
                {!visible.length && <p className="muted">No runs match “{filter}”.</p>}
              </div>
            )}
          </section>

          {compared.length >= 2 && <Comparison runs={compared} onClear={() => setSelected([])} />}

          {scatter.some((s) => s.points.length) && (
            <section className="panel">
              <h3>Accuracy against cost, {compared.length ? 'selected runs' : 'every scored run'}</h3>
              <p className="muted small">One point per run and pipeline: median tokens per question on x, mean F1 on y.</p>
              <div className="bench-scatter">
                <ScatterPlot series={scatter} xLabel="median tokens" yLabel="F1" />
              </div>
            </section>
          )}
        </>
      )}
    </div>
  )
}

function Comparison({ runs, onClear }: { runs: RunSummary[]; onClear: () => void }) {
  const [baseline, ...others] = runs
  const pipelines = PIPELINE_IDS.filter((p) => runs.some((r) => r.pipelines[p]))

  function cell(run: RunSummary, pipeline: (typeof PIPELINE_IDS)[number], metric: Metric) {
    const v = value(run, pipeline, metric.key)
    if (v === null) return <td key={run.run_id}>—</td>
    // Compared at display precision, so a difference too small to show never reads as a win.
    const shown = runs.map((r) => value(r, pipeline, metric.key)).filter((x): x is number => x !== null).map(metric.fmt)
    const values = runs.map((r) => value(r, pipeline, metric.key)).filter((x): x is number => x !== null)
    const top = metric.fmt(metric.better === 'high' ? Math.max(...values) : Math.min(...values))
    const base = value(baseline, pipeline, metric.key)
    const d = run === baseline || base === null ? null : metric.fmt(v) === metric.fmt(base) ? 0 : v - base
    const tone = d === null || d === 0 ? 'flat' : (d > 0) === (metric.better === 'high') ? 'gain' : 'loss'
    return (
      <td key={run.run_id} className={metric.fmt(v) === top && shown.some((x) => x !== top) ? 'best' : undefined}>
        {metric.fmt(v)}
        {d !== null && <span className={`delta ${tone}`}>{metric.delta(d, base as number)}</span>}
      </td>
    )
  }

  return (
    <section className="panel">
      <div className="panel-head">
        <h3>Compare {runs.length} runs</h3>
        <span className="muted small">
          Deltas against <code>{baseline.run_id}</code> · best value per row highlighted
        </span>
        <button type="button" className="link" onClick={onClear}>Clear selection</button>
      </div>
      <div className="matrix-scroll">
        <table className="matrix compare">
          <thead>
            <tr>
              <th />
              {runs.map((r, i) => (
                <th key={r.run_id}>
                  <code>{r.run_id}</code>
                  <span className="muted small block">{i === 0 ? 'baseline' : when(r.started_at)}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr className="section-row">
              <th colSpan={runs.length + 1}>Configuration</th>
            </tr>
            {CONFIG_KEYS.map(([key, label]) => (
              <tr key={key}>
                <th scope="row">{label}</th>
                {runs.map((r) => {
                  const v = key === 'dataset' ? r.dataset : r.run_config[key]
                  const changed = others.includes(r) && String(v) !== String(key === 'dataset' ? baseline.dataset : baseline.run_config[key])
                  return (
                    <td key={r.run_id} className={`text${changed ? ' diff' : ''}`}>
                      {v === undefined || v === null ? '—' : String(v)}
                    </td>
                  )
                })}
              </tr>
            ))}
            <tr>
              <th scope="row">Questions</th>
              {runs.map((r) => (
                <td key={r.run_id}>{r.n_questions}</td>
              ))}
            </tr>
            {pipelines.map((p) => [
              <tr key={`${p}-head`} className="section-row">
                <th colSpan={runs.length + 1}>
                  <i className="swatch" style={{ background: PIPELINE_COLORS[p] }} />
                  {PIPELINE_LABELS[p]}
                </th>
              </tr>,
              ...METRICS.map((m) => (
                <tr key={`${p}-${m.key}`}>
                  <th scope="row">{m.label}</th>
                  {runs.map((r) => cell(r, p, m))}
                </tr>
              )),
            ])}
          </tbody>
        </table>
      </div>
    </section>
  )
}
