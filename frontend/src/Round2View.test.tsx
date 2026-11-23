import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { Round2View } from './Round2View'
import { ApiError } from './services/http'
import * as r2Service from './services/r2Service'
import type { R2Answer } from './types'

vi.mock('./services/r2Service')
const mocked = vi.mocked(r2Service)

function record(over: Partial<R2Answer> = {}): R2Answer {
  return {
    qid: 'live-1',
    status: 'answered',
    answer: 'Ann Alpha',
    explanation: 'Won both finals.',
    citations: ['E1', 'E2'],
    input_tokens: 300,
    output_tokens: 30,
    latency_ms: 1500,
    graph_backend: 'tigergraph',
    trace: [
      { step: 1, tool: 'plan', tigergraph: false, input_tokens: 100, output_tokens: 10, ms: 400, note: 'thinking' },
      { step: 2, tool: 'find_events', tigergraph: true, query: 'r2_find_events', params: { sport: 'X' }, rows: 7, ms: 55 },
      { step: 3, tool: 'llm_step', tigergraph: false, input_tokens: 200, output_tokens: 20, ms: 900 },
    ],
    ...over,
  }
}

async function ask(result: R2Answer | Error) {
  if (result instanceof Error) mocked.askRound2.mockRejectedValue(result)
  else mocked.askRound2.mockResolvedValue(result)
  render(
    <MemoryRouter>
      <Round2View />
    </MemoryRouter>,
  )
  fireEvent.change(screen.getByLabelText('Question'), { target: { value: 'anything' } })
  fireEvent.click(screen.getByRole('button', { name: 'Ask' }))
}

beforeEach(() => vi.resetAllMocks())

describe('Round2View', () => {
  it.each([
    ['answered', 'Answered'],
    ['partial', 'Partial'],
    ['not_in_corpus', 'Not in corpus'],
  ] as const)('renders the %s status', async (status, label) => {
    await ask(record({ status, answer: status === 'not_in_corpus' ? null : 'x' }))
    const badge = await screen.findByText(label)
    expect(badge.closest('.r2-status')).toHaveClass(`r2-status-${status}`)
    if (status === 'not_in_corpus') expect(screen.getByText('No answer returned.')).toBeInTheDocument()
  })

  it('shows loading while the agent works', async () => {
    mocked.askRound2.mockReturnValue(new Promise(() => undefined))
    render(
      <MemoryRouter>
        <Round2View />
      </MemoryRouter>,
    )
    fireEvent.change(screen.getByLabelText('Question'), { target: { value: 'q' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))
    expect(await screen.findByText(/querying the graph/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Working…' })).toBeDisabled()
  })

  it('renders a list of objects as a table', async () => {
    await ask(record({ answer: [{ nation: 'USA', golds: 3 }, { nation: 'KEN', golds: 2 }] }))
    const table = await screen.findByRole('table')
    expect(within(table).getByRole('columnheader', { name: 'nation' })).toBeInTheDocument()
    expect(within(table).getAllByRole('row')).toHaveLength(3)
    expect(within(table).getByText('KEN')).toBeInTheDocument()
  })

  it('renders other JSON as formatted pre and shows citations and totals', async () => {
    await ask(record({ answer: { winner: 'Ann' } }))
    const pre = await screen.findByText(/"winner": "Ann"/)
    expect(pre.tagName).toBe('PRE')
    const cites = within(screen.getByRole('list', { name: 'Citations' }))
    expect(cites.getByText('E1')).toBeInTheDocument()
    expect(cites.getByText('E2')).toBeInTheDocument()
    expect(screen.getByText('LLM calls').nextSibling).toHaveTextContent('2')
    expect(screen.getByText('TigerGraph queries').nextSibling).toHaveTextContent('1')
    expect(screen.getByText('Tokens in').nextSibling).toHaveTextContent('300')
  })

  it('renders the trace in order with TigerGraph tags', async () => {
    await ask(record())
    const steps = within(await screen.findByRole('list', { name: 'Agent trace' })).getAllByRole('listitem')
    expect(steps).toHaveLength(3)
    expect(within(steps[0]).queryByText('TigerGraph')).toBeNull()
    expect(within(steps[1]).getByText('TigerGraph')).toBeInTheDocument()
    expect(within(steps[1]).getByText('r2_find_events')).toBeInTheDocument()
    expect(within(steps[1]).getByText('{"sport":"X"}')).toBeInTheDocument()
    expect(within(steps[1]).getByText('7 rows')).toBeInTheDocument()
    expect(within(steps[1]).getByText('55 ms')).toBeInTheDocument()
    expect(within(steps[0]).getByText('thinking')).toBeInTheDocument()
    expect(within(steps[0]).getByText('110 tokens')).toBeInTheDocument()
  })

  it('shows an error and no answer when the call fails', async () => {
    await ask(new ApiError('TigerGraph could not be reached', 503))
    expect(await screen.findByRole('alert')).toHaveTextContent('TigerGraph could not be reached')
    await waitFor(() => expect(screen.queryByLabelText('Answer')).toBeNull())
    expect(screen.getByRole('button', { name: 'Ask' })).toBeEnabled()
  })
})
