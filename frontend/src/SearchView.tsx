import { useEffect, useRef, useState } from 'react'
import { Icon } from './components/Icon'
import { QueryInput } from './components/QueryInput'
import { ResultColumn, type ColumnState } from './components/ResultColumn'
import { VerdictStrip } from './components/VerdictStrip'
import { TracePanel } from './TracePanel'
import { RequiresServices } from './ServiceStatus'
import { getQueryResult, openQueryStream, submitQuery } from './services/queryService'
import { PIPELINE_IDS, type PipelineId, type QueryLevelRecord, type TraceStep } from './types'

type Columns = Record<PipelineId, ColumnState>

const IDLE: Columns = {
  rag: { status: 'idle', record: null, error: null },
  graphrag: { status: 'idle', record: null, error: null },
  agentic_graphrag: { status: 'idle', record: null, error: null },
}

const RUNNING: Columns = {
  rag: { status: 'running', record: null, error: null },
  graphrag: { status: 'running', record: null, error: null },
  agentic_graphrag: { status: 'running', record: null, error: null },
}

export function SearchView() {
  const [columns, setColumns] = useState<Columns>(IDLE)
  const [trace, setTrace] = useState<TraceStep[]>([])
  const [result, setResult] = useState<QueryLevelRecord | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [inFlight, setInFlight] = useState(false)
  const cancelRef = useRef<(() => void) | null>(null)
  // Identifies the current run, so a late response from a superseded run
  // (its result fetch outlives the stream cancel) is dropped.
  const runRef = useRef(0)

  useEffect(() => () => cancelRef.current?.(), [])

  async function runQuery(query: string) {
    cancelRef.current?.()
    const run = ++runRef.current
    const current = () => run === runRef.current
    setColumns(RUNNING)
    setTrace([])
    setResult(null)
    setSubmitError(null)
    setInFlight(true)

    let accepted
    try {
      accepted = await submitQuery(query)
    } catch (error) {
      if (!current()) return
      setSubmitError(error instanceof Error ? error.message : 'Could not reach the API')
      setColumns(IDLE)
      setInFlight(false)
      return
    }

    cancelRef.current = openQueryStream(accepted, {
      onTrace: (step) => setTrace((steps) => [...steps, step]),
      onPipeline: (record) =>
        setColumns((current) => ({
          ...current,
          [record.pipeline]: {
            status: record.status,
            record,
            error: record.error_detail,
          },
        })),
      onDone: async () => {
        try {
          const merged = await getQueryResult(accepted.query_id)
          if (current()) setResult(merged)
        } catch (error) {
          if (current()) setSubmitError(error instanceof Error ? error.message : 'Could not load the merged result')
        } finally {
          if (current()) setInFlight(false)
        }
      },
      onError: async (message) => {
        // The backend finishes the run and keeps its result even when the
        // stream drops, so recover the columns from it where possible.
        try {
          const merged = await getQueryResult(accepted.query_id)
          if (!current()) return
          setColumns(Object.fromEntries(PIPELINE_IDS.map((p) => {
            const record = merged.pipelines[p]
            return [p, { status: record.status, record, error: record.error_detail }]
          })) as Columns)
          setResult(merged)
        } catch {
          if (!current()) return
          setSubmitError(message)
          setColumns((cols) => Object.fromEntries(PIPELINE_IDS.map((p) => [
            p, cols[p].status === 'running' ? { status: 'error', record: null, error: message } : cols[p],
          ])) as Columns)
        } finally {
          if (current()) setInFlight(false)
        }
      },
    })
  }

  const agentic = columns.agentic_graphrag
  const settled = PIPELINE_IDS.filter((p) => ['done', 'error'].includes(columns[p].status)).length
  // Concise status for screen readers; only changes when a pipeline settles, a
  // trace step arrives, or the verdict lands.
  const announcement = result
    ? 'All three pipelines complete. Verdict ready.'
    : inFlight
      ? `${settled} of 3 pipelines complete, ${trace.length} trace ${trace.length === 1 ? 'step' : 'steps'}.`
      : ''

  const consoleState = inFlight ? 'running' : result ? 'complete' : 'idle'
  const consoleLabel = {
    idle: 'Awaiting query',
    running: `Synchronized run · ${settled}/3 settled`,
    complete: 'Synchronized benchmark complete',
  }[consoleState]

  return (
    <div className="view search-view">
      <RequiresServices needs={['db', 'llm']}>
        <section className="panel-x console">
          <header className="panel-x-head">
            <h2 className="panel-x-title">
              <Icon name="scan" size={20} className="accent" />
              Synchronous Execution Console
            </h2>
            <span className={`live-flag ${consoleState}`}>
              <span className="dot" aria-hidden="true" />
              {consoleLabel}
            </span>
          </header>
          <QueryInput onSubmit={runQuery} disabled={inFlight} />
        </section>

        <p className="sr-only" aria-live="polite" role="status">
          {announcement}
        </p>

        {submitError && <p className="error-box pad">{submitError}</p>}

        {result ? (
          <VerdictStrip verdict={result.verdict} />
        ) : (
          <section className="panel-x verdict placeholder">
            <header className="panel-x-head">
              <h3 className="panel-x-title">
                <span className="icon-box">
                  <Icon name="checkCircle" size={16} />
                </span>
                Verdict: pending
              </h3>
            </header>
            <p className="muted">
              The verdict strip renders once all three pipelines have completed.
            </p>
          </section>
        )}

        <div className="columns">
          {PIPELINE_IDS.map((pipeline) => (
            <ResultColumn key={pipeline} pipeline={pipeline} state={columns[pipeline]} />
          ))}
        </div>

        <TracePanel
          steps={trace}
          running={agentic.status === 'running'}
          stopReason={agentic.record?.stop_reason ?? null}
          strategyChanged={agentic.record?.strategy_changed ?? null}
        />
      </RequiresServices>
    </div>
  )
}
