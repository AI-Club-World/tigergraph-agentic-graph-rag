import { render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { Dashboard } from './Dashboard'
import type { BatchRecord, PipelineId, PipelineRecord, PipelineScores, QType } from './types'
import * as batchService from './services/batchService'

vi.mock('./services/batchService')

const mocked = vi.mocked(batchService)

function pipelineRecord(pipeline: PipelineId, total: number): PipelineRecord {
  return {
    pipeline,
    answer: 'answer',
    explanation: 'Explanation.',
    citations: [],
    chunks_returned: 0,
    citations_count: 0,
    tokens: { input: total, output: 0, total },
    token_source: 'provider',
    latency_ms: 100,
    trace: pipeline === 'agentic_graphrag' ? [] : null,
    strategy_changed: pipeline === 'agentic_graphrag' ? false : null,
    stop_reason: pipeline === 'agentic_graphrag' ? 'answer_found' : null,
    status: 'done',
    error_detail: null,
  }
}

function scores(em: number): PipelineScores {
  return { em, f1: em, precision: em, recall: em, completeness: em }
}

/** One scored record with the given EMs and token totals for RAG and Agentic. */
function record(
  qid: string,
  qtype: QType,
  em: { rag: number; agentic: number },
  tokens: { rag: number; agentic: number },
  scored = true,
): BatchRecord {
  return {
    run_id: 'test',
    qid,
    question: `Question ${qid}?`,
    qtype,
    ground_truth: scored ? ['answer'] : [],
    gold_doc_ids: scored ? ['Q1'] : [],
    record: {
      query_id: qid,
      query_text: `Question ${qid}?`,
      qtype,
      timestamp: '2026-01-01T00:00:00Z',
      pipelines: {
        rag: pipelineRecord('rag', tokens.rag),
        graphrag: pipelineRecord('graphrag', 1000),
        agentic_graphrag: pipelineRecord('agentic_graphrag', tokens.agentic),
      },
      verdict: {
        token_multiplier_vs_rag: 1,
        token_multiplier_vs_graphrag: 1,
        accuracy_delta_vs_rag: 0,
        accuracy_delta_vs_graphrag: 0,
        summary_line: 'Summary.',
      },
    },
    scores: scored
      ? { rag: scores(em.rag), graphrag: scores(0), agentic_graphrag: scores(em.agentic) }
      : null,
  }
}

function renderDashboard(runId = 'test') {
  render(
    <MemoryRouter initialEntries={[`/dashboard?run=${runId}`]}>
      <Dashboard />
    </MemoryRouter>,
  )
}

/** The worth-it table's cells for one question type: [n, gap, multiplier, verdict]. */
async function worthItRow(label: string): Promise<string[]> {
  const header = await screen.findByRole('rowheader', { name: label })
  const row = header.closest('tr') as HTMLElement
  return within(row)
    .getAllByRole('cell')
    .map((cell) => cell.textContent ?? '')
}

beforeEach(() => {
  vi.resetAllMocks()
})

describe('Dashboard worth-it table', () => {
  it('uses the mean of per-question ratios, not the ratio of means', async () => {
    mocked.getBatchRecords.mockResolvedValue([
      // ratios 3.0 and 0.5 -> mean 1.75 (ratio of means would be 400 / 300 = 1.33)
      record('a', 'lookup', { rag: 0, agentic: 1 }, { rag: 100, agentic: 300 }),
      record('b', 'lookup', { rag: 0, agentic: 1 }, { rag: 200, agentic: 100 }),
    ])
    renderDashboard()

    expect(await worthItRow('Lookup')).toEqual(['2', '+1.00', '1.75×', 'Worth it'])
  })

  it('applies the 0.5 / 0.05 verdict thresholds inclusively', async () => {
    mocked.getBatchRecords.mockResolvedValue([
      record('t', 'temporal', { rag: 0, agentic: 0.5 }, { rag: 100, agentic: 100 }),
      record('m', 'multi_hop', { rag: 0, agentic: 0.05 }, { rag: 100, agentic: 100 }),
      record('g', 'aggregation', { rag: 0, agentic: 0.49 }, { rag: 100, agentic: 100 }),
      record('l', 'lookup', { rag: 1, agentic: 0 }, { rag: 100, agentic: 100 }),
    ])
    renderDashboard()

    expect((await worthItRow('Temporal'))[3]).toBe('Worth it')
    expect((await worthItRow('Multi Hop'))[3]).toBe('Overkill')
    expect((await worthItRow('Aggregation'))[3]).toBe('Marginal')
    expect(await worthItRow('Lookup')).toEqual(['1', '-1.00', '1.00×', 'Overkill'])
    // All five qtypes are listed, even at n = 0 — with no verdict, since there is no data.
    expect(await worthItRow('Superlative')).toEqual(['0', 'No questions of this type in the run'])
  })

  it('leaves zero-RAG-token questions out of the token ratio mean', async () => {
    mocked.getBatchRecords.mockResolvedValue([
      record('a', 'aggregation', { rag: 0, agentic: 1 }, { rag: 0, agentic: 500 }),
      record('b', 'aggregation', { rag: 0, agentic: 1 }, { rag: 100, agentic: 250 }),
      record('c', 'multi_hop', { rag: 0, agentic: 1 }, { rag: 0, agentic: 0 }),
    ])
    renderDashboard()

    expect((await worthItRow('Aggregation'))[2]).toBe('2.50×')
    expect((await worthItRow('Multi Hop'))[2]).toBe('0.00×')
    expect(screen.queryByText(/Infinity|NaN/)).not.toBeInTheDocument()
  })

  it('explains a run without ground truth using the spec literal', async () => {
    mocked.getBatchRecords.mockResolvedValue([
      record('a', 'lookup', { rag: 0, agentic: 0 }, { rag: 100, agentic: 100 }, false),
    ])
    renderDashboard('hidden')

    expect(
      await screen.findByText(
        'Run "hidden" carries no ground truth, so no accuracy metrics can be shown. Token, latency and trace aggregations below still apply.',
      ),
    ).toBeInTheDocument()
    expect(screen.queryByText('Is the agent worth it, per question type?')).not.toBeInTheDocument()
  })
})

describe('Dashboard without ground truth', () => {
  it('still compares cost, latency and errors across the three pipelines', async () => {
    const hidden = record('h1', 'lookup', { rag: 0, agentic: 0 }, { rag: 100, agentic: 900 }, false)
    const failed = record('h2', 'lookup', { rag: 0, agentic: 0 }, { rag: 100, agentic: 0 }, false)
    failed.record.pipelines.agentic_graphrag = {
      ...failed.record.pipelines.agentic_graphrag, status: 'error', error_detail: 'timeout',
    }
    mocked.getBatchRecords.mockResolvedValue([hidden, failed])
    renderDashboard()
    const header = await screen.findByRole('rowheader', { name: 'Agentic GraphRAG' })
    const cells = within(header.closest('tr') as HTMLElement).getAllByRole('cell').map((c) => c.textContent)
    // answered, errors, median tokens — the errored answer is not a zero-token answer
    expect(cells.slice(0, 3)).toEqual(['1', '1', '900'])
  })

  it('shows grounding on a run without ground truth, ignoring errored answers', async () => {
    const a = record('h1', 'lookup', { rag: 0, agentic: 0 }, { rag: 100, agentic: 900 }, false)
    a.grounding = { rag: 0.5, agentic_graphrag: 1 }
    const b = record('h2', 'lookup', { rag: 0, agentic: 0 }, { rag: 100, agentic: 0 }, false)
    b.grounding = { rag: 0, agentic_graphrag: 0 }
    b.record.pipelines.agentic_graphrag = {
      ...b.record.pipelines.agentic_graphrag, status: 'error', error_detail: 'timeout',
    }
    mocked.getBatchRecords.mockResolvedValue([a, b])
    renderDashboard()
    const lastCell = async (name: string) => {
      const header = await screen.findByRole('rowheader', { name })
      return within(header.closest('tr') as HTMLElement).getAllByRole('cell').at(-1)?.textContent
    }
    expect(await lastCell('Agentic GraphRAG')).toBe('1.00')
    expect(await lastCell('RAG')).toBe('0.25')
    expect(await lastCell('GraphRAG')).toBe('—')
  })

  it('survives a record missing a pipeline (an imported run)', async () => {
    const partial = record('p1', 'lookup', { rag: 1, agentic: 1 }, { rag: 100, agentic: 200 })
    delete (partial.record.pipelines as Partial<typeof partial.record.pipelines>).graphrag
    delete (partial.scores as Partial<NonNullable<typeof partial.scores>>).graphrag
    mocked.getBatchRecords.mockResolvedValue([partial])
    renderDashboard()
    expect(await screen.findByText('Cost, latency and reliability')).toBeInTheDocument()
  })
})
