import { useSearchParams } from 'react-router-dom'
import { BenchmarksView } from './BenchmarksView'
import { Dashboard } from './Dashboard'

const TABS = [
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'runs', label: 'Run benchmark' },
] as const
type TabId = (typeof TABS)[number]['id']

/** One page for benchmark results and benchmark execution: the dashboard of
 *  a selected run, and the run/history/compare/import controls. `?tab=`
 *  keeps the tab linkable; `?run=` keeps selecting the dashboard's run. */
export function BenchmarksPage() {
  const [params, setParams] = useSearchParams()
  const tab: TabId = params.get('tab') === 'runs' ? 'runs' : 'dashboard'

  function select(next: TabId) {
    const updated = new URLSearchParams(params)
    updated.set('tab', next)
    setParams(updated)
  }

  return (
    <div className="bench-page">
      <div className="tabs" role="tablist" aria-label="Benchmarks">
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
        {tab === 'dashboard' ? <Dashboard /> : <BenchmarksView />}
      </div>
    </div>
  )
}
