import type { Citation } from '../types'

export function CitationList({ citations }: { citations: Citation[] }) {
  if (!citations.length) return <p className="muted small">No citations returned.</p>

  return (
    <ul className="citations">
      {citations.map((citation, i) => (
        <li key={`${citation.source_id}-${citation.chunk_id ?? i}`} className="cite">
          <span className={`ref-type ref-${citation.ref_type}`}>{citation.ref_type}</span>
          <code title="Parent doc_id (wikidata QID) — this is the field scored against gold_doc_ids">
            {citation.source_id}
          </code>
          {citation.chunk_id && <span className="chunk-id">{citation.chunk_id}</span>}
        </li>
      ))}
    </ul>
  )
}
