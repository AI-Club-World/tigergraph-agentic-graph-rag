import { useRef, useState, type FormEvent } from 'react'
import { Notice } from './components/Notice'
import { ms, num } from './format'
import { askRound2 } from './services/r2Service'
import type { R2Answer, R2Status, R2TraceStep } from './types'

const STATUS_LABEL: Record<R2Status, string> = {
  answered: 'Answered',
  partial: 'Partial',
  not_in_corpus: 'Not in corpus',
}

const STATUS_HELP: Record<R2Status, string> = {
  answered: 'Fully supported by the corpus',
  partial: 'Only some parts are in the corpus',
  not_in_corpus: 'Nothing in the corpus answers this',
}

export function R2StatusBadge({ status }: { status: R2Status }) {
  // The text is the primary signal; colour and the leading mark only reinforce it.
  const mark = { answered: '✓', partial: '◐', not_in_corpus: '∅' }[status]
  return (
    <span className={`r2-status r2-status-${status}`} title={STATUS_HELP[status]}>
      <span aria-hidden="true">{mark}</span> {STATUS_LABEL[status] ?? status}
    </span>
  )
}

function cell(value: unknown): string {
  if (value === null || value === undefined) return ''
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

function isRowList(value: unknown): value is Record<string, unknown>[] {
  return (
    Array.isArray(value) &&
    value.length > 0 &&
    value.every((row) => typeof row === 'object' && row !== null && !Array.isArray(row))
  )
}

/** Text as text, a list of objects as a table, any other JSON as formatted pre. */
export function AnswerBody({ answer }: { answer: unknown }) {
  if (answer === null || answer === undefined || answer === '') {
    return <p className="muted">No answer returned.</p>
  }
  if (typeof answer === 'string') return <p className="r2-answer-text">{answer}</p>
  if (isRowList(answer)) {
    const columns = [...new Set(answer.flatMap((row) => Object.keys(row)))]
    return (
      <div className="r2-table-wrap">
        <table className="matrix r2-table">
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c} scope="col">{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {answer.map((row, i) => (
              <tr key={i}>
                {columns.map((c) => (
                  <td key={c} className="text">{cell(row[c])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }
  if (typeof answer === 'object') return <pre className="r2-pre">{JSON.stringify(answer, null, 2)}</pre>
  return <p className="r2-answer-text">{String(answer)}</p>
}

function params(step: R2TraceStep): string {
  return step.params && Object.keys(step.params).length ? JSON.stringify(step.params) : ''
}

export function R2Trace({ steps }: { steps: R2TraceStep[] }) {
  return (
    <ol className="r2-trace" aria-label="Agent trace">
      {steps.map((s) => {
        const tokens = (s.input_tokens ?? 0) + (s.output_tokens ?? 0)
        const hasTokens = s.input_tokens !== undefined || s.output_tokens !== undefined
        return (
          <li key={s.step} className={s.tigergraph ? 'r2-step r2-step-tg' : 'r2-step'}>
            <span className="step-n">{s.step}</span>
            <div className="r2-step-body">
              <div className="r2-step-head">
                <code className="tool">{s.tool}</code>
                {s.tigergraph && <span className="tag tag-gain">TigerGraph</span>}
                {s.query && <code className="r2-query">{s.query}</code>}
                <span className="r2-step-metrics">
                  {s.rows !== undefined && s.rows !== null && <span>{num(s.rows)} rows</span>}
                  {hasTokens && (
                    <span title={`input ${num(s.input_tokens ?? 0)} / output ${num(s.output_tokens ?? 0)}`}>
                      {num(tokens)} tokens
                    </span>
                  )}
                  <span>{ms(s.ms)}</span>
                </span>
              </div>
              {params(s) && <code className="r2-params">{params(s)}</code>}
              {s.note && <p className="step-notes">{s.note}</p>}
            </div>
          </li>
        )
      })}
    </ol>
  )
}

export function R2Result({ result }: { result: R2Answer }) {
  const llmCalls = result.trace.filter((s) => s.input_tokens !== undefined || s.output_tokens !== undefined).length
  const tgQueries = result.trace.filter((s) => s.tigergraph).length
  const totals: [string, string][] = [
    ['Tokens in', num(result.input_tokens)],
    ['Tokens out', num(result.output_tokens)],
    ['Latency', ms(result.latency_ms)],
    ['LLM calls', num(llmCalls)],
    ['TigerGraph queries', num(tgQueries)],
  ]
  return (
    <>
      <section className="panel-x" aria-label="Answer">
        <header className="panel-x-head">
          <h3 className="panel-x-title">Answer</h3>
          <R2StatusBadge status={result.status} />
        </header>
        <AnswerBody answer={result.answer} />
        {result.explanation && (
          <>
            <h4 className="section-label">Explanation</h4>
            <p className="r2-explanation">{result.explanation}</p>
          </>
        )}
        <h4 className="section-label">Citations</h4>
        {result.citations.length ? (
          <ul className="citations" aria-label="Citations">
            {result.citations.map((id) => (
              <li key={id} className="cite">
                <span className="cite-toggle"><code>{id}</code></span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted small">No citations.</p>
        )}
        <dl className="r2-totals">
          {totals.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
        {result.graph_backend === 'local' && (
          <p className="muted small">Development backend: not a TigerGraph run.</p>
        )}
      </section>
      <section className="panel-x" aria-label="Trace">
        <header className="panel-x-head">
          <div>
            <h3 className="panel-x-title">Trace</h3>
            <p className="panel-x-sub">Every model call and every TigerGraph query, in order</p>
          </div>
          <span className="muted small">{result.trace.length} steps</span>
        </header>
        <R2Trace steps={result.trace} />
      </section>
    </>
  )
}

export function Round2View() {
  const [question, setQuestion] = useState('')
  const [result, setResult] = useState<R2Answer | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const run = useRef(0)

  async function submit(event: FormEvent) {
    event.preventDefault()
    const q = question.trim()
    if (!q || loading) return
    const mine = ++run.current
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const answer = await askRound2(q)
      if (mine === run.current) setResult(answer)
    } catch (e) {
      if (mine === run.current) setError(e instanceof Error ? e.message : 'Could not reach the API')
    } finally {
      if (mine === run.current) setLoading(false)
    }
  }

  return (
    <div className="view r2-view">
      <div className="view-head">
        <div>
          <h2>Round 2 agent</h2>
          <p className="muted">Ask any question about the corpus. The agent queries TigerGraph and shows its work.</p>
        </div>
      </div>

      <section className="panel-x">
        <form className="query-input" onSubmit={(e) => void submit(e)}>
          <div className="query-row">
            <label className="query-field">
              <input
                type="text"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Type a question"
                aria-label="Question"
              />
            </label>
            <button type="submit" className="btn-primary" disabled={loading || !question.trim()}>
              {loading ? 'Working…' : 'Ask'}
            </button>
          </div>
        </form>
      </section>

      <p className="sr-only" role="status" aria-live="polite">
        {loading ? 'The agent is working.' : result ? `Answer ready: ${STATUS_LABEL[result.status]}.` : ''}
      </p>

      {loading && (
        <p className="muted r2-loading">
          <span className="spinner" aria-hidden="true" /> The agent is querying the graph. This can take a
          little while.
        </p>
      )}
      {error && <Notice onClose={() => setError(null)}>{error}</Notice>}
      {result && <R2Result result={result} />}
    </div>
  )
}
