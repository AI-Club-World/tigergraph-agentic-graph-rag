import { Notice } from './components/Notice'
import { useEffect, useRef, useState } from 'react'
import { Icon } from './components/Icon'
import { QueryInput } from './components/QueryInput'
import { ResultColumn, type ColumnState } from './components/ResultColumn'
import { VerdictStrip } from './components/VerdictStrip'
import { TracePanel } from './TracePanel'
import { RequiresServices } from './ServiceStatus'
import { getQueryResult, openQueryStream, submitQuery } from './services/queryService'
import { ApiError } from './services/http'
import { EmbeddingMismatchDialog, type EmbeddingMismatch } from './components/EmbeddingMismatchDialog'
import { PIPELINE_IDS, type PipelineId, type QueryLevelRecord, type TraceStep } from './types'

type Columns = Record<PipelineId, ColumnState>

const RESULT_POLL_MS = 3000
const RESULT_WAIT_MS = 10 * 60 * 1000

/** The merged result, polling while the server reports it still running. */
async function resultWhenReady(queryId: string, current: () => boolean): Promise<QueryLevelRecord | null> {
  const deadline = Date.now() + RESULT_WAIT_MS
  for (;;) {
    try {
      return await getQueryResult(queryId)
    } catch (error) {
      const running = error instanceof ApiError && error.status === 409
      if (!running || Date.now() > deadline) throw error
      await new Promise((resolve) => setTimeout(resolve, RESULT_POLL_MS))
      if (!current()) return null
    }
  }
}

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
  // A query the server blocked: its selected embedding model has no complete
  // embeddings. It runs again only with a model the user picks from the list.
  const [mismatch, setMismatch] = useState<{ query: string; detail: EmbeddingMismatch } | null>(null)
  const cancelRef = useRef<(() => void) | null>(null)
  // Identifies the current run, so a late response from a superseded run
  // (its result fetch outlives the stream cancel) is dropped.
  const runRef = useRef(0)

  useEffect(() => () => cancelRef.current?.(), [])

  async function runQuery(query: string, embeddingModel?: string) {
    cancelRef.current?.()
    const run = ++runRef.current
    const current = () => run === runRef.current
    setColumns(RUNNING)
    setTrace([])
    setResult(null)
    setSubmitError(null)
    setInFlight(true)

    setMismatch(null)
    let accepted
    try {
      accepted = await submitQuery(query, embeddingModel)
    } catch (error) {
      if (!current()) return
      if (error instanceof ApiError && error.code === 'embedding_mismatch' && error.detail) {
        setMismatch({ query, detail: { ...(error.detail as unknown as EmbeddingMismatch), message: error.message } })
      } else {
        setSubmitError(error instanceof Error ? error.message : 'Could not reach the API')
      }
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
        // stream drops, so recover the columns from it — waiting while the
        // server still says it is running (409) rather than failing at once.
        try {
          const merged = await resultWhenReady(accepted.query_id, current)
          if (!current() || !merged) return
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

  function stopWaiting() {
    // The server finishes the run on its own; this page just stops following it.
    cancelRef.current?.()
    cancelRef.current = null
    runRef.current += 1
    setInFlight(false)
    setColumns((cols) => Object.fromEntries(PIPELINE_IDS.map((p) => [
      p, cols[p].status === 'running' ? { status: 'error', record: null, error: 'Stopped waiting' } : cols[p],
    ])) as Columns)
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
      <RequiresServices needs={['db', 'llm', 'emb']}>
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
          <QueryInput onSubmit={(query) => void runQuery(query)} disabled={inFlight} />
          {inFlight && (
            <button type="button" className="secondary stop-waiting" onClick={stopWaiting}>
              Stop waiting
            </button>
          )}
        </section>
        {mismatch && (
          <EmbeddingMismatchDialog
            mismatch={mismatch.detail}
            onPick={(model) => void runQuery(mismatch.query, model)}
            onCancel={() => setMismatch(null)}
          />
        )}

        <p className="sr-only" aria-live="polite" role="status">
          {announcement}
        </p>

        {submitError && <Notice onClose={() => setSubmitError(null)}>{submitError}</Notice>}

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
