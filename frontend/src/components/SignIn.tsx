/**
 * Sign-in (TECHNICAL-SPEC §4.5): the access key is typed at runtime and
 * exchanged for a session token; it is never compiled into the bundle.
 * `SessionControl` sits in the header: the role when signed in, a Sign in
 * button when not. The dialog also opens by itself when a request finds the
 * session gone (expired or signed out elsewhere).
 */
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { config } from '../config'
import {
  AUTH_REQUIRED_EVENT,
  SESSION_CHANGED_EVENT,
  SignInError,
  sessionRole,
  sessionToken,
  signIn,
  signOut,
  type Role,
} from '../services/session'
import { useDialogFocus } from './useDialogFocus'

export function SignInDialog({
  onClose,
  onSignedIn,
  reason,
}: {
  onClose: () => void
  onSignedIn?: () => void
  reason?: string
}) {
  const [key, setKey] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useDialogFocus(ref, true, onClose)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await signIn(key)
      setKey('')
      onClose()
      onSignedIn?.()
    } catch (err) {
      setError(err instanceof SignInError ? err.message : 'Could not reach the backend')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="embed-dialog-backdrop" role="presentation">
      <div className="embed-dialog signin-dialog" role="dialog" aria-modal="true" aria-labelledby="signin-title" ref={ref}>
        <h3 id="signin-title">Sign in</h3>
        {reason && <p className="muted small">{reason}</p>}
        <form onSubmit={(e) => void submit(e)} className="signin-form">
          <label htmlFor="signin-key">Access key</label>
          <input
            id="signin-key"
            type="password"
            autoComplete="current-password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            required
          />
          <p className="muted small">
            The viewer key (OGR_API_KEY) can ask questions and read runs; the admin key (OGR_ADMIN_KEY) can also
            build, upload, switch embeddings and start benchmarks. The key is sent once; this tab keeps only a
            session that ends when the tab closes.
          </p>
          {error && <p className="error-text small" role="alert">{error}</p>}
          <div className="confirm-actions">
            <button type="button" className="secondary" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn-primary" disabled={busy || !key}>
              {busy ? 'Signing in…' : 'Sign in'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

/** Indirection so tests can observe the reload. */
export const pageReload = { reload: () => window.location.reload() }
function reloadPage() {
  pageReload.reload()
}

export function SessionControl() {
  const [role, setRole] = useState<Role | null>(() => (sessionToken() ? sessionRole() : null))
  const [open, setOpen] = useState(() => !config.useMockApi && !sessionToken())
  const [reason, setReason] = useState<string | undefined>()

  useEffect(() => {
    const changed = () => setRole(sessionToken() ? sessionRole() : null)
    const required = (e: Event) => {
      // Only a session that existed can have ended; before the first sign-in
      // the dialog just asks to sign in.
      setReason((e as CustomEvent<{ hadSession?: boolean }>).detail?.hadSession
        ? 'Your session has ended. Sign in again to continue.'
        : undefined)
      setOpen(true)
    }
    window.addEventListener(SESSION_CHANGED_EVENT, changed)
    window.addEventListener(AUTH_REQUIRED_EVENT, required)
    return () => {
      window.removeEventListener(SESSION_CHANGED_EVENT, changed)
      window.removeEventListener(AUTH_REQUIRED_EVENT, required)
    }
  }, [])

  if (config.useMockApi) return null
  return (
    <>
      {role ? (
        <span className="session-chip" title={role === 'admin' ? 'Signed in with the admin key' : 'Signed in with the viewer key'}>
          {role}
          <button type="button" className="link-button" onClick={() => void signOut()}>
            Sign out
          </button>
        </span>
      ) : (
        <button type="button" className="secondary session-signin" onClick={() => { setReason(undefined); setOpen(true) }}>
          Sign in
        </button>
      )}
      {open && (
        <SignInDialog
          reason={reason}
          onClose={() => setOpen(false)}
          // Screens fetched before sign-in hold 401 errors: reload them all
          // with the new session (it survives a reload, in sessionStorage).
          onSignedIn={() => reloadPage()}
        />
      )}
    </>
  )
}
