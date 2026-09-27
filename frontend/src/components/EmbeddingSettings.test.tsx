import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as settingsService from '../services/settingsService'
import type { EmbeddingModelStatus, EmbeddingOverview, EmbeddingPlan } from '../services/settingsService'
import { EmbeddingSettings } from './EmbeddingSettings'

vi.mock('../services/settingsService', async (importOriginal) => {
  const actual = await importOriginal<typeof settingsService>()
  return {
    ...actual,
    fetchEmbeddings: vi.fn(),
    fetchEmbeddingPlan: vi.fn(),
    switchEmbedding: vi.fn(),
    resumeEmbeddingJob: vi.fn(),
    completeEmbedding: vi.fn(),
  }
})

const mocked = vi.mocked(settingsService)

const LABELS: Record<string, [string, number]> = {
  'qwen3-embedding-0.6b': ['Qwen3-Embedding-0.6B', 1024],
  'embeddinggemma-300m': ['EmbeddingGemma-300M', 768],
  'gte-large-en-v1.5': ['gte-large-en-v1.5', 1024],
  'mxbai-embed-large-v1': ['mxbai-embed-large-v1', 1024],
  'bge-large-en-v1.5': ['bge-large-en-v1.5', 1024],
}

function model(key: string, state: EmbeddingModelStatus['state'], active = false): EmbeddingModelStatus {
  const [label, dim] = LABELS[key]
  return {
    key, label, dim, vertex_type: `Embedding_${key}`, state, stored: state !== 'not_stored',
    complete: state === 'complete', chunks_done: state === 'complete' ? 100 : 0, chunks_total: 100,
    backend: null, active,
  }
}

function overview(extra: Partial<EmbeddingOverview> = {}): EmbeddingOverview {
  return {
    active: 'bge-large-en-v1.5',
    cap: 2,
    stored: ['qwen3-embedding-0.6b', 'bge-large-en-v1.5'],
    models: [
      model('qwen3-embedding-0.6b', 'complete'),
      model('embeddinggemma-300m', 'not_stored'),
      model('gte-large-en-v1.5', 'not_stored'),
      model('mxbai-embed-large-v1', 'not_stored'),
      model('bge-large-en-v1.5', 'complete', true),
    ],
    job: null,
    chunks_total: 100,
    build_running: false,
    switch_disabled_reason: null,
    layout_current: true,
    ...extra,
  }
}

function plan(extra: Partial<EmbeddingPlan> = {}): EmbeddingPlan {
  return {
    target: model('gte-large-en-v1.5', 'not_stored'),
    active: 'bge-large-en-v1.5',
    cap: 2,
    stored: ['qwen3-embedding-0.6b', 'bge-large-en-v1.5'],
    chunks_total: 100,
    instant: false,
    parallel: { needs_eviction: true, evictable: ['qwen3-embedding-0.6b', 'bge-large-en-v1.5'], stored_after: 2 },
    replace: { deletes: 'bge-large-en-v1.5', keeps: ['qwen3-embedding-0.6b'], needs_eviction: false, evictable: [] },
    switch_disabled_reason: null,
    ...extra,
  }
}

async function renderIt() {
  render(<EmbeddingSettings />)
  await act(async () => undefined)
}

async function pick(label: string) {
  await act(async () => {
    fireEvent.click(screen.getByRole('radio', { name: new RegExp(`^${label}`) }))
  })
}

beforeEach(() => {
  vi.resetAllMocks()
  mocked.fetchEmbeddings.mockResolvedValue(overview())
  mocked.fetchEmbeddingPlan.mockResolvedValue(plan())
  mocked.switchEmbedding.mockResolvedValue({ switched: false, active: 'bge-large-en-v1.5' })
})

