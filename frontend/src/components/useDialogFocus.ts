import { useEffect, type RefObject } from 'react'

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * Modal focus handling: on open, focus moves into the dialog; Tab and
 * Shift+Tab stay inside it; Escape closes this dialog only (not a dialog
 * underneath); on close, focus returns to whatever had it before.
 */
export function useDialogFocus(ref: RefObject<HTMLElement>, active: boolean, onClose?: () => void) {
  useEffect(() => {
    if (!active) return
    const dialog = ref.current
    if (!dialog) return
    const previous = document.activeElement as HTMLElement | null
    const focusables = () => Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE))
    ;(focusables()[0] ?? dialog).focus()

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && onClose) {
        e.stopPropagation()
        onClose()
        return
      }
      if (e.key !== 'Tab') return
      const items = focusables()
      if (!items.length) return
      const first = items[0]
      const last = items[items.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
    dialog.addEventListener('keydown', onKey)
    return () => {
      dialog.removeEventListener('keydown', onKey)
      previous?.focus?.()
    }
    // onClose is read at call time; re-running on each render would steal focus.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, ref])
}
