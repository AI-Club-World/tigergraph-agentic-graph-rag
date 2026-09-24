import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { EvalTable } from './EvalTable'
import type { BatchRecord, PipelineId, PipelineRecord, PipelineScores, QType } from './types'
import * as batchService from './services/batchService'

vi.mock('./services/batchService')

const mocked = vi.mocked(batchService)

function pipelineRecord(pipeline: PipelineId, answer: string, total: number): PipelineRecord {
  return {
    pipeline,
    answer,
    explanation: 'Explanation.',
    citations: [{ source_id: `${pipeline}-doc`, chunk_id: null, ref_type: 'entity' }],
    chunks_returned: 0,
    citations_count: 1,
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

function record(opts: {
  qid: string
  qtype: QType
  answers: [string, string, string]
  em?: { rag: number; agentic: number }
  agenticTokens?: number
  scored?: boolean
}): BatchRecord {
  const { qid, qtype, answers, em = { rag: 0, agentic: 0 }, agenticTokens = 100, scored = true } = opts
  return {
    run_id: 'test',
    qid,
    question: `Question ${qid}?`,
    qtype,
    ground_truth: scored ? ['gold'] : [],
    gold_doc_ids: scored ? ['Q1'] : [],
    record: {
      query_id: qid,
      query_text: `Question ${qid}?`,
      qtype,
      timestamp: '2026-01-01T00:00:00Z',
      pipelines: {
        rag: pipelineRecord('rag', answers[0], 100),
        graphrag: pipelineRecord('graphrag', answers[1], 100),
        agentic_graphrag: pipelineRecord('agentic_graphrag', answers[2], agenticTokens),
      },
      verdict: {
        token_multiplier_vs_rag: 1,
        token_multiplier_vs_graphrag: 1,
        accuracy_delta_vs_rag: 0,
        accuracy_delta_vs_graphrag: 0,
        summary_line: `Verdict for ${qid}.`,
      },
    },
    scores: scored
      ? { rag: scores(em.rag), graphrag: scores(0), agentic_graphrag: scores(em.agentic) }
      : null,
  }
}

function renderTable(runId = 'test') {
  return render(
    <MemoryRouter initialEntries={[`/eval?run=${runId}`]}>
      <EvalTable />
    </MemoryRouter>,
  )
}

/** The qids of the rendered rows, in display order. */
function qidOrder(container: HTMLElement): string[] {
  return [...container.querySelectorAll('tr.eval-row code')].map((el) => el.textContent ?? '')
}

// Four orders that each sort differently:
//   qid:    q-a, q-b, q-c
//   qtype:  lookup (q-b, q-c), superlative (q-a)
//   gap:    q-c (+1), q-a (0), q-b (-1)
//   tokens: q-b (900), q-a (500), q-c (100)
const SORTING = [
  record({ qid: 'q-c', qtype: 'lookup', answers: ['x', 'x', 'x'], em: { rag: 0, agentic: 1 }, agenticTokens: 100 }),
  record({ qid: 'q-a', qtype: 'superlative', answers: ['x', 'x', 'x'], em: { rag: 0, agentic: 0 }, agenticTokens: 500 }),
  record({ qid: 'q-b', qtype: 'lookup', answers: ['x', 'x', 'x'], em: { rag: 1, agentic: 0 }, agenticTokens: 900 }),
]

beforeEach(() => {
  vi.resetAllMocks()
})

describe('EvalTable', () => {
  it('detects disagreement only after SQuAD-style normalization', async () => {
    mocked.getBatchRecords.mockResolvedValue([
      // Articles, case, punctuation and whitespace are normalized away.
      record({ qid: 'agree-1', qtype: 'lookup', answers: ['The Usain Bolt', 'usain bolt!', 'Usain   Bolt'] }),
      // Curly apostrophes fold to straight ones.
      record({ qid: 'agree-2', qtype: 'lookup', answers: ['Kenya’s team', "kenya's team", "Kenya's Team."] }),
      record({ qid: 'differ', qtype: 'lookup', answers: ['Bolt', 'Bolt', 'Blake'] }),
    ])
    const { container } = renderTable()

    expect(await screen.findByText(/1 of 3 questions have the pipelines disagreeing/)).toBeInTheDocument()

    fireEvent.click(screen.getByLabelText('Pipelines disagree only'))
    expect(qidOrder(container)).toEqual(['differ'])
  })

  it('supports all four sort orders', async () => {
    mocked.getBatchRecords.mockResolvedValue(SORTING)
    const { container } = renderTable()
    await screen.findByText('q-a')

    expect(qidOrder(container)).toEqual(['q-a', 'q-b', 'q-c'])

    const sort = screen.getByLabelText(/^Sort by/)
    fireEvent.change(sort, { target: { value: 'qtype' } })
    expect(qidOrder(container)).toEqual(['q-b', 'q-c', 'q-a'])

    fireEvent.change(sort, { target: { value: 'gap' } })
    expect(qidOrder(container)).toEqual(['q-c', 'q-a', 'q-b'])

    fireEvent.change(sort, { target: { value: 'tokens' } })
    expect(qidOrder(container)).toEqual(['q-b', 'q-a', 'q-c'])

    fireEvent.change(sort, { target: { value: 'qid' } })
    expect(qidOrder(container)).toEqual(['q-a', 'q-b', 'q-c'])
  })

  it('disables the EM-gap sort and explains hidden columns when the run has no gold', async () => {
    mocked.getBatchRecords.mockResolvedValue([
      record({ qid: 'h-1', qtype: 'lookup', answers: ['x', 'y', 'z'], scored: false }),
    ])
    renderTable('hidden')

    expect(
      await screen.findByText(
        'Run "hidden" supplies no gold answers, so the gold and score columns are hidden.',
      ),
    ).toBeInTheDocument()
    expect(screen.getByRole('option', { name: /Agentic . RAG EM/ })).toBeDisabled()
  })

  it('expands and collapses a row from the keyboard with Enter and Space', async () => {
    mocked.getBatchRecords.mockResolvedValue(SORTING)
    const { container } = renderTable()
    await screen.findByText('q-a')

    const row = container.querySelector('tr.eval-row') as HTMLElement
    expect(row).toHaveAttribute('tabindex', '0')
    expect(row).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('Retrieved document sets')).not.toBeInTheDocument()

    row.focus()
    fireEvent.keyDown(row, { key: 'Enter' })
    expect(row).toHaveAttribute('aria-expanded', 'true')
    const detailId = row.getAttribute('aria-controls')
    expect(detailId).toBeTruthy()
    const detail = document.getElementById(detailId as string)
    expect(detail).toHaveTextContent('Retrieved document sets')
    expect(detail).toHaveTextContent('Verdict for q-a.')

    // Space toggles too, and its default (page scroll) is prevented.
    const notPrevented = fireEvent.keyDown(row, { key: ' ' })
    expect(notPrevented).toBe(false)
    expect(row).toHaveAttribute('aria-expanded', 'false')
    expect(row).not.toHaveAttribute('aria-controls')
    expect(screen.queryByText('Retrieved document sets')).not.toBeInTheDocument()

    // Other keys do nothing.
    fireEvent.keyDown(row, { key: 'a' })
    expect(row).toHaveAttribute('aria-expanded', 'false')
  })

  it('keeps only one row open at a time', async () => {
    mocked.getBatchRecords.mockResolvedValue(SORTING)
    const { container } = renderTable()
    await screen.findByText('q-a')

    const [first, second] = [...container.querySelectorAll('tr.eval-row')] as HTMLElement[]
    fireEvent.click(first)
    fireEvent.keyDown(second, { key: 'Enter' })
    expect(first).toHaveAttribute('aria-expanded', 'false')
    expect(second).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getAllByText('Retrieved document sets')).toHaveLength(1)
  })
})
