import { config } from '../config'
import { triggerRecheckOnFailure } from '../useServiceStatus'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    /** Machine-readable reason when the server sends a structured detail. */
    readonly code?: string,
    /** The whole structured detail (e.g. the models an embedding_mismatch offers). */
    readonly detail?: Record<string, unknown>,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

function headers(): HeadersInit {
  const h: Record<string, string> = { 'Content-Type': 'application/json' }
  if (config.apiKey) h['X-API-Key'] = config.apiKey
  return h
}

async function parse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    // Server errors (5xx) suggest the backend is degraded — re-check health.
    if (res.status >= 500) triggerRecheckOnFailure()
    let detail = res.statusText
    let code: string | undefined
    let structured: Record<string, unknown> | undefined
    try {
      const body = (await res.json()) as {
        detail?: string | { code?: string; message?: string } | { loc?: unknown[]; msg?: string }[]
      }
      if (typeof body.detail === 'string') detail = body.detail
      else if (Array.isArray(body.detail)) {
        // FastAPI validation errors (422): a list of {loc, msg}.
        detail = body.detail
          .map((d) => [d.loc?.slice(1).join('.'), d.msg].filter(Boolean).join(': '))
          .join('; ') || detail
      } else if (body.detail) {
        detail = body.detail.message ?? detail
        code = body.detail.code
        structured = body.detail as Record<string, unknown>
      }
    } catch {
      // Non-JSON error body; keep the status text.
    }
    throw new ApiError(detail, res.status, code, structured)
  }
  return (await res.json()) as T
}

export async function get<T>(path: string): Promise<T> {
  try {
    return await parse<T>(await fetch(`${config.apiBaseUrl}${path}`, { headers: headers() }))
  } catch (err) {
    if (err instanceof TypeError) triggerRecheckOnFailure() // network failure
    throw err
  }
}

export async function post<T>(path: string, body: unknown): Promise<T> {
  try {
    return await parse<T>(
      await fetch(`${config.apiBaseUrl}${path}`, {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify(body),
      }),
    )
  } catch (err) {
    if (err instanceof TypeError) triggerRecheckOnFailure() // network failure
    throw err
  }
}

export async function patch<T>(path: string, body: unknown): Promise<T> {
  try {
    return await parse<T>(
      await fetch(`${config.apiBaseUrl}${path}`, {
        method: 'PATCH',
        headers: headers(),
        body: JSON.stringify(body),
      }),
    )
  } catch (err) {
    if (err instanceof TypeError) triggerRecheckOnFailure()
    throw err
  }
}

export type SseHandlers = Record<string, (data: unknown) => void>

/**
 * Opens an SSE stream. `EventSource` cannot send headers, so the stream is
 * authenticated by the short-lived single-use token returned with the id
 * (TECHNICAL-SPEC §4.5, DP-8).
 */
export function openSse(
  path: string,
  streamToken: string,
  handlers: SseHandlers,
  onTransportError: (message: string) => void,
): () => void {
  const url = `${config.apiBaseUrl}${path}?token=${encodeURIComponent(streamToken)}`
  const source = new EventSource(url)

  for (const [name, handler] of Object.entries(handlers)) {
    source.addEventListener(name, (event) => {
      const message = event as MessageEvent<string>
      try {
        handler(JSON.parse(message.data))
      } catch {
        onTransportError(`Malformed ${name} event`)
      }
      // The server closes the connection right after its own 'done' event
      // (both /query/{id}/stream and /build/{id}/stream end their generator
      // there). Closing the client first means that expected close is never
      // seen as a transport failure below — without this, every successful
      // run against a live backend ends with a spurious error banner.
      if (name === 'done') source.close()
    })
  }

  // Any transport error ends the stream: the token is single-use, so the
  // browser's automatic reconnect could only fail with 401.
  source.onerror = () => {
    source.close()
    onTransportError('Stream interrupted before the run finished')
  }

  return () => source.close()
}
