import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { StrictMode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BuildView } from './BuildView'
import type { BuildEvent, PipelineId } from './types'
import * as buildService from './services/buildService'
import * as datasetService from './services/datasetService'
import { datasetLabel } from './services/datasetService'
import { STALE_BACKEND } from './services/http'

vi.mock('./services/buildService')

const mocked = vi.mocked(buildService)

let handlers: buildService.BuildStreamHandlers

function event(overrides: Partial<BuildEvent>): BuildEvent {
  return {
    stage: 'parse_infoboxes',
    pipeline_affected: ['rag'],
    status: 'running',
    items_done: 0,
    items_total: 100,
    elapsed_ms: 0,
    tokens: 0,
    note: 'note',
    ...overrides,
  }
}

const pipelineHeading: Record<PipelineId, string> = {
  rag: 'RAG',
  graphrag: 'GraphRAG',
  agentic_graphrag: 'Agentic GraphRAG',
}

function column(pipeline: PipelineId): HTMLElement {
  return screen.getByRole('heading', { name: pipelineHeading[pipeline] }).closest('section') as HTMLElement
}

function metric(col: HTMLElement, label: string): string {
  return within(col).getByText(label).nextElementSibling?.textContent ?? ''
}

async function start() {
  render(<BuildView />)
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Start build' }))
  })
}

async function emit(e: BuildEvent) {
  await act(async () => {
    handlers.onEvent(e)
  })
}

beforeEach(() => {
  vi.resetAllMocks()
  mocked.startBuild.mockResolvedValue({ build_id: 'b1' })
  mocked.openBuildStream.mockImplementation((_accepted, h) => {
    handlers = h
    return () => undefined
  })
})

describe('BuildView reducer', () => {
  it('applies an event only to the pipelines it affects', async () => {
    await start()
    await emit(event({ items_done: 40, pipeline_affected: ['rag'] }))

    expect(column('rag').dataset.status).toBe('running')
    expect(within(column('rag')).getByText('Parse Infoboxes')).toBeInTheDocument()
    expect(column('graphrag').dataset.status).toBe('idle')
    expect(within(column('graphrag')).getByText('Not started')).toBeInTheDocument()
  })

  it('keeps ready sticky and shows Ready as the final stage', async () => {
    await start()
    await emit(event({ stage: 'embed_chunks', items_done: 10 }))
    await emit(event({ stage: 'pipeline_ready', status: 'ready', items_done: 1, items_total: 1 }))

    const rag = column('rag')
    expect(rag.dataset.status).toBe('ready')
    expect(within(rag).getAllByText('Ready').length).toBeGreaterThan(0)
    expect(within(rag).queryByText('Embed Chunks')).toBeNull()

    // A later event cannot demote the column or bring back a stage name.
    await emit(event({ stage: 'vector_index', status: 'error', items_done: 2, items_total: 5 }))
    expect(column('rag').dataset.status).toBe('ready')
    expect(within(column('rag')).queryByText('Vector Index')).toBeNull()
  })

  it('shows each pipeline only its own data', async () => {
    await start()
    await emit(event({ stage: 'parse_infoboxes', items_done: 50, items_total: 100, pipeline_affected: ['graphrag', 'agentic_graphrag'] }))
    await emit(event({ stage: 'chunk_documents', items_done: 800, items_total: 800, status: 'done', pipeline_affected: ['rag', 'agentic_graphrag'] }))
    await emit(event({ stage: 'embed_chunks', items_done: 800, items_total: 800, status: 'done', pipeline_affected: ['rag', 'agentic_graphrag'] }))
    await emit(event({ stage: 'load_vertices', items_done: 120, items_total: 0, status: 'done', pipeline_affected: ['graphrag', 'agentic_graphrag'] }))
    await emit(event({ stage: 'load_edges', items_done: 300, items_total: 0, status: 'done', pipeline_affected: ['graphrag', 'agentic_graphrag'] }))

    const rag = column('rag')
    expect(metric(rag, 'Chunks')).toBe('800')
    expect(metric(rag, 'Vectors')).toBe('800')
    expect(within(rag).queryByText('Entities')).toBeNull()

    const graph = column('graphrag')
    expect(metric(graph, 'Documents')).toBe('50')
    expect(metric(graph, 'Entities')).toBe('120')
    expect(metric(graph, 'Relationships')).toBe('300')
    expect(within(graph).queryByText('Vectors')).toBeNull()

    const agentic = column('agentic_graphrag')
    expect(metric(agentic, 'Entities')).toBe('120')
    expect(metric(agentic, 'Vectors')).toBe('800')
  })

  it('reports percent complete, weighted by stage', async () => {
    await start()
    await emit(event({ stage: 'chunk_documents', status: 'done', items_done: 10, items_total: 10, pipeline_affected: ['rag'] }))
    await emit(event({ stage: 'embed_chunks', status: 'running', items_done: 5, items_total: 10, pipeline_affected: ['rag'] }))
    // rag stages weigh 75 (remove_previous excluded); done 5 + 40 * 0.5 = 25 -> 33%
    expect(within(column('rag')).getByText('33% complete')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Building… \d+%/ })).toBeInTheDocument()
  })

  it('says building uses the embedding model, not an LLM', async () => {
    await start()
    await emit(event({ stage: 'embed_chunks', status: 'done', note: '@cf/baai/bge-m3 via cloudflare' }))
    expect(within(column('rag')).getByText('Embedding model: @cf/baai/bge-m3 via cloudflare — no LLM calls')).toBeInTheDocument()
    expect(within(column('graphrag')).getByText('Graph only — no embeddings, no LLM calls')).toBeInTheDocument()
    expect(within(column('rag')).getByText('1 stage events')).toBeInTheDocument()
  })
})

