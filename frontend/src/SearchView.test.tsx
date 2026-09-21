import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { SearchView } from './SearchView'
import type { PipelineId, PipelineRecord, TraceStep } from './types'
import * as queryService from './services/queryService'

vi.mock('./services/queryService')

const mocked = vi.mocked(queryService)

let handlers: queryService.QueryStreamHandlers

function pipelineRecord(pipeline: PipelineId, answer: string): PipelineRecord {
  return {
    pipeline,
    answer,
    explanation: 'Explanation.',
    citations: [{ source_id: 'Q1', chunk_id: null, ref_type: 'entity' }],
    chunks_returned: 0,
    citations_count: 1,
    tokens: { input: 100, output: 20, total: 120 },
    token_source: 'provider',
    latency_ms: 900,
    trace: null,
    strategy_changed: null,
    stop_reason: null,
    status: 'done',
    error_detail: null,
  }
}

function traceStep(step_n: number, notes: string): TraceStep {
  return {
    step_n,
    agent_type: 'entity_linking',
    tool_called: 'intent_parser',
    tokens: { input: 10, output: 5 },
    chunks_returned: 0,
    citations_count: 0,
    latency_ms: 100,
    strategy_change: false,
    notes,
  }
}

async function submit() {
  render(
    <MemoryRouter>
      <SearchView />
    </MemoryRouter>,
  )
  fireEvent.change(screen.getByLabelText('Query'), { target: { value: 'who won gold in Rio?' } })
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Compare' }))
  })
}

beforeEach(() => {
  vi.resetAllMocks()
  mocked.submitQuery.mockResolvedValue({ query_id: 'q1', stream_token: 't1' })
  mocked.openQueryStream.mockImplementation((_accepted, h) => {
    handlers = h
    return () => undefined
  })
})

describe('SearchView', () => {
  it('renders columns independently — one done while the others are still running', async () => {
    await submit()

    // All three start running.
    await waitFor(() => expect(screen.getAllByText('Running')).toHaveLength(3))

    // Only RAG completes.
    await act(async () => {
      handlers.onPipeline(pipelineRecord('rag', 'Usain Bolt'))
    })

    const rag = document.querySelector('[data-pipeline="rag"]') as HTMLElement
    const graphrag = document.querySelector('[data-pipeline="graphrag"]') as HTMLElement
    const agentic = document.querySelector('[data-pipeline="agentic_graphrag"]') as HTMLElement

    expect(rag.dataset.status).toBe('done')
    expect(within(rag).getByText('Usain Bolt')).toBeInTheDocument()
    expect(graphrag.dataset.status).toBe('running')
    expect(agentic.dataset.status).toBe('running')

    // The verdict strip waits for all three.
    expect(screen.getByText(/verdict strip renders once all three/i)).toBeInTheDocument()
  })

  it('appends each trace step as its SSE event arrives', async () => {
    await submit()

    expect(screen.getByText('0 steps')).toBeInTheDocument()

    await act(async () => {
      handlers.onTrace(traceStep(1, 'Parsed intent'))
    })
    expect(screen.getByText('Parsed intent')).toBeInTheDocument()
    expect(screen.getByText('1 steps')).toBeInTheDocument()

    await act(async () => {
      handlers.onTrace(traceStep(2, 'Traversed PREV_EDITION'))
    })
    expect(screen.getByText('Parsed intent')).toBeInTheDocument()
    expect(screen.getByText('Traversed PREV_EDITION')).toBeInTheDocument()
    expect(screen.getByText('2 steps')).toBeInTheDocument()
  })
})
