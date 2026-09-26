import { config } from '../config'
import { get, openSse, post } from './http'
import { delay, mockBuildEvents, replay } from './mock/transport'
import type { BuildAccepted, BuildEvent } from '../types'

export interface BuildStreamHandlers {
  onEvent: (event: BuildEvent) => void
  onDone: () => void
  onError: (message: string) => void
}

export interface BuildOptions {
  /** The dataset is already loaded: delete its data and load it again. */
  rebuild?: boolean
  /** Drop and recreate the whole graph (every dataset). */
  reset?: boolean
}

/** POST /build {dataset, rebuild, reset} -> 202 {build_id, stream_token}.
 *  409 with code already_built / reset_required / build_running asks first. */
export async function startBuild(dataset = 'corpus', options: BuildOptions = {}): Promise<BuildAccepted> {
  if (!config.useMockApi) return post<BuildAccepted>('/build', { dataset, ...options })

  await delay(120)
  const buildId = `mock-build-${Date.now()}`
  return { build_id: buildId, stream_token: `mock-token-${buildId}` }
}

/** GET /build/{id}/stream?token=… (SSE). Returns a cancel function. */
export function openBuildStream(
  accepted: BuildAccepted,
  handlers: BuildStreamHandlers,
): () => void {
  if (!config.useMockApi) {
    return openSse(
      `/build/${accepted.build_id}/stream`,
      accepted.stream_token,
      {
        build: (data) => handlers.onEvent(data as BuildEvent),
        done: () => handlers.onDone(),
      },
      handlers.onError,
    )
  }

  return replay(
    mockBuildEvents(),
    (event) => event.elapsed_ms,
    handlers.onEvent,
    handlers.onDone,
  )
}

export interface CurrentBuild {
  build_id: string
  dataset: string | null
  running: boolean
  events: BuildEvent[]
}

/** GET /build/current — the latest build with its events, so a reloaded page
 *  can show a running build and keep following it. */
export async function getCurrentBuild(): Promise<CurrentBuild | null> {
  if (config.useMockApi) return null
  return (await get<{ build: CurrentBuild | null }>('/build/current')).build
}
