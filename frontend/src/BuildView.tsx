import { useEffect, useRef, useState } from 'react'
import { Icon, type IconName } from './components/Icon'
import { StatusBadge } from './components/StatusBadge'
import { ms, num, titleCase } from './format'
import { RequiresServices } from './ServiceStatus'
import { openBuildStream, startBuild, type BuildOptions } from './services/buildService'
import { datasetNameFor, listCorpora, uploadCorpus, type CorporaResponse } from './services/datasetService'
import { ApiError } from './services/http'
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

const PIPELINE_ICONS: Record<PipelineId, IconName> = {
  rag: 'doc',
  graphrag: 'hub',
  agentic_graphrag: 'bot',
}

/**
 * The dependency flow groups build stages into the three layers the pipelines
 * wait on. A group is done once its gating pipeline turns ready, so a stage
 * name the backend adds later cannot leave a group stuck in flight.
 */
interface StageGroup {
  title: string
  detail: string
  icon: IconName
  gate: PipelineId
  stages: string[]
}

const STAGE_GROUPS: StageGroup[] = [
  {
    title: 'Foundation Layer',
    detail: 'Docs • Chunks • Embeddings • Vector index',
    icon: 'grid',
    gate: 'rag',
    stages: ['parse_infoboxes', 'chunk_documents', 'embed_chunks', 'vector_index'],
  },
  {
    title: 'Graph Indexing',
    detail: 'Schema • Vertices • Edges • Graph queries',
    icon: 'tree',
    gate: 'graphrag',
    stages: ['schema_install', 'remove_previous', 'load_vertices', 'load_edges', 'install_graph_queries'],
  },
  {
    title: 'Agentic Tooling',
    detail: 'Tool registry • Router',
    icon: 'sync',
    gate: 'agentic_graphrag',
    stages: ['register_agent_tools'],
  },
]

type GroupState = 'pending' | 'running' | 'done' | 'failed'

function groupState(group: StageGroup, columns: Record<PipelineId, BuildColumn>, seen: Set<string>): GroupState {
  if (columns[group.gate].status === 'ready') return 'done'
  if (columns[group.gate].status === 'error') return 'failed'
  return group.stages.some((stage) => seen.has(stage)) ? 'running' : 'pending'
}

/** One row per stage: its most recent event, in the order stages first appeared. */
function latestPerStage(log: BuildEvent[]): BuildEvent[] {
  const latest = new Map<string, BuildEvent>()
  for (const event of log) latest.set(event.stage, event)
  return [...latest.values()]
}

const secs = (n: number) => `${(n / 1000).toFixed(2)}s`

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <span className={tone ? `stat-value ${tone}` : 'stat-value'}>{value}</span>
    </div>
  )
}

