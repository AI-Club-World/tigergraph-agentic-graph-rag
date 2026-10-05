import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { HistoryView } from './HistoryView'
import * as historyService from './services/historyService'

vi.mock('./services/historyService')
const mocked = vi.mocked(historyService)

beforeEach(() => {
  mocked.getHistory.mockResolvedValue([
    { id: '1', at: '2026-09-26T10:00:00Z', kind: 'build', status: 'needs_confirmation', subject: 'corpus',
      error: 'already built', llm_provider: 'groq', llm_model: 'm' },
    { id: '2', at: '2026-09-26T09:00:00Z', kind: 'query', status: 'done', subject: 'How many sailing events?',
      duration_ms: 1500, tokens: 120, llm_provider: 'groq', llm_model: 'm' },
  ])
})

describe('HistoryView', () => {
  it('lists every attempt and filters by type and text', async () => {
    await act(async () => {
      render(<HistoryView />)
    })
    expect(screen.getByText('How many sailing events?')).toBeInTheDocument()
    expect(screen.getByText('already built')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Type'), { target: { value: 'build' } })
    expect(screen.queryByText('How many sailing events?')).toBeNull()

    fireEvent.change(screen.getByLabelText('Type'), { target: { value: 'all' } })
    fireEvent.change(screen.getByLabelText('Search history'), { target: { value: 'sailing' } })
    expect(screen.getByText('How many sailing events?')).toBeInTheDocument()
    expect(screen.queryByText('already built')).toBeNull()
  })
})
