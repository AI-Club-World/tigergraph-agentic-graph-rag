import { CitationList } from './CitationList'
import { Icon } from './Icon'
import { StatusBadge } from './StatusBadge'
import { ms, num } from '../format'
import { PIPELINE_IDS, PIPELINE_LABELS, type PipelineId, type PipelineRecord } from '../types'

export interface ColumnState {
  status: 'idle' | 'running' | 'done' | 'error'
  record: PipelineRecord | null
  error: string | null
}

const SUBTITLES: Record<PipelineId, string> = {
  rag: 'Q5 vector top-k, no type filtering',
  graphrag: 'Shared intent parser, exactly one query, no loop',
  agentic_graphrag: 'Intent parse, necessity routing, evidence check, optional re-query',
}

function Stat({ label, value, sub, title }: { label: string; value: string; sub?: string; title?: string }) {
  return (
    <div className="stat" title={title}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
      {sub && <span className="stat-sub">{sub}</span>}
    </div>
  )
}

export function ResultColumn({ pipeline, state }: { pipeline: PipelineId; state: ColumnState }) {
  const { record } = state
  const index = String(PIPELINE_IDS.indexOf(pipeline) + 1).padStart(2, '0')

  return (
    <section className="pcard" data-pipeline={pipeline} data-status={state.status}>
      <header className="pcard-head">
        <div>
          <h3 className="pcard-title">
            <span className="pipe-tag">Pipeline {index}</span>
            <span className="pipe-name">{PIPELINE_LABELS[pipeline]}</span>
          </h3>
          <p className="pcard-sub">{SUBTITLES[pipeline]}</p>
        </div>
        <StatusBadge status={state.status} />
      </header>

      {state.status === 'idle' && <p className="muted pcard-pad">Submit a query to start.</p>}

      {state.status === 'running' && (
        <div className="pcard-pad">
          <div className="output-box">
            <span className="output-label">Synthesized output</span>
            <div className="skeleton tall" />
            <div className="skeleton" />
            <div className="skeleton short" />
          </div>
          <p className="muted small">Waiting on this pipeline only — the other columns render independently.</p>
        </div>
      )}

      {state.status === 'error' && (
        <div className="pcard-pad">
          <div className="error-box pad">
            <strong>Pipeline failed</strong>
            <p>{state.error ?? record?.error_detail ?? 'Unknown error'}</p>
            <p className="muted">The other two columns are unaffected.</p>
          </div>
        </div>
      )}

      {state.status === 'done' && record && (
        <>
          <div className="pcard-pad">
            <div className="output-box">
              <span className="output-label">Synthesized output</span>
              <p className="answer-text">{record.answer}</p>
              <p className="explanation">{record.explanation}</p>

              {record.token_source === 'local_tokenizer' && (
                <p className="callout warn">
                  <Icon name="warning" size={13} />
                  <span>Token counts came from the local tokenizer — the configured provider reported no usage.</span>
                </p>
              )}
              {record.token_source === 'estimated' && (
                <p className="callout warn">
                  <Icon name="warning" size={13} />
                  <span>
                    Token counts are estimates (about 4 characters per token) — the provider reported no usage and
                    the model has no tokenizer.
                  </span>
                </p>
              )}

              {record.stop_reason && (
                <p className="callout accent">
                  <Icon name="flag" size={13} />
                  <span>
                    Stopped because: <code>{record.stop_reason}</code>
                  </span>
                </p>
              )}

              {record.strategy_changed && (
                <p className="callout strategy">
                  <Icon name="fork" size={13} />
                  <span>The orchestrator deviated from its initial plan at least once.</span>
                </p>
              )}
            </div>
          </div>

          <div className="stat-grid">
            <Stat
              label="Total Tokens"
              value={num(record.tokens.total)}
              sub={`in ${num(record.tokens.input)} / out ${num(record.tokens.output)}`}
              title={`source: ${record.token_source}`}
            />
            <Stat label="Latency" value={ms(record.latency_ms)} />
            <Stat label="Retrieved Chunks" value={num(record.chunks_returned)} />
            <Stat label="Citations" value={num(record.citations_count)} />
          </div>

          <div className="citations-block">
            <span className="section-label">Provenance citations</span>
            <CitationList citations={record.citations} />
          </div>
        </>
      )}
    </section>
  )
}
