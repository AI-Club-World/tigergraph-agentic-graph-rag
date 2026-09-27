import { config } from '../config'
import { get, patch } from './http'

export interface AppSettings {
  llm_provider: string
  /** The selectable provider serving the model (null: none of the presets). */
  llm_provider_preset?: string | null
  /** host[:port] of the LLM endpoint, when one is set. */
  llm_base_host?: string | null
  llm_model: string
  embedding_model: string
  embedding_dim: number
}

/** GET /settings — unauthenticated, returns effective runtime config. */
export async function fetchSettings(): Promise<AppSettings> {
  // Bypass the auth wrapper: /settings is on `app`, not `router`.
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

/** GET /settings/models — the provider's live text-model catalog. NVIDIA is
 *  narrowed to 'Free Endpoint' models; `note` says when that was not possible. */
export async function fetchModels(provider: string): Promise<{ models: string[]; note: string | null }> {
  const res = await get<{ models: string[]; note?: string | null }>(
    `/settings/models?provider=${encodeURIComponent(provider)}`,
  )
  return { models: res.models, note: res.note ?? null }
}

export const EMBEDDING_OPTIONS = [
  { value: '@cf/baai/bge-m3', label: 'BGE-M3 (BAAI) — Cloudflare → local', dim: 1024 },
] as const

/** The provider the settings panel shows as selected: the preset serving the
 *  model when the server resolved one, else the configured client type. */
export function providerIdOf(s: AppSettings): string {
  return s.llm_provider_preset || s.llm_provider
}