describe('EmbeddingSettings', () => {
  it('lists the five models with their state for the corpus', async () => {
    await renderIt()
    const group = screen.getByRole('radiogroup', { name: 'Embedding model' })
    expect(within(group).getAllByRole('radio')).toHaveLength(5)
    expect(group).toHaveTextContent('bge-large-en-v1.5Active · Complete')
    expect(group).toHaveTextContent('EmbeddingGemma-300MNot stored768d')
    expect(screen.getByText(/2\/2 models stored for 100 chunks/)).toBeInTheDocument()
  })

  it('is disabled, and says why, while an ingestion build runs', async () => {
    mocked.fetchEmbeddings.mockResolvedValue(
      overview({ build_running: true, switch_disabled_reason: 'An ingestion build is running.' }),
    )
    await renderIt()
    expect(screen.getByRole('status')).toHaveTextContent('Switching is disabled: An ingestion build is running.')
    for (const radio of screen.getAllByRole('radio')) expect(radio).toBeDisabled()
  })

  it('shows two options with the real cap state and preselects neither', async () => {
    await renderIt()
    await pick('gte-large-en-v1.5')
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByTestId('cap-status')).toHaveTextContent(
      '2/2 models currently stored: Qwen3-Embedding-0.6B, bge-large-en-v1.5 (active).',
    )
    expect(dialog).toHaveTextContent("bge-large-en-v1.5's embeddings are deleted before re-embedding")
    expect(dialog).toHaveTextContent('2/2 stored — adding gte-large-en-v1.5 requires evicting one.')
    const modes = within(within(dialog).getByRole('radiogroup', { name: 'How to switch' })).getAllByRole('radio')
    expect(modes.every((r) => !(r as HTMLInputElement).checked)).toBe(true)
    expect(within(dialog).getByRole('button', { name: 'Choose an option' })).toBeDisabled()
  })

  it('at the cap, parallel indices cannot start until a model to evict is picked', async () => {
    await renderIt()
    await pick('gte-large-en-v1.5')
    const dialog = screen.getByRole('dialog')
    fireEvent.click(within(dialog).getByRole('radio', { name: /Keep parallel indices/ }))
    expect(within(dialog).getByText('Evict one model first (required)')).toBeInTheDocument()
    const confirm = within(dialog).getByRole('button', { name: 'Build alongside' })
    expect(confirm).toBeDisabled()
    fireEvent.click(within(dialog).getByRole('radio', { name: 'Qwen3-Embedding-0.6B' }))
    expect(confirm).toBeEnabled()
    await act(async () => {
      fireEvent.click(confirm)
    })
    expect(mocked.switchEmbedding).toHaveBeenCalledWith('gte-large-en-v1.5', 'parallel', 'qwen3-embedding-0.6b')
  })

  it('force re-embed needs no eviction when it frees a slot', async () => {
    await renderIt()
    await pick('gte-large-en-v1.5')
    const dialog = screen.getByRole('dialog')
    fireEvent.click(within(dialog).getByRole('radio', { name: /Force full re-embed/ }))
    expect(within(dialog).queryByText('Evict one model first (required)')).toBeNull()
    await act(async () => {
      fireEvent.click(within(dialog).getByRole('button', { name: 'Re-embed' }))
    })
    expect(mocked.switchEmbedding).toHaveBeenCalledWith('gte-large-en-v1.5', 'replace', undefined)
  })

  it('a model with complete embeddings switches instantly', async () => {
    mocked.fetchEmbeddingPlan.mockResolvedValue(plan({ target: model('qwen3-embedding-0.6b', 'complete'), instant: true }))
    await renderIt()
    await pick('Qwen3-Embedding-0.6B')
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('the switch is instant')
    await act(async () => {
      fireEvent.click(within(dialog).getByRole('button', { name: 'Switch' }))
    })
    expect(mocked.switchEmbedding).toHaveBeenCalledWith('qwen3-embedding-0.6b', undefined, undefined)
  })

  it('a failed job says why and resumes from its checkpoint', async () => {
    mocked.fetchEmbeddings.mockResolvedValue(overview({
      job: {
        id: 'j', model: 'gte-large-en-v1.5', mode: 'parallel', delete: [], status: 'failed', phase: 'embedding',
        chunks_done: 50, chunks_total: 100, batches_done: 1, batches_total: 2, attempts: 1,
        error: 'rate limited (429)', updated_at: '',
      },
    }))
    mocked.resumeEmbeddingJob.mockResolvedValue({} as never)
    await renderIt()
    expect(screen.getByText(/failed while batch 1\/2 · 50\/100 chunks — rate limited \(429\)/)).toBeInTheDocument()
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Resume' }))
    })
    expect(mocked.resumeEmbeddingJob).toHaveBeenCalled()
  })
})
