import { Notice } from './components/Notice'
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
  return records.flatMap((r) => {
    const value = r.scores?.[pipeline]?.[key]
    return typeof value === 'number' ? [value] : []
  })
}

/** A pipeline's record on one question, or undefined (an imported run may lack one). */
function recordOf(r: BatchRecord, pipeline: PipelineId) {
  return r.record.pipelines[pipeline]
}

/** The agentic record's trace; empty when absent. */
function agenticTrace(r: BatchRecord) {
  return recordOf(r, 'agentic_graphrag')?.trace ?? []
}

export function Dashboard() {
  const { runId, setRunId, records, error, clearError, loading } = useBatchRecords()

  const scored = useMemo(() => (records ?? []).filter((r) => r.scores !== null), [records])

  const headline = useMemo(() => {
    return PIPELINE_IDS.map((pipeline) => ({
      pipeline,
      em: mean(scoresBy(scored, pipeline, 'em')),
      f1: mean(scoresBy(scored, pipeline, 'f1')),
      completeness: mean(scoresBy(scored, pipeline, 'completeness')),
      medianTokens: median(scored.flatMap((r) => {
        const pr = recordOf(r, pipeline)
        return pr && pr.status !== 'error' ? [pr.tokens.total] : []
      })),
    }))
  }, [scored])

  // Cost, latency and reliability per pipeline over every question — shown
  // whether or not the run has ground truth (the hidden set has none).
  // Errored answers are counted, not averaged in as zero-token answers.
  const costs = useMemo(() => {
    return PIPELINE_IDS.map((pipeline) => {
      const all = (records ?? []).flatMap((r) => (recordOf(r, pipeline) ? [recordOf(r, pipeline)!] : []))
      const answered = all.filter((pr) => pr.status !== 'error')
      return {
        pipeline,
        n: all.length,
        errors: all.length - answered.length,
        medianTokens: median(answered.map((pr) => pr.tokens.total)),
        meanInput: mean(answered.map((pr) => pr.tokens.input)),
        meanOutput: mean(answered.map((pr) => pr.tokens.output)),
        meanLatency: mean(answered.map((pr) => pr.latency_ms)),
        meanCitations: mean(answered.map((pr) => pr.citations_count)),
        grounded: (() => {
          const values = (records ?? []).flatMap((r) => {
            const pr = recordOf(r, pipeline)
            const g = r.grounding?.[pipeline]
            return pr && pr.status !== 'error' && typeof g === 'number' ? [g] : []
          })
          return values.length ? mean(values) : null
        })(),
      }
    })
  }, [records])

  // What the agent did: invocations, tokens and time per agent type.
  const agentUsage = useMemo(() => {
    const byAgent = new Map<string, { calls: number; tokens: number; latency: number }>()
    for (const r of records ?? []) {
      for (const step of agenticTrace(r)) {
        const row = byAgent.get(step.agent_type) ?? { calls: 0, tokens: 0, latency: 0 }
        row.calls += 1
        row.tokens += step.tokens.input + step.tokens.output
        row.latency += step.latency_ms
        byAgent.set(step.agent_type, row)
      }
    }
    return [...byAgent.entries()].sort((a, b) => b[1].calls - a[1].calls)
  }, [records])

  const perQtype = useMemo(() => {
    return QTYPES.map((qtype) => {
      const rows = scored.filter((r) => r.qtype === qtype)
      const emGap =
        mean(scoresBy(rows, 'agentic_graphrag', 'em')) - mean(scoresBy(rows, 'rag', 'em'))
      // Mean of per-question ratios; a question with zero RAG tokens has no
      // defined ratio and is left out rather than folding Infinity/NaN in.
      const multiplier = mean(
        rows.flatMap((r) => {
          const ragTokens = recordOf(r, 'rag')?.tokens.total ?? 0
          const agenticTokens = recordOf(r, 'agentic_graphrag')?.tokens.total
          return ragTokens && agenticTokens !== undefined ? [agenticTokens / ragTokens] : []
        }),
      )
      return { qtype, n: rows.length, rows, emGap, multiplier }
    })
  }, [scored])

  const scatter: ScatterSeries[] = useMemo(
    () =>
      PIPELINE_IDS.map((pipeline) => ({
        name: PIPELINE_LABELS[pipeline],
        color: PIPELINE_COLORS[pipeline],
        points: scored.flatMap((r) => {
          const pr = recordOf(r, pipeline)
          const sc = r.scores?.[pipeline]
          return pr && sc ? [{ x: pr.tokens.total, y: sc.f1, label: `${r.qid} (${r.qtype})` }] : []
        }),
      })),
    [scored],
  )

  const stepCounts = useMemo(() => {
    const counts = new Map<number, number>()
    for (const r of records ?? []) {
      const n = agenticTrace(r).length
      counts.set(n, (counts.get(n) ?? 0) + 1)
    }
    return [...counts.entries()]
      .sort((a, b) => a[0] - b[0])
      .map(([steps, count]) => ({ label: `${steps} steps`, value: count }))
  }, [records])

  const stopReasons = useMemo(() => {
    const counts = new Map<string, number>()
    for (const r of records ?? []) {
      const reason = recordOf(r, 'agentic_graphrag')?.stop_reason ?? 'none'
      counts.set(reason, (counts.get(reason) ?? 0) + 1)
    }
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([reason, count]) => ({ label: reason, value: count }))
  }, [records])

  const strategyChanges = useMemo(() => {
    const runs = records ?? []
    const changed = runs.filter((r) => recordOf(r, 'agentic_graphrag')?.strategy_changed).length
    const steps = runs.reduce((sum, r) => sum + agenticTrace(r).filter((s) => s.strategy_change).length, 0)
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

      {loading && <p className="muted pad">Loading run "{runId}"…</p>}
      {error && <Notice onClose={clearError}>{error}</Notice>}

      {records && !scored.length && (
        <p className="note pad">
          Run "{runId}" carries no ground truth, so no accuracy metrics can be shown. Token, latency
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
                    <th title="Alias of retrieval recall against the gold documents">Completeness</th>
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
                      <td>{dec(row.completeness)}</td>
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
                  {perQtype.map((row) => row.n === 0 ? (
                    <tr key={row.qtype}>
                      <th scope="row">{titleCase(row.qtype)}</th>
                      <td>0</td>
                      <td className="muted" colSpan={3}>No questions of this type in the run</td>
                    </tr>
                  ) : (
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

          <section className="panel">
            <h3>Cost, latency and reliability</h3>
            <table className="matrix">
              <thead>
                <tr>
                  <th>Pipeline</th>
                  <th>Answered</th>
                  <th>Errors</th>
                  <th>Median tokens</th>
                  <th>Mean input</th>
                  <th>Mean output</th>
                  <th>Mean latency</th>
                  <th>Mean citations</th>
                  <th title="Share of the answer's names found in the evidence it cites">Grounded</th>
                </tr>
              </thead>
              <tbody>
                {costs.map((row) => (
                  <tr key={row.pipeline}>
                    <th scope="row">
                      <i className="swatch" style={{ background: PIPELINE_COLORS[row.pipeline] }} />
                      {PIPELINE_LABELS[row.pipeline]}
                    </th>
                    <td>{num(row.n - row.errors)}</td>
                    <td className={row.errors ? 'loss' : undefined}>{num(row.errors)}</td>
                    <td>{num(Math.round(row.medianTokens))}</td>
                    <td>{num(Math.round(row.meanInput))}</td>
                    <td>{num(Math.round(row.meanOutput))}</td>
                    <td>{`${(row.meanLatency / 1000).toFixed(1)} s`}</td>
                    <td>{dec(row.meanCitations)}</td>
                    <td>{row.grounded === null ? '—' : dec(row.grounded)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted small">
              Over answered questions; errored answers are counted, not averaged in. Grounded checks the answer
              against the text of its own citations — it needs no ground truth.
            </p>
          </section>

          {agentUsage.length > 0 && (
            <section className="panel">
              <h3>Agentic trace: agents invoked</h3>
              <table className="matrix">
                <thead>
                  <tr>
                    <th>Agent</th>
                    <th>Invocations</th>
                    <th>Tokens</th>
                    <th>Tokens / call</th>
                    <th>Time / call</th>
                  </tr>
                </thead>
                <tbody>
                  {agentUsage.map(([agent, row]) => (
                    <tr key={agent}>
                      <th scope="row">{titleCase(agent)}</th>
                      <td>{num(row.calls)}</td>
                      <td>{num(row.tokens)}</td>
                      <td>{num(Math.round(row.tokens / row.calls))}</td>
                      <td>{`${Math.round(row.latency / row.calls)} ms`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
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
