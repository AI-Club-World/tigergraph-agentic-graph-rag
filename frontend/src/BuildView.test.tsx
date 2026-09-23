import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BuildView } from './BuildView'
import type { BuildEvent, PipelineId } from './types'
import * as buildService from './services/buildService'

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
  return within(col).getByText(label).previousElementSibling?.textContent ?? ''
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
  mocked.startBuild.mockResolvedValue({ build_id: 'b1', stream_token: 't1' })
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

  it('keeps ready sticky and keeps the previous stage on the ready event', async () => {
    await start()
    await emit(event({ stage: 'embed_chunks', items_done: 10 }))
    await emit(event({ stage: 'pipeline_ready', status: 'ready', items_done: 1, items_total: 1 }))

    const rag = column('rag')
    expect(rag.dataset.status).toBe('ready')
    expect(within(rag).getByText('Ready')).toBeInTheDocument()
    expect(within(rag).getByText('Embed Chunks')).toBeInTheDocument()

    // A later non-ready event updates the stage but cannot demote the column.
    await emit(event({ stage: 'vector_index', status: 'running', items_done: 2, items_total: 5 }))
    expect(column('rag').dataset.status).toBe('ready')
    expect(within(column('rag')).getByText('Vector Index')).toBeInTheDocument()

    await emit(event({ stage: 'vector_index', status: 'error', items_done: 2, items_total: 5 }))
    expect(column('rag').dataset.status).toBe('ready')
  })

  it('advances counters with max() while progress is overwritten', async () => {
    await start()
    await emit(event({ stage: 'parse_infoboxes', items_done: 50, items_total: 100 }))
    await emit(event({ stage: 'parse_infoboxes', items_done: 30, items_total: 100 }))

    const rag = column('rag')
    expect(metric(rag, 'documents')).toBe('50')
    expect(within(rag).getByText('30 / 100 items')).toBeInTheDocument()

    // chunk_documents and embed_chunks share the chunks counter.
    await emit(event({ stage: 'chunk_documents', items_done: 800, items_total: 800 }))
    await emit(event({ stage: 'embed_chunks', items_done: 200, items_total: 800 }))
    expect(metric(column('rag'), 'chunks')).toBe('800')

    // A stage outside the map owns no counter.
    await emit(event({ stage: 'vector_index', items_done: 9999, items_total: 9999 }))
    expect(metric(column('rag'), 'documents')).toBe('50')
    expect(metric(column('rag'), 'chunks')).toBe('800')
    expect(metric(column('rag'), 'vertices')).toBe('0')
    expect(metric(column('rag'), 'edges')).toBe('0')
  })

  it('accumulates tokens and logs every event', async () => {
    await start()
    await emit(event({ tokens: 3 }))
    await emit(event({ tokens: 4 }))
    await emit(event({ stage: 'pipeline_ready', status: 'ready', tokens: 5 }))

    const rag = column('rag')
    expect(within(rag).getByText('LLM tokens: 12 (local embedding model)')).toBeInTheDocument()
    expect(within(rag).getByText('3 stage events')).toBeInTheDocument()
  })
})
