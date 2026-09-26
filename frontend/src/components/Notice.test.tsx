import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { Notice } from './Notice'

describe('Notice', () => {
  it('shows a close button that dismisses the message', () => {
    const onClose = vi.fn()
    render(<Notice onClose={onClose}>TigerGraph unreachable</Notice>)
    expect(screen.getByRole('alert')).toHaveTextContent('TigerGraph unreachable')
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss message' }))
    expect(onClose).toHaveBeenCalledOnce()
  })
})
