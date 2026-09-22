import { useEffect, useRef, useState } from 'react'
import { StatusBadge } from './components/StatusBadge'
import { ms, num, titleCase } from './format'
import { openBuildStream, startBuild } from './services/buildService'
import { PIPELINE_IDS, PIPELINE_LABELS, type BuildEvent, type PipelineId } from './types'

interface Counters {
  documents: number
  chunks: number
  vertices: number
  edges: number
}

interface BuildColumn {
  status: 'idle' | 'running' | 'done' | 'error' | 'ready'
  stage: string | null
  itemsDone: number
  itemsTotal: number
  elapsedMs: number
  tokens: number
  counters: Counters
  log: BuildEvent[]
}

/**
 * Which counter a stage advances. Stages absent from the map still drive the
 * progress bar; they just do not own a headline number.
 */
const STAGE_COUNTER: Record<string, keyof Counters> = {
  parse_infoboxes: 'documents',
  chunk_documents: 'chunks',
  embed_chunks: 'chunks',
  load_vertices: 'vertices',
  load_edges: 'edges',
}

const EMPTY: BuildColumn = {
  status: 'idle',
  stage: null,
  itemsDone: 0,
  itemsTotal: 0,
  elapsedMs: 0,
  tokens: 0,
  counters: { documents: 0, chunks: 0, vertices: 0, edges: 0 },
  log: [],
}

const initialColumns = (): Record<PipelineId, BuildColumn> => ({
  rag: { ...EMPTY, counters: { ...EMPTY.counters }, log: [] },
  graphrag: { ...EMPTY, counters: { ...EMPTY.counters }, log: [] },
  agentic_graphrag: { ...EMPTY, counters: { ...EMPTY.counters }, log: [] },
})

function apply(column: BuildColumn, event: BuildEvent): BuildColumn {
  const counters = { ...column.counters }
  const counter = STAGE_COUNTER[event.stage]
  if (counter) counters[counter] = Math.max(counters[counter], event.items_done)

  return {
    status: event.status === 'ready' ? 'ready' : column.status === 'ready' ? 'ready' : event.status,
    stage: event.status === 'ready' ? column.stage : event.stage,
    itemsDone: event.items_done,
    itemsTotal: event.items_total,
    elapsedMs: event.elapsed_ms,
    tokens: column.tokens + event.tokens,
    counters,
    log: [...column.log, event],
  }
}

export function BuildView() {
  const [columns, setColumns] = useState(initialColumns)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const cancelRef = useRef<(() => void) | null>(null)

  useEffect(() => () => cancelRef.current?.(), [])

  async function run() {
    cancelRef.current?.()
    setColumns(initialColumns())
    setError(null)
    setRunning(true)

    let accepted
    try {
      accepted = await startBuild()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start the build')
      setRunning(false)
      return
    }

    cancelRef.current = openBuildStream(accepted, {
      onEvent: (event) =>
        setColumns((current) => {
          const next = { ...current }
          for (const pipeline of event.pipeline_affected) {
            next[pipeline] = apply(current[pipeline], event)
          }
          return next
        }),
      onDone: () => setRunning(false),
      onError: (message) => {
        setError(message)
        setRunning(false)
      },
    })
  }

  return (
    <div className="view build-view">
      <header className="view-head">
        <div>
          <h2>Ingestion build</h2>
          <p className="muted">
            One shared build. Each column shows when that pipeline becomes answerable, fanned out by
            the stages it depends on — RAG consumes the foundation, GraphRAG pays for the graph, and
            Agentic turns ready last.
          </p>
        </div>
        <button type="button" onClick={run} disabled={running}>
          {running ? 'Building…' : 'Start build'}
        </button>
      </header>

      {error && <p className="error-box pad">{error}</p>}

      <div className="columns">
        {PIPELINE_IDS.map((pipeline) => {
          const column = columns[pipeline]
          const progress = column.itemsTotal ? column.itemsDone / column.itemsTotal : 0
          return (
            <section key={pipeline} className="column" data-status={column.status}>
              <header className="column-head">
                <h3>{PIPELINE_LABELS[pipeline]}</h3>
                <StatusBadge status={column.status} />
              </header>

              <div className="pad">
                <p className="stage-name">
                  {column.stage ? titleCase(column.stage) : 'Not started'}
                </p>
                <div className="progress">
                  <div className="progress-bar" style={{ width: `${Math.round(progress * 100)}%` }} />
                </div>
                <p className="muted small">
                  {num(column.itemsDone)} / {num(column.itemsTotal)} items
                </p>
              </div>

              <div className="metrics">
                <div className="metric">
                  <span className="metric-value">{ms(column.elapsedMs)}</span>
                  <span className="metric-label">elapsed</span>
                </div>
                <div className="metric">
                  <span className="metric-value">{num(column.counters.documents)}</span>
                  <span className="metric-label">documents</span>
                </div>
                <div className="metric">
                  <span className="metric-value">{num(column.counters.chunks)}</span>
                  <span className="metric-label">chunks</span>
                </div>
                <div className="metric">
                  <span className="metric-value">{num(column.counters.vertices)}</span>
                  <span className="metric-label">vertices</span>
                </div>
                <div className="metric">
                  <span className="metric-value">{num(column.counters.edges)}</span>
                  <span className="metric-label">edges</span>
                </div>
              </div>

              <p className="note">LLM tokens: {num(column.tokens)} (local embedding model)</p>

              <details className="stage-log">
                <summary>{column.log.length} stage events</summary>
                <ol>
                  {column.log.map((event, i) => (
                    <li key={`${event.stage}-${event.elapsed_ms}-${i}`}>
                      <code>{event.stage}</code> <span className="muted">{event.status}</span>
                      <p className="muted small">{event.note}</p>
                    </li>
                  ))}
                </ol>
              </details>
            </section>
          )
        })}
      </div>
    </div>
  )
}
