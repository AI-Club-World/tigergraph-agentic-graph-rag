import { useMemo } from 'react'
import { BarChart, ScatterPlot, type ScatterSeries } from './components/Charts'
import { PIPELINE_COLORS } from './components/colors'
import { RunPicker } from './components/RunPicker'
import { dec, mean, median, num, signed, titleCase } from './format'
import { useBatchRecords } from './useBatchRecords'
import {
  PIPELINE_IDS,
  PIPELINE_LABELS,
  QTYPES,
  type BatchRecord,
  type PipelineId,
  type PipelineScores,
} from './types'

const METRICS: Array<{ key: keyof PipelineScores; label: string; note?: string }> = [
  { key: 'em', label: 'EM' },
  { key: 'f1', label: 'F1' },
  { key: 'recall', label: 'Recall' },
  { key: 'precision', label: 'Precision' },
  { key: 'completeness', label: 'Completeness', note: 'alias of Recall' },
]

function scoresBy(records: BatchRecord[], pipeline: PipelineId, key: keyof PipelineScores) {
  return records.flatMap((r) => (r.scores ? [r.scores[pipeline][key]] : []))
}

export function Dashboard() {
  const { runId, setRunId, records, error, loading } = useBatchRecords()

  const scored = useMemo(() => (records ?? []).filter((r) => r.scores !== null), [records])

  const headline = useMemo(() => {
    return PIPELINE_IDS.map((pipeline) => ({
      pipeline,
      em: mean(scoresBy(scored, pipeline, 'em')),
      f1: mean(scoresBy(scored, pipeline, 'f1')),
      medianTokens: median(scored.map((r) => r.record.pipelines[pipeline].tokens.total)),
    }))
  }, [scored])

  const perQtype = useMemo(() => {
    return QTYPES.map((qtype) => {
      const rows = scored.filter((r) => r.qtype === qtype)
      const emGap =
        mean(scoresBy(rows, 'agentic_graphrag', 'em')) - mean(scoresBy(rows, 'rag', 'em'))
      const multiplier = mean(
        rows.map(
          (r) =>
            r.record.pipelines.agentic_graphrag.tokens.total / r.record.pipelines.rag.tokens.total,
        ),
      )
      return { qtype, n: rows.length, rows, emGap, multiplier }
    })
  }, [scored])

  const scatter: ScatterSeries[] = useMemo(
    () =>
      PIPELINE_IDS.map((pipeline) => ({
        name: PIPELINE_LABELS[pipeline],
        color: PIPELINE_COLORS[pipeline],
        points: scored.map((r) => ({
          x: r.record.pipelines[pipeline].tokens.total,
          y: r.scores![pipeline].f1,
          label: `${r.qid} (${r.qtype})`,
        })),
      })),
    [scored],
  )

  const stepCounts = useMemo(() => {
    const counts = new Map<number, number>()
    for (const r of records ?? []) {
      const n = r.record.pipelines.agentic_graphrag.trace?.length ?? 0
      counts.set(n, (counts.get(n) ?? 0) + 1)
    }
    return [...counts.entries()]
      .sort((a, b) => a[0] - b[0])
      .map(([steps, count]) => ({ label: `${steps} steps`, value: count }))
  }, [records])

  const stopReasons = useMemo(() => {
    const counts = new Map<string, number>()
    for (const r of records ?? []) {
      const reason = r.record.pipelines.agentic_graphrag.stop_reason ?? 'none'
      counts.set(reason, (counts.get(reason) ?? 0) + 1)
    }
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([reason, count]) => ({ label: reason, value: count }))
  }, [records])

  const strategyChanges = useMemo(() => {
    const runs = records ?? []
    const changed = runs.filter((r) => r.record.pipelines.agentic_graphrag.strategy_changed).length
    const steps = runs.reduce(
      (sum, r) =>
        sum + (r.record.pipelines.agentic_graphrag.trace ?? []).filter((s) => s.strategy_change).length,
      0,
    )
    return { runs: runs.length, changed, steps }
  }, [records])

  return (
    <div className="view dashboard">
      <header className="view-head">
        <div>
          <h2>Benchmark dashboard</h2>
          <p className="muted">
            Aggregate view over one batch run. Scores come from the backend scorer — no metric is
            recomputed in the browser.
          </p>
        </div>
        <RunPicker runId={runId} onChange={setRunId} />
      </header>

      {loading && <p className="muted pad">Loading run “{runId}”…</p>}
      {error && <p className="error-box pad">{error}</p>}

      {records && !scored.length && (
        <p className="note pad">
          Run “{runId}” carries no ground truth, so no accuracy metrics can be shown. Token, latency
          and trace aggregations below still apply.
        </p>
      )}

      {records && (
        <>
          {scored.length > 0 && (
            <section className="panel">
              <h3>Headline</h3>
              <table className="matrix">
                <thead>
                  <tr>
                    <th>Pipeline</th>
                    <th>EM</th>
                    <th>F1</th>
                    <th>Median tokens</th>
                  </tr>
                </thead>
                <tbody>
                  {headline.map((row) => (
                    <tr key={row.pipeline}>
                      <th scope="row">
                        <i className="swatch" style={{ background: PIPELINE_COLORS[row.pipeline] }} />
                        {PIPELINE_LABELS[row.pipeline]}
                      </th>
                      <td>{dec(row.em)}</td>
                      <td>{dec(row.f1)}</td>
                      <td>{num(Math.round(row.medianTokens))}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <h4>Is the agent worth it, per question type?</h4>
              <table className="matrix">
                <thead>
                  <tr>
                    <th>Question type</th>
                    <th>n</th>
                    <th>Agentic &minus; RAG EM</th>
                    <th>Agentic &divide; RAG tokens</th>
                    <th>Verdict</th>
                  </tr>
                </thead>
                <tbody>
                  {perQtype.map((row) => (
                    <tr key={row.qtype}>
                      <th scope="row">{titleCase(row.qtype)}</th>
                      <td>{row.n}</td>
                      <td className={row.emGap > 0 ? 'gain' : row.emGap < 0 ? 'loss' : 'flat'}>
                        {signed(row.emGap)}
                      </td>
                      <td>{dec(row.multiplier)}&times;</td>
                      <td>
                        {row.emGap >= 0.5
                          ? 'Worth it'
                          : row.emGap <= 0.05
                            ? 'Overkill'
                            : 'Marginal'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          {scored.length > 0 && (
            <section className="panel">
              <h3>Per-question-type matrix</h3>
              <div className="matrix-scroll">
                <table className="matrix">
                  <thead>
                    <tr>
                      <th>Metric</th>
                      {QTYPES.map((qtype) => (
                        <th key={qtype} colSpan={3}>
                          {titleCase(qtype)}
                        </th>
                      ))}
                    </tr>
                    <tr>
                      <th />
                      {QTYPES.flatMap((qtype) =>
                        PIPELINE_IDS.map((pipeline) => (
                          <th key={`${qtype}-${pipeline}`} className="sub">
                            <i className="swatch" style={{ background: PIPELINE_COLORS[pipeline] }} />
                            {pipeline === 'agentic_graphrag' ? 'AG' : pipeline === 'graphrag' ? 'GR' : 'RAG'}
                          </th>
                        )),
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {METRICS.map((metric) => (
                      <tr key={metric.key}>
                        <th scope="row" title={metric.note}>
                          {metric.label}
                          {metric.note && <sup>*</sup>}
                        </th>
                        {QTYPES.flatMap((qtype) => {
                          const rows = scored.filter((r) => r.qtype === qtype)
                          return PIPELINE_IDS.map((pipeline) => (
                            <td key={`${metric.key}-${qtype}-${pipeline}`}>
                              {rows.length ? dec(mean(scoresBy(rows, pipeline, metric.key))) : '—'}
                            </td>
                          ))
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="muted small">
                * Completeness is an explicit alias of Recall — |retrieved &cap; gold| / |gold| —
                kept because the guidebook names the column.
              </p>
            </section>
          )}

          {scored.length > 0 && (
            <section className="panel">
              <h3>Accuracy against tokens</h3>
              <ScatterPlot series={scatter} xLabel="tokens.total" yLabel="F1" />
            </section>
          )}

          <div className="panel-grid">
            <section className="panel">
              <h3>Agentic step-count distribution</h3>
              <BarChart data={stepCounts} color={PIPELINE_COLORS.agentic_graphrag} />
            </section>

            <section className="panel">
              <h3>Stop-reason breakdown</h3>
              <BarChart data={stopReasons} color={PIPELINE_COLORS.graphrag} />
            </section>

            <section className="panel">
              <h3>Strategy changes</h3>
              <div className="metrics">
                <div className="metric">
                  <span className="metric-value">{strategyChanges.changed}</span>
                  <span className="metric-label">runs that deviated</span>
                </div>
                <div className="metric">
                  <span className="metric-value">{strategyChanges.steps}</span>
                  <span className="metric-label">steps flagged</span>
                </div>
                <div className="metric">
                  <span className="metric-value">
                    {strategyChanges.runs
                      ? `${Math.round((strategyChanges.changed / strategyChanges.runs) * 100)}%`
                      : '—'}
                  </span>
                  <span className="metric-label">of {strategyChanges.runs} runs</span>
                </div>
              </div>
            </section>
          </div>
        </>
      )}
    </div>
  )
}
