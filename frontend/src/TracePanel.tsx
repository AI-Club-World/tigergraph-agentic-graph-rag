import { ms, num, titleCase } from './format'
import type { TraceStep } from './types'

interface Props {
  steps: TraceStep[]
  running: boolean
  stopReason: string | null
  strategyChanged: boolean | null
}

export function TracePanel({ steps, running, stopReason, strategyChanged }: Props) {
  const totalTokens = steps.reduce((sum, s) => sum + s.tokens.input + s.tokens.output, 0)
  const changes = steps.filter((s) => s.strategy_change).length

  return (
    <section className="trace-panel">
      <header className="trace-head">
        <h3>Agentic investigation trace</h3>
        <div className="trace-summary">
          <span>{steps.length} steps</span>
          <span>{num(totalTokens)} tokens</span>
          <span>{changes} strategy {changes === 1 ? 'change' : 'changes'}</span>
        </div>
      </header>

      {!steps.length && (
        <p className="muted pad">
          {running ? 'Waiting for the first step…' : 'No trace yet. Submit a query to watch the agent work.'}
        </p>
      )}

      <ol className="trace-steps">
        {steps.map((step) => (
          <li key={step.step_n} className={step.strategy_change ? 'step strategy-change' : 'step'}>
            <div className="step-head">
              <span className="step-n">{step.step_n}</span>
              <span className="agent-type">{titleCase(step.agent_type)}</span>
              <code className="tool">{step.tool_called}</code>
              {step.strategy_change && <span className="strategy-flag">strategy change</span>}
            </div>
            <p className="step-notes">{step.notes}</p>
            <div className="step-metrics">
              <span title={`input ${num(step.tokens.input)} / output ${num(step.tokens.output)}`}>
                {num(step.tokens.input + step.tokens.output)} tokens
              </span>
              <span>{ms(step.latency_ms)}</span>
              <span>{num(step.chunks_returned)} chunks</span>
              <span>{num(step.citations_count)} citations</span>
            </div>
          </li>
        ))}
      </ol>

      {running && steps.length > 0 && <p className="muted pad">Investigating…</p>}

      {stopReason && (
        <footer className="trace-foot">
          <span className="label">Stop reason</span>
          <code>{stopReason}</code>
          {strategyChanged && <span className="strategy-flag">plan deviated</span>}
        </footer>
      )}
    </section>
  )
}
