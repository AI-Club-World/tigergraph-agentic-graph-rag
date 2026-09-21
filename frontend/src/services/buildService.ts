import { config } from '../config'
import { openSse, post } from './http'
import { delay, mockBuildEvents, replay } from './mock/transport'
import type { BuildAccepted, BuildEvent } from '../types'

export interface BuildStreamHandlers {
  onEvent: (event: BuildEvent) => void
  onDone: () => void
  onError: (message: string) => void
}

/** POST /build -> 202 {build_id, stream_token} (TECHNICAL-SPEC §4.6). */
export async function startBuild(): Promise<BuildAccepted> {
  if (!config.useMockApi) return post<BuildAccepted>('/build', {})

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
        error: (data) =>
          handlers.onError(String((data as { detail?: string }).detail ?? 'Build error')),
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
