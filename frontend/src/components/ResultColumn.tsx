import { CitationList } from './CitationList'
import { StatusBadge } from './StatusBadge'
import { ms, num } from '../format'
import { PIPELINE_LABELS, type PipelineId, type PipelineRecord } from '../types'

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

export function ResultColumn({ pipeline, state }: { pipeline: PipelineId; state: ColumnState }) {
  const { record } = state

  return (
    <section className="column" data-pipeline={pipeline} data-status={state.status}>
      <header className="column-head">
        <div>
          <h3>{PIPELINE_LABELS[pipeline]}</h3>
          <p className="muted">{SUBTITLES[pipeline]}</p>
        </div>
        <StatusBadge status={state.status} />
      </header>

      {state.status === 'idle' && <p className="muted pad">Submit a query to start.</p>}

      {state.status === 'running' && (
        <div className="pad">
          <div className="skeleton" />
          <div className="skeleton short" />
          <p className="muted">Waiting on this pipeline only — the other columns render independently.</p>
        </div>
      )}

      {state.status === 'error' && (
        <div className="pad error-box">
          <strong>Pipeline failed</strong>
          <p>{state.error ?? record?.error_detail ?? 'Unknown error'}</p>
          <p className="muted">The other two columns are unaffected.</p>
        </div>
      )}

      {state.status === 'done' && record && (
        <>
          <div className="answer">
            <span className="label">Answer</span>
            <p className="answer-text">{record.answer}</p>
          </div>

          <p className="explanation">{record.explanation}</p>

          <div className="metrics">
            <div
              className="metric"
              title={`input ${num(record.tokens.input)} / output ${num(record.tokens.output)} — source: ${record.token_source}`}
            >
              <span className="metric-value">{num(record.tokens.total)}</span>
              <span className="metric-label">tokens</span>
            </div>
            <div className="metric">
              <span className="metric-value">{ms(record.latency_ms)}</span>
              <span className="metric-label">latency</span>
            </div>
            <div className="metric">
              <span className="metric-value">{num(record.chunks_returned)}</span>
              <span className="metric-label">chunks</span>
            </div>
            <div className="metric">
              <span className="metric-value">{num(record.citations_count)}</span>
              <span className="metric-label">citations</span>
            </div>
          </div>

          {record.token_source === 'local_tokenizer' && (
            <p className="note">
              Token counts came from the local tokenizer — the configured provider reported no usage.
            </p>
          )}
          {record.token_source === 'estimated' && (
            <p className="note">
              Token counts are estimates (about 4 characters per token) — the provider reported no usage and the model has no tokenizer.
            </p>
          )}

          {record.stop_reason && (
            <p className="stop-reason">
              <span className="label">Stopped because</span> <code>{record.stop_reason}</code>
            </p>
          )}

          {record.strategy_changed && (
            <p className="note strategy">The orchestrator deviated from its initial plan at least once.</p>
          )}

          <div className="citations-block">
            <span className="label">Citations</span>
            <CitationList citations={record.citations} />
          </div>
        </>
      )}
    </section>
  )
}