export function BuildView() {
  const [columns, setColumns] = useState(initialColumns)
  const [buildId, setBuildId] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const cancelRef = useRef<(() => void) | null>(null)
  // Datasets: which corpus to build, and the rebuild/reset question the
  // server asks when the build would replace existing data.
  const [corpora, setCorpora] = useState<CorporaResponse | null>(null)
  const [dataset, setDataset] = useState('corpus')
  const [confirm, setConfirm] = useState<{ code: string; message: string } | null>(null)
  const [uploadNote, setUploadNote] = useState<{ ok: boolean; text: string } | null>(null)

  useEffect(() => () => cancelRef.current?.(), [])

  function refreshCorpora(select?: string) {
    listCorpora()
      .then((data) => {
        setCorpora(data)
        setDataset((current) => {
          const names = data.corpora.map((c) => c.name)
          if (select && names.includes(select)) return select
          return names.includes(current) ? current : names[0] ?? current
        })
      })
      .catch(() => setCorpora(null))
  }
  useEffect(() => refreshCorpora(), [])

  async function upload(file: File) {
    const name = datasetNameFor(file.name)
    setUploadNote(null)
    try {
      const added = await uploadCorpus(name, file)
      setUploadNote({ ok: true, text: `Added dataset '${added.name}' (${added.documents} documents).` })
      refreshCorpora(added.name)
    } catch (e) {
      setUploadNote({ ok: false, text: e instanceof Error ? e.message : 'Upload failed' })
    }
  }

  async function run(options: BuildOptions = {}) {
    cancelRef.current?.()
    setConfirm(null)
    setColumns(initialColumns())
    setBuildId(null)
    setError(null)
    setRunning(true)

    let accepted
    try {
      accepted = await startBuild(dataset, options)
    } catch (e) {
      if (e instanceof ApiError && (e.code === 'already_built' || e.code === 'reset_required')) {
        setConfirm({ code: e.code, message: e.message })
      } else {
        setError(e instanceof Error ? e.message : 'Could not start the build')
      }
      setRunning(false)
      return
    }
    setBuildId(accepted.build_id)

    cancelRef.current = openBuildStream(accepted, {
      onEvent: (event) =>
        setColumns((current) => {
          const next = { ...current }
          for (const pipeline of event.pipeline_affected) {
            next[pipeline] = apply(current[pipeline], event)
          }
          return next
        }),
      onDone: () => {
        setRunning(false)
        refreshCorpora()
      },
      onError: (message) => {
        setError(message)
        setRunning(false)
      },
    })
  }

  const seen = new Set(PIPELINE_IDS.flatMap((p) => columns[p].log.map((e) => e.stage)))
  const groups = STAGE_GROUPS.map((group) => ({ group, state: groupState(group, columns, seen) }))
  const allReady = groups.every((g) => g.state === 'done')
  const activeGroup = groups.findIndex((g) => g.state === 'running')
  const elapsed = Math.max(...PIPELINE_IDS.map((p) => columns[p].elapsedMs))
  const vertices = Math.max(...PIPELINE_IDS.map((p) => columns[p].counters.vertices))
  const edges = Math.max(...PIPELINE_IDS.map((p) => columns[p].counters.edges))

  // A stage that ended in error fails the build even though the stream closed cleanly.
  const failedAt = PIPELINE_IDS.map((p) => columns[p]).find((c) => c.status === 'error')?.stage ?? null
  const stageFailed = failedAt !== null

  const phase = stageFailed
    ? 'failed'
    : activeGroup >= 0 ? `stage ${activeGroup + 1}` : allReady ? 'complete' : 'idle'
  const flowLabel = stageFailed
    ? `Failed at ${titleCase(failedAt)}`
    : allReady
      ? 'All stages ready'
      : activeGroup >= 0
        ? `Stage ${activeGroup + 1}/${groups.length} in flight`
        : 'Idle'

  const syncState = error || stageFailed ? 'failed' : running ? 'running' : allReady ? 'complete' : 'idle'
  const syncLabel = {
    failed: 'Build failed',
    running: `Sync running: +${secs(elapsed)}`,
    complete: `Build complete: ${secs(elapsed)}`,
    idle: 'Idle',
  }[syncState]

  // Cumulative latency: when each pipeline turned ready, or how far it has got.
  const readyAt = PIPELINE_IDS.map((pipeline) => {
    const column = columns[pipeline]
    const ready = column.log.find((e) => e.status === 'ready')
    return {
      pipeline,
      ms: ready ? ready.elapsed_ms : column.elapsedMs,
      active: !ready && column.status === 'running',
    }
  })
  const latencyMax = Math.max(1, ...readyAt.map((r) => r.ms))

  return (
    <div className="view build-view">
      <header className="panel-x build-head">
        <div>
          <p className="build-meta">
            <span className="tag">Pipeline ops // {phase}</span>
            <span>JOB-ID: {buildId ?? '—'}</span>
          </p>
          <h2>Ingestion build</h2>
          <p className="build-lede">
            One shared build. Each column shows when that pipeline becomes answerable, fanned out by
            the stages it depends on — RAG consumes the foundation, GraphRAG pays for the graph, and
            Agentic turns ready last.
          </p>
        </div>
        <div className="build-actions">
          <span className={`live-flag ${syncState}`}>
            <span className="dot" aria-hidden="true" />
            {syncLabel}
          </span>
          <RequiresServices needs={['db', 'emb']}>
            <button type="button" className="btn-primary" onClick={() => run()} disabled={running || !!confirm}>
              <Icon name="restart" size={16} className={running ? 'spin' : undefined} />
              {running ? 'Building…' : 'Start build'}
            </button>
          </RequiresServices>
        </div>
      </header>

      <section className="panel-x dataset-panel" aria-label="Dataset">
        <div className="dataset-row">
          <label htmlFor="build-dataset" className="section-label">Dataset</label>
          <select
            id="build-dataset"
            value={dataset}
            onChange={(e) => { setDataset(e.target.value); setConfirm(null) }}
            disabled={running}
          >
            {(corpora?.corpora ?? [{ name: dataset, documents: 0, size_bytes: 0, built: null }]).map((c) => (
              <option key={c.name} value={c.name}>
                {c.name} — {num(c.documents)} docs{c.built ? ' · built' : ''}
              </option>
            ))}
          </select>
          <label className="secondary dataset-upload">
            Upload JSONL…
            <input
              type="file"
              accept=".jsonl,.ndjson,application/x-ndjson"
              hidden
              disabled={running}
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) void upload(file)
                e.target.value = ''
              }}
            />
          </label>
        </div>
        <p className="muted small">
          Each line: {'{"doc_id", "title", "text", "url"}'}. Building a new dataset adds it to the graph and keeps the
          datasets already loaded.
          {corpora && Object.keys(corpora.graph.datasets).length > 0 && (
            <> Loaded: {Object.entries(corpora.graph.datasets)
              .map(([name, info]) => `${name} (${num(info.documents)} docs)`)
              .join(', ')}.</>
          )}
        </p>
        {uploadNote && <p className={uploadNote.ok ? 'flash' : 'error-box pad'}>{uploadNote.text}</p>}
        {confirm && (
          <div className="confirm-box" role="alertdialog" aria-label="Confirm build">
            <p>{confirm.message}</p>
            <div className="confirm-actions">
              <button type="button" className="secondary" onClick={() => setConfirm(null)}>
                Cancel
              </button>
              {confirm.code === 'already_built' ? (
                <button type="button" className="btn-primary" onClick={() => run({ rebuild: true })}>
                  Rebuild {dataset}
                </button>
              ) : (
                <button type="button" className="btn-primary danger" onClick={() => run({ reset: true })}>
                  Reset graph and build
                </button>
              )}
            </div>
          </div>
        )}
      </section>

      {error && <p className="error-box pad">{error}</p>}

      <section className="panel-x flow">
        <header className="flow-head">
          <span className="section-label">Dependency execution flow</span>
          <span className="flow-state">{flowLabel}</span>
        </header>
        <ol className="flow-steps">
          {groups.map(({ group, state }, i) => (
            <li key={group.title} className={`flow-step ${state}`} data-pipeline={group.gate}>
              <span className="flow-icon">
                <Icon
                  name={group.icon}
                  size={18}
                  className={state === 'running' && group.icon === 'sync' ? 'spin' : undefined}
                />
              </span>
              <div>
                <p className="flow-title">
                  {i + 1}. {group.title}
                  {state === 'done' && <Icon name="checkCircle" size={15} className="gain" />}
                  {state === 'running' && <span className="flow-running">running</span>}
                  {state === 'failed' && <span className="flow-running">failed</span>}
                </p>
                <p className="flow-detail">{group.detail}</p>
              </div>
              {i < groups.length - 1 && (
                <span className="flow-arrow">
                  <Icon name="arrowRight" size={14} />
                </span>
              )}
            </li>
          ))}
        </ol>
      </section>

      <div className="columns">
        {PIPELINE_IDS.map((pipeline) => {
          const column = columns[pipeline]
          const progress = column.itemsTotal ? column.itemsDone / column.itemsTotal : 0
          const pct = Math.round(progress * 100)
          // 'done' means one stage finished and the next has not started yet.
          const active = column.status === 'running' || column.status === 'done'
          return (
            <section key={pipeline} className="pcard bcard" data-pipeline={pipeline} data-status={column.status}>
              <header className="pcard-head">
                <h3 className="bcard-title">
                  <Icon name={PIPELINE_ICONS[pipeline]} size={20} className="pipe-color" />
                  {PIPELINE_LABELS[pipeline]}
                </h3>
                <StatusBadge status={column.status} />
              </header>

              <div className="bcard-body">
                <div className="stage-row">
                  <span className="muted">Current Stage</span>
                  <span className={active ? 'stage-name live' : 'stage-name'}>
                    {active && <Icon name="sync" size={13} className="spin" />}
                    {column.stage ? titleCase(column.stage) : 'Not started'}
                  </span>
                </div>

                <div className="progress-meta">
                  <span>
                    {num(column.itemsDone)} / {num(column.itemsTotal)} items
                  </span>
                  <span className="pipe-color">{pct}%</span>
                </div>
                <div
                  className="progress"
                  role="progressbar"
                  aria-valuenow={pct}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label={`${PIPELINE_LABELS[pipeline]} stage progress`}
                >
                  <div className="progress-bar" style={{ width: `${pct}%` }} />
                </div>

                <div className="stat-grid three">
                  <Stat label="Elapsed" value={ms(column.elapsedMs)} tone={active ? 'pipe-color' : undefined} />
                  <Stat label="Documents" value={num(column.counters.documents)} />
                  <Stat label="Chunks" value={num(column.counters.chunks)} />
                  <Stat label="Vertices" value={num(column.counters.vertices)} />
                  <Stat label="Edges" value={num(column.counters.edges)} />
                </div>

                <p className="token-row">
                  <Icon name="chip" size={15} className="pipe-color" />
                  LLM tokens: {num(column.tokens)} (local embedding model)
                </p>

                <details className="stage-log" open={active || undefined}>
                  <summary>
                    <Icon name="chevronRight" size={16} className="chev" />
                    <span>{column.log.length} stage events</span>
                    <span className="stage-log-state">
                      {column.status === 'ready'
                        ? 'Complete'
                        : active
                          ? 'In flight'
                          : column.status === 'error'
                            ? 'Failed'
                            : ''}
                    </span>
                  </summary>
                  <ol>
                    {latestPerStage(column.log).map((event, i, rows) => {
                      const current = active && i === rows.length - 1
                      return (
                        <li
                          key={event.stage}
                          className={current ? `log-${event.status} current` : `log-${event.status}`}
                          title={event.note}
                        >
                          <span className="log-dot" aria-hidden="true" />
                          <code>{event.stage}</code>
                          <span className="log-status">{event.status}</span>
                          <span className="log-time">{ms(event.elapsed_ms)}</span>
                          {current && <p className="log-note">{event.note}</p>}
                        </li>
                      )
                    })}
                  </ol>
                </details>
              </div>
            </section>
          )
        })}
      </div>

      <div className="build-summary">
        <section className="panel-x">
          <header className="panel-x-head">
            <h3 className="panel-x-title">
              <Icon name="gauge" size={18} className="accent" />
              Cumulative Ingestion Latency
            </h3>
            <span className="muted mono small">Time to ready</span>
          </header>
          <div className="latency-bars">
            {readyAt.map((row, i) => {
              const delta = i > 0 ? row.ms - readyAt[i - 1].ms : 0
              return (
                <div key={row.pipeline} className="latency-row" data-pipeline={row.pipeline}>
                  <div className="latency-label">
                    <span className="pipe-color">
                      {PIPELINE_LABELS[row.pipeline]}
                      {i > 0 && row.ms > 0 && ` (+${secs(delta)}${row.active ? ' active' : ''})`}
                    </span>
                    <span>{(row.ms / 1000).toFixed(2)} s</span>
                  </div>
                  <div className="progress">
                    <div className="progress-bar" style={{ width: `${Math.round((row.ms / latencyMax) * 100)}%` }} />
                  </div>
                </div>
              )
            })}
          </div>
        </section>

        <section className="panel-x">
          <header className="panel-x-head">
            <h3 className="panel-x-title">
              <Icon name="share" size={18} className="agentic" />
              Shared Graph Store Density
            </h3>
          </header>
          <p className="muted small">
            Indexed document chunks mapped into the unified knowledge graph that GraphRAG and Agentic
            GraphRAG traverse for multi-hop questions.
          </p>
          <div className="density-grid">
            <div className="density-card">
              <span className="icon-box accent lg">
                <Icon name="circle" size={22} />
              </span>
              <div>
                <span className="stat-label">Total Vertices</span>
                <span className="density-value">{num(vertices)}</span>
              </div>
            </div>
            <div className="density-card">
              <span className="icon-box gain lg">
                <Icon name="share" size={22} />
              </span>
              <div>
                <span className="stat-label">Total Edges</span>
                <span className="density-value">{num(edges)}</span>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}
