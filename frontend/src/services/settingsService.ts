import { get, patch } from './http'

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

/** PATCH /settings — authenticated; updates runtime provider/model without restart.
 *  The selected LLM applies to all three pipelines. */
export async function saveSettings(p: {
  llm_provider?: string
  llm_model?: string
  embedding_model?: string
}): Promise<AppSettings> {
  return patch<AppSettings>('/settings', p)
}

export interface ProviderInfo {
  id: string
  label: string
  configured: boolean // API key set on the server
}

/** GET /settings/providers — the runtime-selectable LLM providers. */
export async function fetchProviders(): Promise<ProviderInfo[]> {
  return get<ProviderInfo[]>('/settings/providers')
}

/** GET /settings/models — the provider's live text-model catalog. */
export async function fetchModels(provider: string): Promise<string[]> {
  const res = await get<{ models: string[] }>(`/settings/models?provider=${encodeURIComponent(provider)}`)
  return res.models
}

export const EMBEDDING_OPTIONS = [
  { value: '@cf/baai/bge-m3', label: 'BGE-M3 (BAAI) — Cloudflare → NVIDIA NIM → local', dim: 1024 },
] as const
