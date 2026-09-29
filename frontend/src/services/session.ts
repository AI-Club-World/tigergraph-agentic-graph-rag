/**
 * Browser session (TECHNICAL-SPEC §4.5). No key is compiled into the bundle:
 * the operator types it once, the backend returns a session token, and only
 * that token is kept — in sessionStorage, so it ends with the tab. Every
 * request sends it as `Authorization: Bearer`.
 */
import { config } from '../config'

export type Role = 'admin' | 'viewer'

const TOKEN_KEY = 'ogr.session.token'
const ROLE_KEY = 'ogr.session.role'
/** Fired when a request finds no valid session, so the app can ask to sign in. */
export const AUTH_REQUIRED_EVENT = 'ogr:auth-required'
export const SESSION_CHANGED_EVENT = 'ogr:session-changed'

function read(key: string): string | null {
  try {
    return window.sessionStorage.getItem(key)
  } catch {
    return null
  }
}

function write(key: string, value: string | null) {
  try {
    if (value === null) window.sessionStorage.removeItem(key)
    else window.sessionStorage.setItem(key, value)
  } catch {
    // Storage blocked (private mode): the session lasts until reload.
  }
}

let memoryToken: string | null = null
let memoryRole: Role | null = null

export function sessionToken(): string | null {
  return memoryToken ?? read(TOKEN_KEY)
}

export function sessionRole(): Role | null {
  return memoryRole ?? (read(ROLE_KEY) as Role | null)
}

function store(token: string | null, role: Role | null) {
  memoryToken = token
  memoryRole = role
  write(TOKEN_KEY, token)
  write(ROLE_KEY, role)
  window.dispatchEvent(new Event(SESSION_CHANGED_EVENT))
}

/** The auth header for a request; empty in mock mode or when signed out. */
export function authHeaders(): Record<string, string> {
  const token = config.useMockApi ? null : sessionToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export class SignInError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = 'SignInError'
  }
}

export async function signIn(key: string): Promise<Role> {
  const res = await fetch(`${config.apiBaseUrl}/auth/session`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key }),
  })
  if (!res.ok) {
    let detail = res.status === 401 ? 'Wrong key' : res.statusText
    try {
      const body = (await res.json()) as { detail?: string }
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      // keep the default message
    }
    throw new SignInError(detail, res.status)
  }
  const body = (await res.json()) as { token: string; role: Role }
  store(body.token, body.role)
  return body.role
}

export async function signOut(): Promise<void> {
  const headers = authHeaders()
  store(null, null)
  try {
    await fetch(`${config.apiBaseUrl}/auth/session`, { method: 'DELETE', headers })
  } catch {
    // Signed out locally either way; the server session expires on its own.
  }
}

/** A request came back 401: the session is gone. Forget it and ask again. */
export function sessionRejected() {
  if (config.useMockApi) return
  const hadSession = Boolean(sessionToken())
  store(null, null)
  window.dispatchEvent(new CustomEvent(AUTH_REQUIRED_EVENT, { detail: { hadSession } }))
}
