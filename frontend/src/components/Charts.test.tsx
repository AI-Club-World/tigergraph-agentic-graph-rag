import { render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ScatterPlot } from './Charts'

afterEach(() => vi.restoreAllMocks())

function xTickLabels(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll('text.tick'))
    .filter((t) => t.getAttribute('text-anchor') === 'middle')
    .map((t) => t.textContent ?? '')
}

describe('ScatterPlot x ticks', () => {
  it('stay distinct for small maxima, with no duplicate-key warning', () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {})
    const { container } = render(
      <ScatterPlot
        series={[{ name: 'rag', color: 'red', points: [{ x: 120, y: 0.5, label: 'q1' }] }]}
        xLabel="tokens"
        yLabel="F1"
      />,
    )
    const labels = xTickLabels(container)
    expect(new Set(labels).size).toBe(labels.length)
    expect(labels.length).toBeGreaterThan(2)
    expect(error.mock.calls.flat().join(' ')).not.toMatch(/same key/)
  })

  it('round to hundreds for larger maxima', () => {
    const { container } = render(
      <ScatterPlot
        series={[{ name: 'rag', color: 'red', points: [{ x: 4000, y: 0.5, label: 'q1' }] }]}
        xLabel="tokens"
        yLabel="F1"
      />,
    )
    expect(xTickLabels(container)).toEqual(['0', '1,100', '2,100', '3,200', '4,200'])
  })
})
