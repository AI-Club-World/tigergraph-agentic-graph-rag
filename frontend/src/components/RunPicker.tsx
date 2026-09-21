import { useState, type FormEvent } from 'react'

interface Props {
  runId: string
  onChange: (runId: string) => void
}

export function RunPicker({ runId, onChange }: Props) {
  const [value, setValue] = useState(runId)

  function submit(event: FormEvent) {
    event.preventDefault()
    if (value.trim()) onChange(value.trim())
  }

  return (
    <form className="run-picker" onSubmit={submit}>
      <label htmlFor="run-id">Run</label>
      <input id="run-id" value={value} onChange={(e) => setValue(e.target.value)} />
      <button type="submit">Load</button>
    </form>
  )
}
