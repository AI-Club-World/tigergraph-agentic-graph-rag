import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { CitationList } from './CitationList'

describe('CitationList', () => {
  it('shows a citation’s evidence text when its chip is selected, and hides it again', () => {
    render(
      <CitationList
        citations={[
          { source_id: 'Q1', chunk_id: null, ref_type: 'entity', snippet: 'event_name: Shot put; gold: Valerie Vili' },
          { source_id: 'Q2', chunk_id: 'Q2_c0', ref_type: 'chunk', snippet: null },
        ]}
      />,
    )
    expect(screen.queryByText(/Valerie Vili/)).toBeNull()
    const chip = screen.getByRole('button', { name: /Q1/ })
    fireEvent.click(chip)
    expect(chip.getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByText(/gold: Valerie Vili/)).toBeTruthy()
    fireEvent.click(chip)
    expect(screen.queryByText(/Valerie Vili/)).toBeNull()
    // No evidence text: a plain chip, not a toggle.
    expect(screen.queryByRole('button', { name: /Q2/ })).toBeNull()
    expect(screen.getByText('Q2')).toBeTruthy()
  })

  it('says so when there are no citations', () => {
    render(<CitationList citations={[]} />)
    expect(screen.getByText('No citations returned.')).toBeTruthy()
  })
})
