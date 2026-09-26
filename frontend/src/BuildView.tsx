import { Notice } from './components/Notice'
import { useEffect, useRef, useState } from 'react'
import { Icon, type IconName } from './components/Icon'
import { StatusBadge } from './components/StatusBadge'
import { ms, num, titleCase } from './format'
import { RequiresServices } from './ServiceStatus'
import { openBuildStream, startBuild, type BuildOptions } from './services/buildService'
import {
  datasetNameFor,
  listCorpora,
  uploadCorpus,
  type BuiltInfo,
  type CorporaResponse,
} from './services/datasetService'
import { ApiError } from './services/http'
import { PIPELINE_IDS, PIPELINE_LABELS, type BuildEvent, type PipelineId } from './types'

interface Counters {
  documents: number
  chunks: number
  vectors: number
  entities: number
  relationships: number
}

interface BuildColumn {
  status: 'idle' | 'running' | 'done' | 'error' | 'ready'
  stage: string | null
  itemsDone: number
  itemsTotal: number
  elapsedMs: number
  counters: Counters
  /** Embedding model and tier from the embed stage — building calls no LLM. */
  embedding: string | null
  log: BuildEvent[]
}

/**
 * Which counter a stage advances. Stages absent from the map still drive the
 * progress bar; they just do not own a headline number.
 */
const STAGE_COUNTER: Record<string, keyof Counters> = {
  parse_infoboxes: 'documents',
  chunk_documents: 'chunks',
  embed_chunks: 'vectors',
  load_vertices: 'entities',
  load_edges: 'relationships',
}

/** What each pipeline is built from: RAG answers from chunk vectors,
 *  GraphRAG from the graph, Agentic GraphRAG from the graph with vector
 *  search as a fallback tool — so each column shows only its own data. */
const PIPELINE_METRICS: Record<PipelineId, Array<[string, keyof Counters]>> = {
  rag: [['Chunks', 'chunks'], ['Vectors', 'vectors']],
  graphrag: [['Documents', 'documents'], ['Entities', 'entities'], ['Relationships', 'relationships']],
  agentic_graphrag: [['Entities', 'entities'], ['Relationships', 'relationships'], ['Vectors', 'vectors']],
}

/** Relative cost of each stage (embedding dominates), for percent complete. */
const STAGE_WEIGHTS: Record<string, number> = {
  parse_infoboxes: 5,
  chunk_documents: 5,
  embed_chunks: 40,
  schema_install: 5,
  remove_previous: 5,
  load_vertices: 10,
  load_edges: 5,
  load_chunks: 10,
  install_graph_queries: 5,
  vector_index: 10,
}

/** The stages each pipeline waits on (matches the backend's fan-out). */
const PIPELINE_STAGES: Record<PipelineId, string[]> = {
  rag: ['chunk_documents', 'embed_chunks', 'schema_install', 'remove_previous', 'load_chunks',
    'install_graph_queries', 'vector_index'],
  graphrag: ['parse_infoboxes', 'schema_install', 'remove_previous', 'load_vertices', 'load_edges',
    'install_graph_queries'],
  agentic_graphrag: Object.keys(STAGE_WEIGHTS),
}

/** Percent of this pipeline's build done: finished stages count fully, the
 *  running one by its items. remove_previous only counts on a rebuild. */
function percentComplete(pipeline: PipelineId, column: BuildColumn): number {
  if (column.status === 'ready') return 100
  const latest = new Map(column.log.map((e) => [e.stage, e]))
  const stages = PIPELINE_STAGES[pipeline].filter((s) => s !== 'remove_previous' || latest.has(s))
  const total = stages.reduce((sum, s) => sum + STAGE_WEIGHTS[s], 0)
  const done = stages.reduce((sum, s) => {
    const event = latest.get(s)
    if (!event) return sum
    if (event.status === 'done') return sum + STAGE_WEIGHTS[s]
    const fraction = event.items_total ? Math.min(1, event.items_done / event.items_total) : 0
    return sum + STAGE_WEIGHTS[s] * fraction
  }, 0)
  return total ? Math.min(99, Math.floor((done / total) * 100)) : 0
}

