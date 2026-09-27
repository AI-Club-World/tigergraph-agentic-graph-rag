import { config } from '../config'
import { ApiError, get, patch } from './http'
import { delay } from './mock/transport'

export interface BuiltInfo {
  built_at: string
  documents: number
  events: number
  chunks: number
  file_bytes: number
  // Present for datasets built with per-pipeline metrics.
  entities?: number
  relationships?: number
  vectors?: number
  embedding_backend?: string
  ready_ms?: Partial<Record<'rag' | 'graphrag' | 'agentic_graphrag', number>>
}

/** Where a dataset's title came from: typed by a user, a field the records
 *  carry, inferred from their content, or just the file name. */
export type TitleSource = 'given' | 'declared' | 'inferred' | 'file'

export interface Corpus {
  /** The dataset id: its file stem in data/corpus/. */
  name: string
  /** The name shown for it (absent from an older backend: use `name`). */
  title?: string
  title_source?: TitleSource
  description?: string | null
  /** The uploaded file's original name. */
  source_file?: string | null
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
    corpora: [{
      name: 'corpus', title: 'Wikipedia · Olympics · 1900–2022', title_source: 'inferred',
      size_bytes: 23_097_758, documents: 2951, built: null,
    }],
    graph: { tracked: false, schema: null, datasets: {} },
  }
}

export interface UploadedCorpus {
  name: string
  title?: string
  title_source?: TitleSource
  documents: number
}

/** POST /corpora/{name} — the body is the JSONL file itself. A taken id gets
 *  a suffix rather than failing, so files sharing a name can all be added;
 *  without a `title` the server infers one from the documents. */
export async function uploadCorpus(name: string, file: File, title?: string): Promise<UploadedCorpus> {
  if (config.useMockApi) throw new ApiError('Upload needs the live backend', 400)
  const query = new URLSearchParams({ unique: 'true', source_file: file.name })
  if (title?.trim()) query.set('title', title.trim())
  const res = await fetch(`${config.apiBaseUrl}/corpora/${encodeURIComponent(name)}?${query}`, {
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
  return (await res.json()) as UploadedCorpus
}

/** PATCH /corpora/{name} — rename a dataset; an empty title restores the inferred one. */
export async function renameCorpus(name: string, title: string): Promise<Corpus> {
  if (config.useMockApi) throw new ApiError('Rename needs the live backend', 400)
  return patch<Corpus>(`/corpora/${encodeURIComponent(name)}`, { title })
}

/** The name to show for a dataset; its id is added when another dataset
 *  shows the same title, so two datasets never look alike. */
export function datasetLabel(corpus: Pick<Corpus, 'name' | 'title'>, all: Pick<Corpus, 'name' | 'title'>[] = []): string {
  const title = corpus.title?.trim() || corpus.name
  const clash = all.some((c) => c.name !== corpus.name && (c.title?.trim() || c.name) === title)
  return clash ? `${title} (${corpus.name})` : title
}

/** A dataset name from an uploaded file name: data/corpus/<name>.jsonl. */
export function datasetNameFor(fileName: string): string {
  return fileName.replace(/\.[^.]*$/, '').replace(/[^A-Za-z0-9_-]+/g, '_').slice(0, 64) || 'dataset'
}
