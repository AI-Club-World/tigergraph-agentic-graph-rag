import { useState } from 'react'
import type { Citation } from '../types'

/** Citation chips. A chip with evidence text is a toggle: selecting it shows
 *  what was cited (the same text the grounding score checks) in a preview
 *  under the list. Hover gives a quick look; the preview works on touch. */
export function CitationList({ citations }: { citations: Citation[] }) {
  const [open, setOpen] = useState<number | null>(null)
  if (!citations.length) return <p className="muted small">No citations returned.</p>

  const selected = open === null ? null : citations[open]
  return (
    <>
      <ul className="citations">
        {citations.map((citation, i) => {
          const body = (
            <>
              <span className={`ref-type ref-${citation.ref_type}`}>{citation.ref_type}</span>
              <code>{citation.source_id}</code>
              {citation.chunk_id && <span className="chunk-id">{citation.chunk_id}</span>}
            </>
          )
          return (
            <li key={`${citation.source_id}-${citation.chunk_id ?? i}`} className="cite">
              {citation.snippet ? (
                <button
                  type="button"
                  className="cite-toggle"
                  aria-pressed={open === i}
                  title={citation.snippet.slice(0, 200)}
                  onClick={() => setOpen(open === i ? null : i)}
                >
                  {body}
                </button>
              ) : (
                <span className="cite-toggle" title="Parent doc_id (wikidata QID), scored against gold_doc_ids">
                  {body}
                </span>
              )}
            </li>
          )
        })}
      </ul>
      {selected?.snippet && (
        <blockquote className="cite-preview" aria-live="polite">
          <span className="cite-preview-source">
            {selected.source_id}
            {selected.chunk_id ? ` · ${selected.chunk_id}` : ''}
          </span>
          {selected.snippet}
        </blockquote>
      )}
    </>
  )
}
