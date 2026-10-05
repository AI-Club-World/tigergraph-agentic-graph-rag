type Status = 'idle' | 'running' | 'done' | 'error' | 'ready'

const LABELS: Record<Status, string> = {
  idle: 'Idle',
  running: 'Running',
  done: 'Done',
  error: 'Error',
  ready: 'Ready',
}

export function StatusBadge({ status }: { status: Status }) {
  return (
    <span className={`badge badge-${status}`}>
      {status === 'running' && <span className="spinner" aria-hidden="true" />}
      {LABELS[status]}
    </span>
  )
}
