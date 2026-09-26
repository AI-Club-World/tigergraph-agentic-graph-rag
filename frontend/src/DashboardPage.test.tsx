import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { DashboardPage } from './DashboardPage'

describe('DashboardPage', () => {
  it('opens on the dashboard and switches to run-benchmark and eval tabs', async () => {
    await act(async () => {
      render(
        <MemoryRouter initialEntries={['/dashboard']}>
          <DashboardPage />
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

    await act(async () => {
      fireEvent.click(screen.getByRole('tab', { name: 'Eval table' }))
    })
    expect(screen.getByRole('heading', { name: 'Per-question results' })).toBeInTheDocument()
  })
})
