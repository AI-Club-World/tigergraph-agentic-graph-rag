import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { EmbeddingMismatchDialog } from './EmbeddingMismatchDialog'
import { ErrorBoundary } from './ErrorBoundary'

const mismatch = {
  message: 'No embeddings.',
  selected: { key: 'q', label: 'Qwen3', state: 'not_stored', chunks_done: 0, chunks_total: 1 },
  available: [{ key: 'b', label: 'bge', dim: 1024 }],
}

describe('modal dialogs', () => {
  it('move focus inside, keep Tab inside and close on Escape', () => {
    const onCancel = vi.fn()
    render(
      <>
        <button type="button">outside</button>
        <EmbeddingMismatchDialog mismatch={mismatch} onPick={vi.fn()} onCancel={onCancel} />
      </>,
    )
    const [use, cancel] = [screen.getByRole('button', { name: /Use bge/ }), screen.getByRole('button', { name: 'Cancel query' })]
    expect(document.activeElement).toBe(use)
    cancel.focus()
    fireEvent.keyDown(cancel, { key: 'Tab' })
    expect(document.activeElement).toBe(use)
    fireEvent.keyDown(use, { key: 'Escape' })
    expect(onCancel).toHaveBeenCalled()
  })
})

describe('ErrorBoundary', () => {
  it('shows a screen that failed to render instead of blanking the app', () => {
    const Broken = () => {
      throw new Error('boom')
    }
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    render(<ErrorBoundary><Broken /></ErrorBoundary>)
    expect(screen.getByRole('alert')).toHaveTextContent('This screen could not be shown: boom')
  })
})
