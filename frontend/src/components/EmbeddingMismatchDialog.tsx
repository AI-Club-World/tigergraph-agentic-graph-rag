import { useRef } from 'react'
import { useDialogFocus } from './useDialogFocus'

/**
 * Shown when the server blocks a query because the selected embedding model
 * has no complete embeddings for the data (409 embedding_mismatch). The
 * query only proceeds with a model the server listed as complete — there is
 * no "run anyway": a query is never searched against another model's index.
 */

export interface MismatchModel {
  key: string
  label: string
  dim: number
}

export interface EmbeddingMismatch {
  message: string
  selected: { key: string; label: string; state: string; chunks_done: number; chunks_total: number }
  available: MismatchModel[]
}

interface Props {
  mismatch: EmbeddingMismatch
  onPick: (model: string) => void
  onCancel: () => void
}

export function EmbeddingMismatchDialog({ mismatch, onPick, onCancel }: Props) {
  const { selected, available } = mismatch
  const ref = useRef<HTMLDivElement>(null)
  useDialogFocus(ref, true, onCancel)
  return (
    <div className="embed-dialog-backdrop" role="presentation">
      <div className="embed-dialog" role="alertdialog" aria-modal="true" aria-labelledby="mismatch-title" ref={ref}>
        <h3 id="mismatch-title">No matching embeddings for {selected.label}</h3>
        <p>{mismatch.message}</p>
        {available.length > 0 ? (
          <>
            <p>These models have complete, queryable embeddings for this data. Run the query with one of them:</p>
            <div className="embed-pick">
              {available.map((m) => (
                <button key={m.key} type="button" className="btn-primary" onClick={() => onPick(m.key)}>
                  Use {m.label} ({m.dim}d)
                </button>
              ))}
            </div>
          </>
        ) : (
          <p>
            No model has complete embeddings for this data yet. Build the dataset or finish a re-embed job in Settings,
            then query again.
          </p>
        )}
        <div className="confirm-actions">
          <button type="button" className="secondary" onClick={onCancel}>
            Cancel query
          </button>
        </div>
      </div>
    </div>
  )
}
