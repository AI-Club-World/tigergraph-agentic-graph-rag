import { useSearchParams } from 'react-router-dom'
import { BenchmarksView } from './BenchmarksView'
import { Dashboard } from './Dashboard'
import { EvalTable } from './EvalTable'

const TABS = [
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'runs', label: 'Run benchmark' },
  { id: 'eval', label: 'Eval table' },
] as const
type TabId = (typeof TABS)[number]['id']

/** The Dashboard page: charts for a selected run, benchmark execution
 *  (run/history/compare/import), and the per-question eval table. `?tab=`
 *  keeps the tab linkable; `?run=` selects the run for charts and table. */
export function DashboardPage() {
  const [params, setParams] = useSearchParams()
  const requested = params.get('tab')
  const tab: TabId = TABS.some((t) => t.id === requested) ? (requested as TabId) : 'dashboard'

  function select(next: TabId) {
    const updated = new URLSearchParams(params)
    updated.set('tab', next)
    setParams(updated)
  }

  return (
    <div className="bench-page">
      <div className="tabs" role="tablist" aria-label="Dashboard">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls={`panel-${t.id}`}
            className={tab === t.id ? 'tab active' : 'tab'}
            onClick={() => select(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === 'dashboard' ? <Dashboard /> : tab === 'runs' ? <BenchmarksView /> : <EvalTable />}
      </div>
    </div>
  )
}
