import type { ReactNode } from 'react'

interface Props {
  tone?: 'error' | 'ok'
  /** Shows a close button; the owner clears the message. */
  onClose?: () => void
  role?: 'alert' | 'status'
  children: ReactNode
}

/** A banner message (error or confirmation) the user can dismiss. */
export function Notice({ tone = 'error', onClose, role, children }: Props) {
  return (
    <div className={`notice ${tone === 'ok' ? 'flash' : 'error-box pad'}`} role={role ?? (tone === 'error' ? 'alert' : 'status')}>
      <span className="notice-text">{children}</span>
      {onClose && (
        <button type="button" className="notice-close" aria-label="Dismiss message" title="Dismiss" onClick={onClose}>
          ×
        </button>
      )}
    </div>
  )
}
