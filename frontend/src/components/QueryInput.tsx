import { useState, type FormEvent } from 'react'
import { Icon } from './Icon'

const EXAMPLES = [
  'How many archery events were contested at the 2012 Summer Olympics?',
  'Who took gold in the men’s 100 metres in Rio?',
  'Which nation won the most gold medals in athletics at the Games immediately before the 2012 Summer Olympics?',
]

interface Props {
  onSubmit: (query: string) => void
  disabled: boolean
}

export function QueryInput({ onSubmit, disabled }: Props) {
  const [value, setValue] = useState('')

  function submit(event: FormEvent) {
    event.preventDefault()
    const query = value.trim()
    if (query) onSubmit(query)
  }

  return (
    <form className="query-input" onSubmit={submit}>
      <div className="query-row">
        <label className="query-field">
          <Icon name="terminal" size={18} />
          <input
            type="text"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Ask one question of all three pipelines"
            aria-label="Query"
          />
        </label>
        <button type="submit" className="btn-primary" disabled={disabled || !value.trim()}>
          <Icon name={disabled ? 'sync' : 'play'} size={14} className={disabled ? 'spin' : 'filled'} />
          {disabled ? 'Running…' : 'Compare'}
        </button>
      </div>
      <div className="presets">
        <span className="presets-label">Presets:</span>
        {EXAMPLES.map((example) => (
          <button
            key={example}
            type="button"
            className={value === example ? 'preset active' : 'preset'}
            aria-pressed={value === example}
            disabled={disabled}
            onClick={() => {
              setValue(example)
              onSubmit(example)
            }}
          >
            {example}
          </button>
        ))}
      </div>
    </form>
  )
}
