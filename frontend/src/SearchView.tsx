import { useEffect, useRef, useState } from 'react'
import { QueryInput } from './components/QueryInput'
import { ResultColumn, type ColumnState } from './components/ResultColumn'
import { VerdictStrip } from './components/VerdictStrip'
import { TracePanel } from './TracePanel'
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

  useEffect(() => () => cancelRef.current?.(), [])

  async function runQuery(query: string) {
    cancelRef.current?.()
    setColumns(RUNNING)
    setTrace([])
    setResult(null)
    setSubmitError(null)
    setInFlight(true)

    let accepted
    try {
      accepted = await submitQuery(query)
    } catch (error) {
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
        setInFlight(false)
        try {
          setResult(await getQueryResult(accepted.query_id))
        } catch (error) {
          setSubmitError(error instanceof Error ? error.message : 'Could not load the merged result')
        }
      },
      onError: (message) => {
        setInFlight(false)
        setSubmitError(message)
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

  return (
    <div className="view search-view">
      <QueryInput onSubmit={runQuery} disabled={inFlight} />

      <p className="sr-only" aria-live="polite" role="status">
        {announcement}
      </p>

      {submitError && <p className="error-box pad">{submitError}</p>}

      {result ? (
        <VerdictStrip verdict={result.verdict} />
      ) : (
        <section className="verdict placeholder">
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
    </div>
  )
}
