import { Notice } from './components/Notice'
import { Fragment, useMemo, useState } from 'react'
import { PIPELINE_COLORS } from './components/colors'
import { RunPicker } from './components/RunPicker'
import { TracePanel } from './TracePanel'
import { dec, ms, num, titleCase } from './format'
import { useBatchRecords } from './useBatchRecords'
import {
  PIPELINE_IDS,
  PIPELINE_LABELS,
  QTYPES,
  type BatchRecord,
  type PipelineId,
  type QType,
} from './types'

/**
 * SQuAD-style normalization, used only to decide whether the three pipelines
 * disagree. Scoring itself stays in the backend scorer (one implementation).
 */
function normalize(text: string): string {
  return text
    .toLowerCase()
    .replace(/[‘’]/g, "'")
    .replace(/\b(a|an|the)\b/g, ' ')
    .replace(/[^\w\s']/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function disagree(record: BatchRecord): boolean {
  const answers = PIPELINE_IDS.map((p) => normalize(record.record.pipelines[p]?.answer ?? ''))
  return new Set(answers).size > 1
}

type SortKey = 'qid' | 'qtype' | 'gap' | 'tokens'

export function EvalTable() {
  const { runId, setRunId, records, error, clearError, loading } = useBatchRecords()
  const [qtypeFilter, setQtypeFilter] = useState<QType | 'all'>('all')
  const [pipelineFilter, setPipelineFilter] = useState<PipelineId | 'all'>('all')
  const [onlyDisagreeing, setOnlyDisagreeing] = useState(false)
  const [sortKey, setSortKey] = useState<SortKey>('qid')
  const [expanded, setExpanded] = useState<string | null>(null)

  const hasGold = useMemo(() => (records ?? []).some((r) => r.scores !== null), [records])
  const shownPipelines = pipelineFilter === 'all' ? PIPELINE_IDS : [pipelineFilter]

  const rows = useMemo(() => {
    let list = records ?? []
    if (qtypeFilter !== 'all') list = list.filter((r) => r.qtype === qtypeFilter)
    if (onlyDisagreeing) list = list.filter(disagree)

    const gap = (r: BatchRecord) =>
      r.scores ? (r.scores.agentic_graphrag?.em ?? 0) - (r.scores.rag?.em ?? 0) : 0

    return [...list].sort((a, b) => {
      if (sortKey === 'qid') return a.qid.localeCompare(b.qid)
      if (sortKey === 'qtype') return (a.qtype ?? '').localeCompare(b.qtype ?? '') || a.qid.localeCompare(b.qid)
      if (sortKey === 'gap') return gap(b) - gap(a)
      return (
        b.record.pipelines.agentic_graphrag.tokens.total -
        a.record.pipelines.agentic_graphrag.tokens.total
      )
    })
  }, [records, qtypeFilter, onlyDisagreeing, sortKey])

  const disagreeCount = useMemo(() => (records ?? []).filter(disagree).length, [records])

  return (
    <div className="view eval-table">
      <header className="view-head">
        <div>
          <h2>Per-question results</h2>
          <p className="muted">
            Every question in the run against all three pipelines. {disagreeCount} of{' '}
            {records?.length ?? 0} questions have the pipelines disagreeing — that filter is where
            the research question lives.
          </p>
        </div>
        <RunPicker runId={runId} onChange={setRunId} />
      </header>

      {loading && <p className="muted pad">Loading run "{runId}"…</p>}
      {error && <Notice onClose={clearError}>{error}</Notice>}

      {records && (
        <>
          <div className="filters">
            <label>
              Question type
              <select value={qtypeFilter} onChange={(e) => setQtypeFilter(e.target.value as QType | 'all')}>
                <option value="all">All</option>
                {QTYPES.map((qtype) => (
                  <option key={qtype} value={qtype}>
                    {titleCase(qtype)}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Pipeline
              <select
                value={pipelineFilter}
                onChange={(e) => setPipelineFilter(e.target.value as PipelineId | 'all')}
              >
                <option value="all">All three</option>
                {PIPELINE_IDS.map((pipeline) => (
                  <option key={pipeline} value={pipeline}>
                    {PIPELINE_LABELS[pipeline]}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Sort by
              <select value={sortKey} onChange={(e) => setSortKey(e.target.value as SortKey)}>
                <option value="qid">Question id</option>
                <option value="qtype">Question type</option>
                <option value="gap" disabled={!hasGold}>
                  Agentic &minus; RAG EM
                </option>
                <option value="tokens">Agentic tokens</option>
              </select>
            </label>

            <label className="checkbox">
              <input
                type="checkbox"
                checked={onlyDisagreeing}
                onChange={(e) => setOnlyDisagreeing(e.target.checked)}
              />
              Pipelines disagree only
            </label>
          </div>

          {!hasGold && (
            <p className="note pad">
              Run "{runId}" supplies no gold answers, so the gold and score columns are hidden.
            </p>
          )}

          <div className="matrix-scroll">
            <table className="matrix eval">
              <thead>
                <tr>
                  <th rowSpan={2}>Question</th>
                  {hasGold && <th rowSpan={2}>Gold</th>}
                  {shownPipelines.map((pipeline) => (
                    <th key={pipeline} colSpan={hasGold ? 7 : 4}>
                      <i className="swatch" style={{ background: PIPELINE_COLORS[pipeline] }} />
                      {PIPELINE_LABELS[pipeline]}
                    </th>
                  ))}
                </tr>
                <tr>
                  {shownPipelines.flatMap((pipeline) => {
                    const cols = hasGold
                      ? ['Answer', 'EM', 'F1', 'P', 'R', 'Tokens', 'Latency']
                      : ['Answer', 'Cites', 'Tokens', 'Latency']
                    return cols.map((col) => (
                      <th key={`${pipeline}-${col}`} className="sub">
                        {col}
                      </th>
                    ))
                  })}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const isOpen = expanded === row.qid
                  const detailId = `eval-detail-${row.qid}`
                  const toggle = () => setExpanded(isOpen ? null : row.qid)
                  return (
                    <Fragment key={row.qid}>
                      <tr
                        className={`eval-row ${isOpen ? 'open' : ''}`}
                        tabIndex={0}
                        aria-expanded={isOpen}
                        aria-controls={isOpen ? detailId : undefined}
                        onClick={toggle}
                        onKeyDown={(e) => {
                          if (e.target !== e.currentTarget) return
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault()
                            toggle()
                          }
                        }}
                      >
                        <th scope="row" className="question-cell">
                          <code>{row.qid}</code>
                          <span className="qtype-tag">{titleCase(row.qtype ?? "unknown")}</span>
                          <p>{row.question}</p>
                        </th>
                        {hasGold && (
                          <td className="gold-cell">
                            <strong>{row.ground_truth.join(' / ')}</strong>
                            <p className="muted small">{row.gold_doc_ids.join(', ')}</p>
                          </td>
                        )}
                        {shownPipelines.flatMap((pipeline) => {
                          const pr = row.record.pipelines[pipeline]
                          const sc = row.scores?.[pipeline]
                          // Every row has as many cells as the header, whatever it lacks.
                          const scoreCols = hasGold ? 4 : 1
                          if (!pr) {
                            return Array.from({ length: 3 + scoreCols }, (_, i) => (
                              <td key={`${pipeline}-none-${i}`} className="muted">—</td>
                            ))
                          }
                          const cells = [
                            <td key={`${pipeline}-a`} className="answer-cell">
                              {pr.answer}
                              {pipeline === 'agentic_graphrag' && (
                                <span className="muted small">
                                  {pr.trace?.length ?? 0} steps · {pr.stop_reason ?? '—'}
                                </span>
                              )}
                            </td>,
                          ]
                          if (sc) {
                            cells.push(
                              <td key={`${pipeline}-em`} className={sc.em ? 'gain' : 'loss'}>
                                {sc.em}
                              </td>,
                              <td key={`${pipeline}-f1`}>{dec(sc.f1)}</td>,
                              <td key={`${pipeline}-p`}>{dec(sc.precision)}</td>,
                              <td key={`${pipeline}-r`}>{dec(sc.recall)}</td>,
                            )
                          } else if (hasGold) {
                            // A run mixing scored and unscored questions: no gold for this one.
                            for (const k of ['em', 'f1', 'p', 'r']) {
                              cells.push(<td key={`${pipeline}-${k}`} className="muted">—</td>)
                            }
                          } else {
                            cells.push(<td key={`${pipeline}-c`}>{pr.citations_count}</td>)
                          }
                          cells.push(
                            <td key={`${pipeline}-t`}>{num(pr.tokens.total)}</td>,
                            <td key={`${pipeline}-l`}>{ms(pr.latency_ms)}</td>,
                          )
                          return cells
                        })}
                      </tr>
                      {isOpen && (
                        <tr id={detailId} className="drilldown">
                          <td colSpan={1 + (hasGold ? 1 : 0) + shownPipelines.length * (hasGold ? 7 : 4)}>
                            <div className="drilldown-body">
                              <div className="retrieved">
                                <h4>Retrieved document sets</h4>
                                {PIPELINE_IDS.map((pipeline) => (
                                  <div key={pipeline} className="retrieved-row">
                                    <span className="label">{PIPELINE_LABELS[pipeline]}</span>
                                    <code>
                                      {row.record.pipelines[pipeline].citations
                                        .map((c) => c.source_id)
                                        .join(', ') || '—'}
                                    </code>
                                  </div>
                                ))}
                                {hasGold && (
                                  <div className="retrieved-row gold">
                                    <span className="label">Gold</span>
                                    <code>{row.gold_doc_ids.join(', ')}</code>
                                  </div>
                                )}
                                <p className="verdict-summary">
                                  {row.record.verdict.summary_line}
                                </p>
                              </div>
                              <TracePanel
                                steps={row.record.pipelines.agentic_graphrag.trace ?? []}
                                running={false}
                                stopReason={row.record.pipelines.agentic_graphrag.stop_reason}
                                strategyChanged={
                                  row.record.pipelines.agentic_graphrag.strategy_changed
                                }
                              />
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>

          {!rows.length && <p className="muted pad">No questions match these filters.</p>}
        </>
      )}
    </div>
  )
}
