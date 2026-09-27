import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as settingsService from './services/settingsService'
import { AUTO_CLOSE_S, SettingsPanel } from './SettingsPanel'

// The panel needs the live backend; the service is mocked below.
vi.mock('./config', () => ({ config: { useMockApi: false, apiBaseUrl: '', apiKey: '' } }))
vi.mock('./useServiceStatus', () => ({ triggerRecheckOnFailure: vi.fn() }))
vi.mock('./services/settingsService', async (importOriginal) => {
  const actual = await importOriginal<typeof settingsService>()
  return {
    ...actual,
    fetchSettings: vi.fn(),
    fetchProviders: vi.fn(),
    fetchModels: vi.fn(),
    saveSettings: vi.fn(),
    fetchEmbeddings: vi.fn(),
  }
})

const mocked = vi.mocked(settingsService)

const PROVIDERS = [
  { id: 'gemini', label: 'Google Gemini (AI Studio)', configured: true },
  { id: 'nvidia_nim', label: 'NVIDIA NIM', configured: false },
  { id: 'groq', label: 'Groq', configured: true },
]

// Started with LLM_PROVIDER=openai_compatible pointed at NVIDIA.
const STARTUP = {
  llm_provider: 'openai_compatible',
  llm_provider_preset: 'nvidia_nim',
  llm_base_host: 'integrate.api.nvidia.com',
  llm_model: 'meta/llama-3.3-70b-instruct',
  embedding_model: 'bge-large-en-v1.5',
  embedding_dim: 1024,
}

async function openPanel() {
  render(<SettingsPanel />)
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Open settings' }))
  })
}

beforeEach(() => {
  vi.resetAllMocks()
  mocked.fetchSettings.mockResolvedValue(STARTUP)
  mocked.fetchProviders.mockResolvedValue(PROVIDERS)
  mocked.fetchEmbeddings.mockRejectedValue(new Error('not under test'))
  mocked.fetchModels.mockResolvedValue({ models: ['meta/llama-3.3-70b-instruct', 'qwen/qwen3'], note: null })
})

afterEach(() => vi.useRealTimers())

describe('SettingsPanel', () => {
  it('selects the provider that serves the current model', async () => {
    await openPanel()
    const select = screen.getByLabelText('Provider') as HTMLSelectElement
    expect(select.value).toBe('nvidia_nim')
    expect(select.selectedOptions[0].textContent).toContain('NVIDIA NIM')
    expect(select.selectedOptions[0].disabled).toBe(false)
    expect(mocked.fetchModels).toHaveBeenCalledWith('nvidia_nim')
    expect((screen.getByRole('radio', { name: 'meta/llama-3.3-70b-instruct' }) as HTMLInputElement).checked).toBe(true)
  })

  it('keeping the provider sends only the model', async () => {
    mocked.saveSettings.mockResolvedValue({ ...STARTUP, llm_model: 'qwen/qwen3' })
    await openPanel()
    fireEvent.click(screen.getByRole('radio', { name: 'qwen/qwen3' }))
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Apply' }))
    })
    expect(mocked.saveSettings).toHaveBeenCalledWith({ llm_model: 'qwen/qwen3' })
  })

  it('names a provider outside the presets by its endpoint', async () => {
    mocked.fetchSettings.mockResolvedValue({
      ...STARTUP, llm_provider_preset: null, llm_base_host: 'localhost:11434', llm_model: 'qwen2.5:7b',
    })
    await openPanel()
    const select = screen.getByLabelText('Provider') as HTMLSelectElement
    expect(select.selectedOptions[0].textContent).toBe('openai_compatible · localhost:11434 (server default)')
  })

  it(`closes ${AUTO_CLOSE_S} seconds after a successful Apply`, async () => {
    mocked.saveSettings.mockResolvedValue({ ...STARTUP, llm_model: 'qwen/qwen3' })
    await openPanel()
    vi.useFakeTimers()
    fireEvent.click(screen.getByRole('radio', { name: 'qwen/qwen3' }))
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Apply' }))
    })
    expect(screen.getByText(`Closing in ${AUTO_CLOSE_S}s ·`, { exact: false })).toBeTruthy()
    for (let i = 0; i < AUTO_CLOSE_S - 1; i++) await act(async () => { vi.advanceTimersByTime(1000) })
    expect(screen.queryByRole('dialog')).not.toBeNull()
    await act(async () => { vi.advanceTimersByTime(1000) })
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('stays open when the user keeps editing or asks to keep it open', async () => {
    mocked.saveSettings.mockResolvedValue({ ...STARTUP, llm_model: 'qwen/qwen3' })
    await openPanel()
    vi.useFakeTimers()
    fireEvent.click(screen.getByRole('radio', { name: 'qwen/qwen3' }))
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Apply' }))
    })
    fireEvent.click(screen.getByRole('button', { name: 'Keep open' }))
    await act(async () => { vi.advanceTimersByTime((AUTO_CLOSE_S + 1) * 1000) })
    expect(screen.queryByRole('dialog')).not.toBeNull()
  })
})
