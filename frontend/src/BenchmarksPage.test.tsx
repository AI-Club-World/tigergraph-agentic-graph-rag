import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { BenchmarksPage } from './BenchmarksPage'

describe('BenchmarksPage', () => {
  it('opens on the dashboard and switches to the run-benchmark tab', async () => {
    await act(async () => {
      render(
        <MemoryRouter initialEntries={['/benchmarks']}>
          <BenchmarksPage />
        </MemoryRouter>,
      )
    })
    expect(screen.getByRole('tab', { name: 'Dashboard' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('heading', { name: 'Benchmark dashboard' })).toBeInTheDocument()

    await act(async () => {
      fireEvent.click(screen.getByRole('tab', { name: 'Run benchmark' }))
    })
    expect(screen.getByRole('tab', { name: 'Run benchmark' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('heading', { name: 'Runs & history' })).toBeInTheDocument()
  })
})
