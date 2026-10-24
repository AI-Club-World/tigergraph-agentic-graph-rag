import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ResultColumn } from './ResultColumn'
import type { PipelineRecord } from '../types'

function record(extra: Partial<PipelineRecord> = {}): PipelineRecord {
  return {
    pipeline: 'agentic_graphrag',
    answer: 'Runner B',
    explanation: 'Resolved.',
    citations: [],
    chunks_returned: 2,
    citations_count: 2,
    tokens: { input: 100, output: 20, total: 120 },
    token_source: 'provider',
    latency_ms: 900,
    trace: [],
    strategy_changed: false,
    stop_reason: 'conflict_resolved',
    status: 'done',
    error_detail: null,
    ...extra,
  }
}

describe('ResultColumn — Round 2', () => {
  it('shows the confidence, the time scope and the values weighed', () => {
    render(
      <ResultColumn
        pipeline="agentic_graphrag"
        state={{
          status: 'done',
          error: null,
          record: record({
            confidence: 0.87,
            temporal_scope: { mode: 'as_of', t1: '2015-12-31', t2: null, cue: 'as of 2015', ambiguous: false },
            conflicts: [
              {
                subject: 'Men’s 800 m',
                predicate: 'gold',
                chosen: {
                  value: 'Runner B', score: 2, probability: 0.9, support: 0.95,
                  sources: ['src:results-office'], observed_at: ['2018-05-07'], doc_ids: ['D2'],
                },
                alternatives: [
                  { value: 'Runner C', score: 1, probability: 0.1, support: 0.3, sources: ['src:fan-zone'], observed_at: [], doc_ids: ['D3'] },
                ],
                superseded: [{ value: 'Runner A', source: 'src:wikipedia.org', observed_at: null, doc_id: 'D1' }],
                confidence: 0.87,
              },
            ],
          }),
        }}
      />,
    )
    expect(screen.getByText('0.87')).toBeInTheDocument()
    expect(screen.getByText('as of 2015-12-31')).toBeInTheDocument()
    const weighed = screen.getByLabelText('Conflicting values')
    expect(weighed).toHaveTextContent('Runner B chosen · p 0.90')
    expect(weighed).toHaveTextContent('Runner C · p 0.10 · src:fan-zone')
    expect(weighed).toHaveTextContent('Runner A · superseded · src:wikipedia.org')
  })

  it('shows nothing extra for a Round-1 record', () => {
    render(<ResultColumn pipeline="agentic_graphrag" state={{ status: 'done', error: null, record: record({ stop_reason: 'direct_route' }) }} />)
    expect(screen.queryByText(/Confidence/)).toBeNull()
    expect(screen.queryByLabelText('Conflicting values')).toBeNull()
  })
})