describe('BuildView dataset confirmation', () => {
  it('asks to rebuild or cancel when the dataset is already built', async () => {
    const { ApiError } = await import('./services/http')
    mocked.startBuild.mockRejectedValueOnce(
      new ApiError("Dataset 'corpus' was already built. Rebuild it or cancel.", 409, 'already_built'),
    )
    await start()
    expect(screen.getByRole('alertdialog')).toHaveTextContent('already built')

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Rebuild Wikipedia · Olympics · 1900–2022' }))
    })
    expect(mocked.startBuild).toHaveBeenLastCalledWith('corpus', { rebuild: true })
    expect(screen.queryByRole('alertdialog')).toBeNull()
  })

  it('cancel keeps the existing data and starts nothing', async () => {
    const { ApiError } = await import('./services/http')
    mocked.startBuild.mockRejectedValueOnce(new ApiError('already built', 409, 'already_built'))
    await start()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(mocked.startBuild).toHaveBeenCalledTimes(1)
  })
})

describe('BuildView dataset names', () => {
  it('shows the dataset by its name, not its file', async () => {
    render(<BuildView />)
    const option = await screen.findByRole('option', { name: /^Wikipedia · Olympics · 1900–2022 — 2,951 docs/ })
    expect((option as HTMLOptionElement).value).toBe('corpus')
    expect(screen.getByRole('button', { name: 'Rename' })).toBeInTheDocument()
  })

  it('asks for a name before uploading', async () => {
    const { container } = render(<BuildView />)
    const input = container.querySelector('input[type=file]') as HTMLInputElement
    fireEvent.change(input, { target: { files: [new File(['{}'], 'corpus.jsonl')] } })
    const form = screen.getByRole('form', { name: 'Name the new dataset' })
    expect(form).toHaveTextContent('corpus.jsonl')
    expect(within(form).getByPlaceholderText('Leave empty to infer a name from its documents')).toBeInTheDocument()
  })

  it('tells apart datasets that share a name', () => {
    const all = [{ name: 'corpus', title: 'Olympics' }, { name: 'corpus-2', title: 'Olympics' }, { name: 'films', title: 'Films' }]
    expect(datasetLabel(all[0], all)).toBe('Olympics (corpus)')
    expect(datasetLabel(all[1], all)).toBe('Olympics (corpus-2)')
    expect(datasetLabel(all[2], all)).toBe('Films')
    expect(datasetLabel({ name: 'legacy' }, all)).toBe('legacy')
  })
})

describe('BuildView after navigating back', () => {
  it('follows a build still running on the server, under StrictMode too', async () => {
    mocked.getCurrentBuild.mockResolvedValue({
      build_id: 'b9',
      dataset: 'corpus',
      running: true,
      events: [event({ stage: 'embed_chunks', items_done: 30, pipeline_affected: ['rag'] })],
    })
    await act(async () => {
      render(
        <StrictMode>
          <BuildView />
        </StrictMode>,
      )
    })
    expect(await screen.findByText('JOB-ID: b9')).toBeInTheDocument()
    expect(column('rag').dataset.status).toBe('running')
  })

  it('shows what TigerGraph holds when this install recorded no dataset', async () => {
    mocked.getCurrentBuild.mockResolvedValue(null)
    vi.spyOn(datasetService, 'listCorpora').mockResolvedValue({
      corpora: [],
      graph: {
        tracked: false,
        schema: null,
        datasets: {},
        live: { documents: 2951, events: 2187, chunks: 16669, games: 21, sports: 42, venues: 319 },
      },
    })
    await act(async () => {
      render(<BuildView />)
    })
    expect(await screen.findByText(/In TigerGraph: 2,951 documents/)).toBeInTheDocument()
    expect(column('agentic_graphrag').dataset.status).toBe('ready')
  })
})

describe('BuildView when the datasets cannot be read', () => {
  it('says why instead of showing an empty dataset list', async () => {
    mocked.getCurrentBuild.mockResolvedValue(null)
    vi.spyOn(datasetService, 'listCorpora').mockRejectedValue(new Error(STALE_BACKEND))
    await act(async () => {
      render(<BuildView />)
    })
    expect(await screen.findByText(/older version that still asks for a sign-in/)).toBeInTheDocument()
  })
})
