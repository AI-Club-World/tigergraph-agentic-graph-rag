import { useState, type FormEvent } from 'react'

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
        <input
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Ask one question of all three pipelines"
          aria-label="Query"
        />
        <button type="submit" disabled={disabled || !value.trim()}>
          {disabled ? 'Running…' : 'Compare'}
        </button>
      </div>
      <div className="examples">
        <span className="muted">Try:</span>
        {EXAMPLES.map((example) => (
          <button
            key={example}
            type="button"
            className="link"
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