const EMPTY: BuildColumn = {
  status: 'idle',
  stage: null,
  itemsDone: 0,
  itemsTotal: 0,
  elapsedMs: 0,
  counters: { documents: 0, chunks: 0, vectors: 0, entities: 0, relationships: 0 },
  embedding: null,
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
    // Ready is the pipeline's final state, not the last stage it passed.
    stage: event.status === 'ready' || column.status === 'ready' ? 'ready' : event.stage,
    itemsDone: event.items_done,
    itemsTotal: event.items_total,
    elapsedMs: event.elapsed_ms,
    counters,
    embedding: event.stage === 'embed_chunks' && event.note && event.status === 'done' ? event.note : column.embedding,
    log: [...column.log, event],
  }
}

/** Columns for datasets already in the graph (after a reload, no live build):
 *  every pipeline ready, totals over all loaded datasets. */
function restoredColumns(datasets: Record<string, BuiltInfo>): Record<PipelineId, BuildColumn> {
  const entries = Object.values(datasets)
  const sum = (key: keyof BuiltInfo) => entries.reduce((n, d) => n + (Number(d[key]) || 0), 0)
  const latest = [...entries].sort((a, b) => a.built_at.localeCompare(b.built_at)).at(-1)
  const counters: Counters = {
    documents: sum('documents'),
    chunks: sum('chunks'),
    vectors: entries.reduce((n, d) => n + (d.vectors ?? d.chunks ?? 0), 0),
    entities: entries.reduce((n, d) => n + (d.entities ?? d.documents + (d.events ?? 0)), 0),
    relationships: sum('relationships'),
  }
  const column = (pipeline: PipelineId): BuildColumn => ({
    ...EMPTY,
    status: 'ready',
    stage: 'ready',
    elapsedMs: latest?.ready_ms?.[pipeline] ?? 0,
    counters: { ...counters },
    embedding: latest?.embedding_backend ? `@cf/baai/bge-m3 via ${latest.embedding_backend}` : null,
    log: [],
  })
  return { rag: column('rag'), graphrag: column('graphrag'), agentic_graphrag: column('agentic_graphrag') }
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
    detail: 'Chunks • Embeddings • Vector index (RAG)',
    icon: 'grid',
    gate: 'rag',
    stages: ['chunk_documents', 'embed_chunks', 'load_chunks', 'vector_index'],
  },
  {
    title: 'Graph Indexing',
    detail: 'Entities • Relationships • Graph queries (GraphRAG)',
    icon: 'tree',
    gate: 'graphrag',
    stages: ['parse_infoboxes', 'schema_install', 'remove_previous', 'load_vertices', 'load_edges', 'install_graph_queries'],
  },
  {
    title: 'Agentic Tooling',
    detail: 'Graph tools + vector fallback (Agentic GraphRAG)',
    icon: 'sync',
    gate: 'agentic_graphrag',
    stages: ['install_graph_queries', 'vector_index'],
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
        // After a reload there is no live build: show what the graph holds.
        if (Object.keys(data.graph.datasets).length) {
          setColumns((current) =>
            PIPELINE_IDS.every((p) => current[p].status === 'idle' && current[p].log.length === 0)
              ? restoredColumns(data.graph.datasets)
              : current,
          )
        }
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
  const vertices = Math.max(...PIPELINE_IDS.map((p) => columns[p].counters.entities))
  const edges = Math.max(...PIPELINE_IDS.map((p) => columns[p].counters.relationships))
  const percents = Object.fromEntries(PIPELINE_IDS.map((p) => [p, percentComplete(p, columns[p])])) as Record<
    PipelineId,
    number
  >
  // Agentic GraphRAG waits on every stage, so its percent is the whole build's.
  const overall = percents.agentic_graphrag
  const restored = !running && PIPELINE_IDS.every((p) => columns[p].status === 'ready' && columns[p].log.length === 0)
  const loadedDatasets = corpora ? Object.entries(corpora.graph.datasets) : []

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
    running: `Building · ${overall}% · ${secs(elapsed)}`,
    complete: restored ? `Ready · ${loadedDatasets.length} dataset(s) loaded` : `Build complete: ${secs(elapsed)}`,
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
          <div className="dataset-picker">
            <label htmlFor="build-dataset" className="sr-only">Dataset</label>
            <select
              id="build-dataset"
              value={dataset}
              onChange={(e) => { setDataset(e.target.value); setConfirm(null) }}
              disabled={running}
              title='JSONL in data/corpus/, one {"doc_id", "title", "text", "url"} per line. A new dataset is added alongside those already loaded.'
            >
              {(corpora?.corpora ?? [{ name: dataset, documents: 0, size_bytes: 0, built: null }]).map((c) => (
                <option key={c.name} value={c.name}>
                  {c.name} — {num(c.documents)} docs{c.built ? ' · built' : ''}
                </option>
              ))}
            </select>
            <label className="dataset-upload" title="Add a JSONL dataset">
              Upload…
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
          <RequiresServices needs={['db', 'emb']}>
            <button type="button" className="btn-primary" onClick={() => run()} disabled={running || !!confirm}>
              <Icon name="restart" size={16} className={running ? 'spin' : undefined} />
              {running ? `Building… ${overall}%` : 'Start build'}
            </button>
          </RequiresServices>
          {loadedDatasets.length > 0 && (
            <span className="muted small">
              In graph: {loadedDatasets.map(([name, info]) => `${name} (${num(info.documents)} docs)`).join(', ')}
            </span>
          )}
        </div>
      </header>

      {uploadNote && (
        <Notice tone={uploadNote.ok ? 'ok' : 'error'} onClose={() => setUploadNote(null)}>{uploadNote.text}</Notice>
      )}
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

      {error && <Notice onClose={() => setError(null)}>{error}</Notice>}

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
          const pct = percents[pipeline]
          // 'done' means one stage finished and the next has not started yet.
          const active = column.status === 'running' || column.status === 'done'
          return (
            <section key={pipeline} className="pcard bcard" data-pipeline={pipeline} data-status={column.status}>
              <header className="pcard-head">
                <h3 className="bcard-title">
                  <Icon name={PIPELINE_ICONS[pipeline]} size={20} className="pipe-color" />
                  {PIPELINE_LABELS[pipeline]}
                </h3>
                <span className="bcard-status">
                  {active && <span className="pipe-color bcard-pct">{pct}%</span>}
                  <StatusBadge status={column.status} />
                </span>
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
                    {column.status === 'ready'
                      ? 'Answerable'
                      : `${titleCase(column.stage ?? 'waiting')}: ${num(column.itemsDone)} / ${num(column.itemsTotal)} items`}
                  </span>
                  <span className="pipe-color">{pct}% complete</span>
                </div>
                <div
                  className="progress"
                  role="progressbar"
                  aria-valuenow={pct}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label={`${PIPELINE_LABELS[pipeline]} build progress`}
                >
                  <div className="progress-bar" style={{ width: `${pct}%` }} />
                </div>

                <div className="stat-grid three">
                  <Stat
                    label={column.status === 'ready' ? 'Time to ready' : 'Elapsed'}
                    value={ms(column.elapsedMs)}
                    tone={active ? 'pipe-color' : undefined}
                  />
                  {PIPELINE_METRICS[pipeline].map(([label, key]) => (
                    <Stat key={key} label={label} value={num(column.counters[key])} />
                  ))}
                </div>

                <p className="token-row">
                  <Icon name="chip" size={15} className="pipe-color" />
                  {pipeline === 'graphrag'
                    ? 'Graph only — no embeddings, no LLM calls'
                    : `Embedding model: ${column.embedding ?? '@cf/baai/bge-m3'} — no LLM calls`}
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
                <span className="stat-label">Graph entities</span>
                <span className="density-value">{num(vertices)}</span>
              </div>
            </div>
            <div className="density-card">
              <span className="icon-box gain lg">
                <Icon name="share" size={22} />
              </span>
              <div>
                <span className="stat-label">Relationships</span>
                <span className="density-value">{num(edges)}</span>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}
