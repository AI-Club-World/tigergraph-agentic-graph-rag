import { dec, signed } from '../format'
import type { Verdict } from '../types'

function Delta({ value }: { value: number | 'n/a' }) {
  if (value === 'n/a') {
    return <span className="metric-value na" title="No ground truth available for this query">N/A</span>
  }
  const tone = value > 0 ? 'gain' : value < 0 ? 'loss' : 'flat'
  return <span className={`metric-value ${tone}`}>{signed(value)}</span>
}

export function VerdictStrip({ verdict }: { verdict: Verdict }) {
  return (
    <section className="verdict">
      <div className="verdict-metrics">
        <div className="metric">
          <span className="metric-value">{dec(verdict.token_multiplier_vs_rag)}&times;</span>
          <span className="metric-label">Agentic tokens &divide; RAG</span>
        </div>
        <div className="metric">
          <span className="metric-value">{dec(verdict.token_multiplier_vs_graphrag)}&times;</span>
          <span className="metric-label">Agentic tokens &divide; GraphRAG</span>
        </div>
        <div className="metric">
          <Delta value={verdict.accuracy_delta_vs_rag} />
          <span className="metric-label">Accuracy delta vs RAG</span>
        </div>
        <div className="metric">
          <Delta value={verdict.accuracy_delta_vs_graphrag} />
          <span className="metric-label">Accuracy delta vs GraphRAG</span>
        </div>
      </div>
      <p className="verdict-summary">{verdict.summary_line}</p>
    </section>
  )
}
