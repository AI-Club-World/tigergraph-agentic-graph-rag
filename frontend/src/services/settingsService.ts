import { patch } from './http'

export interface AppSettings {
  llm_provider: string
  llm_model: string
  embedding_model: string
  embedding_dim: number
}

/** GET /settings — unauthenticated, returns effective runtime config. */
export async function fetchSettings(): Promise<AppSettings> {
  // Bypass the auth wrapper: /settings is on `app`, not `router`.
  // Still use the same base URL from config.
  const { config } = await import('../config')
  const res = await fetch(`${config.apiBaseUrl}/settings`, { signal: AbortSignal.timeout(8_000) })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return (await res.json()) as AppSettings
}

/** PATCH /settings — authenticated; updates runtime model without restart. */
export async function saveSettings(p: { llm_model?: string; embedding_model?: string }): Promise<AppSettings> {
  return patch<AppSettings>('/settings', p)
}

// Models offered per provider. Free-text entry is always allowed in addition.
export const MODELS_BY_PROVIDER: Record<string, string[]> = {
  // Gemini via OpenAI-compatible endpoint (recommended for AQ. key format)
  openai_compatible: [
    'gemini-3.6-flash',
    'gemini-2.5-flash',
    'gemini-2.5-pro',
    'gemini-2.5-flash-lite',
    'gemini-2.0-flash-lite',
    'gemini-1.5-flash',
    'gemini-1.5-pro',
  ],
  // Native Gemini SDK (requires AIza... key from Google AI Studio)
  google: [
    'gemini-3.6-flash',
    'gemini-2.5-flash',
    'gemini-2.5-pro',
    'gemini-2.0-flash-lite',
    'gemini-1.5-flash',
    'gemini-1.5-pro',
  ],
  openai: ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-3.5-turbo'],
  anthropic: [
    'claude-opus-4-5',
    'claude-sonnet-4-5',
    'claude-3-5-haiku-20241022',
  ],
  gemini: [],      // alias → same as google (resolved in SettingsPanel)
  google_genai: [],
}

export const EMBEDDING_OPTIONS = [
  { value: '@cf/baai/bge-m3', label: 'BGE-M3 (BAAI) — Cloudflare → NVIDIA NIM → local', dim: 1024 },
] as const
