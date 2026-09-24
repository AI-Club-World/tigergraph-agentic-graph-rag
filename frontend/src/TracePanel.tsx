import { Icon } from './components/Icon'
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
    <section className="panel-x trace-panel">
      <header className="panel-x-head">
        <div className="panel-x-title">
          <Icon name="tree" size={22} className="agentic" />
          <div>
            <h3>Agentic investigation trace</h3>
            <p className="panel-x-sub">Autonomous execution graph with tool telemetry</p>
          </div>
        </div>
        <div className={steps.length ? 'trace-summary live' : 'trace-summary'}>
          <span className="dot" aria-hidden="true" />
          <span>{steps.length} steps</span>
          <span aria-hidden="true">·</span>
          <span>{num(totalTokens)} tokens</span>
          <span aria-hidden="true">·</span>
          <span>{changes} strategy {changes === 1 ? 'change' : 'changes'}</span>
        </div>
      </header>

      {!steps.length && (
        <p className="muted trace-empty">
          {running ? 'Waiting for the first step…' : 'No trace yet. Submit a query to watch the agent work.'}
        </p>
      )}

      <ol className="trace-steps">
        {steps.map((step) => (
          <li key={step.step_n} className={step.strategy_change ? 'step strategy-change' : 'step'}>
            <span className="step-n">{step.step_n}</span>
            <div className="step-body">
              <div className="step-head">
                <span className="agent-type">{titleCase(step.agent_type)}</span>
                <code className="tool">tool: {step.tool_called}</code>
                {step.strategy_change && (
                  <span className="strategy-flag">
                    <Icon name="sync" size={12} />
                    strategy change
                  </span>
                )}
                <div className="step-metrics">
                  <span title={`input ${num(step.tokens.input)} / output ${num(step.tokens.output)}`}>
                    <Icon name="tokens" size={13} />
                    {num(step.tokens.input + step.tokens.output)} tokens
                  </span>
                  <span>
                    <Icon name="clock" size={13} />
                    {ms(step.latency_ms)}
                  </span>
                  <span>
                    <Icon name="layers" size={13} />
                    {num(step.chunks_returned)} chunks
                  </span>
                  <span>
                    <Icon name="link" size={13} />
                    {num(step.citations_count)} citations
                  </span>
                </div>
              </div>
              <p className="step-notes">{step.notes}</p>
            </div>
          </li>
        ))}
      </ol>

      {running && steps.length > 0 && (
        <p className="muted trace-empty">
          <Icon name="sync" size={13} className="spin" /> Investigating…
        </p>
      )}

      {stopReason && (
        <footer className="trace-foot">
          <span className="foot-label">Stop reason:</span>
          <code className="tag tag-gain">{stopReason}</code>
          {strategyChanged !== null && (
            <>
              <span className="foot-label">Plan deviated:</span>
              <span className={strategyChanged ? 'tag tag-strategy' : 'tag'}>{strategyChanged ? 'Yes' : 'No'}</span>
            </>
          )}
        </footer>
      )}
    </section>
  )
}
