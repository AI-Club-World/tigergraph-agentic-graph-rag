import { config } from '../config'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
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
    let detail = res.statusText
    try {
      const body = (await res.json()) as { detail?: string }
      if (body.detail) detail = body.detail
    } catch {
      // Non-JSON error body; keep the status text.
    }
    throw new ApiError(detail, res.status)
  }
  return (await res.json()) as T
}

export async function get<T>(path: string): Promise<T> {
  return parse<T>(await fetch(`${config.apiBaseUrl}${path}`, { headers: headers() }))
}

export async function post<T>(path: string, body: unknown): Promise<T> {
  return parse<T>(
    await fetch(`${config.apiBaseUrl}${path}`, {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify(body),
    }),
  )
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
    })
  }

  source.onerror = () => {
    if (source.readyState === EventSource.CLOSED) {
      onTransportError('Stream closed unexpectedly')
    }
  }

  return () => source.close()
}
