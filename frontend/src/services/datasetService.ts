import { config } from '../config'
import { ApiError, get } from './http'
import { delay } from './mock/transport'

export interface BuiltInfo {
  built_at: string
  documents: number
  events: number
  chunks: number
  file_bytes: number
}

export interface Corpus {
  name: string
  size_bytes: number
  documents: number
  /** Present when the dataset is loaded into the graph. */
  built: BuiltInfo | null
}

export interface CorporaResponse {
  corpora: Corpus[]
  graph: {
    tracked: boolean
    schema: { embedding_model: string; embedding_dim: number } | null
    datasets: Record<string, BuiltInfo>
  }
}

/** GET /corpora — datasets in data/corpus/ and which are loaded. */
export async function listCorpora(): Promise<CorporaResponse> {
  if (!config.useMockApi) return get<CorporaResponse>('/corpora')
  await delay(60)
  return {
    corpora: [{ name: 'corpus', size_bytes: 23_097_758, documents: 2951, built: null }],
    graph: { tracked: false, schema: null, datasets: {} },
  }
}

/** POST /corpora/{name} — the body is the JSONL file itself. */
export async function uploadCorpus(name: string, file: File): Promise<{ name: string; documents: number }> {
  if (config.useMockApi) throw new ApiError('Upload needs the live backend', 400)
  const res = await fetch(`${config.apiBaseUrl}/corpora/${encodeURIComponent(name)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-ndjson', ...(config.apiKey ? { 'X-API-Key': config.apiKey } : {}) },
    body: file,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = (await res.json()) as { detail?: string }
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      // keep status text
    }
    throw new ApiError(detail, res.status)
  }
  return (await res.json()) as { name: string; documents: number }
}

/** A dataset name from an uploaded file name: data/corpus/<name>.jsonl. */
export function datasetNameFor(fileName: string): string {
  return fileName.replace(/\.[^.]*$/, '').replace(/[^A-Za-z0-9_-]+/g, '_').slice(0, 64) || 'dataset'
}
