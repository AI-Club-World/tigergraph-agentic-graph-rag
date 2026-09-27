import { config } from '../config'
import { get, patch, post } from './http'

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

// ── Embedding models (config-docs/EMBEDDING-SWITCHING.md) ─────────────────────

export type EmbeddingState = 'complete' | 'incomplete' | 'building' | 'failed' | 'not_stored' | 'evicting'

export interface EmbeddingModelStatus {
  key: string
  label: string
  dim: number
  vertex_type: string
  state: EmbeddingState
  stored: boolean
  complete: boolean
  chunks_done: number
  chunks_total: number
  backend: string | null
  active: boolean
}

export interface EmbeddingJob {
  id: string
  model: string
  mode: 'replace' | 'parallel' | 'complete'
  delete: string[]
  status: 'running' | 'failed' | 'complete'
  phase: 'queued' | 'deleting' | 'embedding' | 'indexing' | 'done'
  chunks_done: number
  chunks_total: number
  batches_done: number
  batches_total: number
  attempts: number
  error: string | null
  updated_at: string
}

export interface EmbeddingOverview {
  active: string
  cap: number
  stored: string[]
  models: EmbeddingModelStatus[]
  job: EmbeddingJob | null
  chunks_total: number
  build_running: boolean
  /** Why switching is refused right now (null: allowed). */
  switch_disabled_reason: string | null
  layout_current: boolean
}

interface SwitchOption {
  needs_eviction: boolean
  evictable: string[]
}

export interface EmbeddingPlan {
  target: EmbeddingModelStatus
  active: string
  cap: number
  stored: string[]
  chunks_total: number
  /** The target already covers the corpus: switching is instant. */
  instant: boolean
  parallel: SwitchOption & { stored_after: number }
  replace: SwitchOption & { deletes: string | null; keeps: string[] }
  switch_disabled_reason: string | null
}

export type SwitchMode = 'replace' | 'parallel'

/** GET /embeddings — every model's state for the corpus, the cap and the job. */
export async function fetchEmbeddings(): Promise<EmbeddingOverview> {
  return get<EmbeddingOverview>('/embeddings')
}

/** GET /embeddings/plan — what switching to `model` would do right now. */
export async function fetchEmbeddingPlan(model: string): Promise<EmbeddingPlan> {
  return get<EmbeddingPlan>(`/embeddings/plan?model=${encodeURIComponent(model)}`)
}

/** POST /embeddings/switch — instant for a complete model; else `mode` (and
 *  at the cap, `evict`) must be the user's explicit choice. */
export async function switchEmbedding(
  model: string,
  mode?: SwitchMode,
  evict?: string,
): Promise<{ switched: boolean; active: string; job?: EmbeddingJob }> {
  return post('/embeddings/switch', { model, ...(mode ? { mode } : {}), ...(evict ? { evict } : {}) })
}

/** POST /embeddings/resume — continue a failed job from its last checkpoint. */
export async function resumeEmbeddingJob(): Promise<{ job: EmbeddingJob }> {
  return post('/embeddings/resume', {})
}

/** POST /embeddings/{model}/complete — embed the chunks a stored model lacks. */
export async function completeEmbedding(model: string): Promise<{ job: EmbeddingJob }> {
  return post(`/embeddings/${encodeURIComponent(model)}/complete`, {})
}

/** The provider the settings panel shows as selected: the preset serving the
 *  model when the server resolved one, else the configured client type. */
export function providerIdOf(s: AppSettings): string {
  return s.llm_provider_preset || s.llm_provider
}
