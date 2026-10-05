import { Icon } from './Icon'
import { dec, signed } from '../format'
import type { Verdict } from '../types'

/** Token-ratio bars are drawn on a fixed 0–5× scale so the two cards compare. */
const RATIO_SCALE = 5

const clamp = (n: number) => Math.max(0, Math.min(1, n))

function Bar({ fraction, tone }: { fraction: number; tone: string }) {
  return (
    <div className="vcard-track" aria-hidden="true">
      <div className={`vcard-fill fill-${tone}`} style={{ width: `${Math.round(clamp(fraction) * 100)}%` }} />
    </div>
  )
}

function RatioCard({ label, value, tone }: { label: string; value: number | null; tone: 'rag' | 'graphrag' }) {
  if (value === null || value === undefined) {
    return (
      <div className="vcard" title="No cost ratio: a pipeline errored, or the baseline spent no tokens">
        <span className="vcard-label">{label}</span>
        <span className="vcard-value">N/A<span className="vcard-unit">no cost ratio</span></span>
      </div>
    )
  }
  return (
    <div className="vcard" title={`Bar scale 0–${RATIO_SCALE}×`}>
      <span className="vcard-label">{label}</span>
      <span className="vcard-value">
        {dec(value)}&times;<span className="vcard-unit">overhead ratio</span>
      </span>
      <Bar fraction={value / RATIO_SCALE} tone={tone} />
    </div>
  )
}

function DeltaCard({ label, value }: { label: string; value: number | 'n/a' }) {
  if (value === 'n/a') {
    return (
      <div className="vcard">
        <span className="vcard-label">{label}</span>
        <span className="vcard-value na" title="No ground truth available for this query">N/A</span>
        <Bar fraction={0} tone="flat" />
      </div>
    )
  }
  const tone = value > 0 ? 'gain' : value < 0 ? 'loss' : 'flat'
  return (
    <div className="vcard">
      <span className="vcard-label">{label}</span>
      <span className={`vcard-value ${tone}`}>
        {signed(value)}
        {tone !== 'flat' && (
          <span className={`delta-tag ${tone}`}>{tone === 'gain' ? '▲ gain' : '▼ loss'}</span>
        )}
      </span>
      <Bar fraction={Math.abs(value)} tone={tone} />
    </div>
  )
}

export function VerdictStrip({ verdict }: { verdict: Verdict }) {
  const scored = verdict.accuracy_delta_vs_rag !== 'n/a' || verdict.accuracy_delta_vs_graphrag !== 'n/a'

  return (
    <section className="panel-x verdict">
      <header className="panel-x-head">
        <h3 className="panel-x-title">
          <span className="icon-box gain">
            <Icon name="checkCircle" size={16} />
          </span>
          {scored ? 'Verdict: completed with ground truth evaluation' : 'Verdict: completed without ground truth'}
        </h3>
        <span className={scored ? 'tag tag-gain' : 'tag tag-warn'}>
          {scored ? 'ground_truth_match' : 'no_ground_truth'}
        </span>
      </header>

      <div className="verdict-grid">
        <RatioCard label="Agentic tokens ÷ RAG" value={verdict.token_multiplier_vs_rag} tone="rag" />
        <RatioCard label="Agentic tokens ÷ GraphRAG" value={verdict.token_multiplier_vs_graphrag} tone="graphrag" />
        <DeltaCard label="Accuracy delta vs RAG" value={verdict.accuracy_delta_vs_rag} />
        <DeltaCard label="Accuracy delta vs GraphRAG" value={verdict.accuracy_delta_vs_graphrag} />
      </div>

      <p className="verdict-line">
        <Icon name="sparkle" size={18} className="gain" />
        <span>{verdict.summary_line}</span>
      </p>
    </section>
  )
}
