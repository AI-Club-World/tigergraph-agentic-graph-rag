import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { BenchmarksView } from './BenchmarksView'
import latest from './fixtures/batchRecords.latest.json'

function renderView() {
  return render(
    <MemoryRouter>
      <BenchmarksView />
    </MemoryRouter>,
  )
}

describe('BenchmarksView (mock transport)', () => {
  it('lists the run history with metadata and drill-down links', async () => {
    renderView()
    const latestBox = await screen.findByLabelText('Compare latest')
    const row = latestBox.closest('tr')!
    expect(within(row).getByText('eval_public')).toBeInTheDocument()
    expect(within(row).getByText('qwen2.5:7b-instruct')).toBeInTheDocument()
    expect(within(row).getByRole('link', { name: 'Dashboard' })).toHaveAttribute('href', '/benchmarks?tab=dashboard&run=latest')
    expect(screen.getByLabelText('Compare hidden')).toBeInTheDocument()
  })

  it('compares two selected runs against the first as baseline', async () => {
    renderView()
    fireEvent.click(await screen.findByLabelText('Compare latest'))
    expect(screen.queryByText(/Compare \d+ runs/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('Compare hidden'))

    const panel = screen.getByText('Compare 2 runs').closest('section')!
    expect(within(panel).getByText('baseline')).toBeInTheDocument()
    // Dataset differs between the two runs, so it is flagged as a config change.
    const datasetRow = within(panel).getByText('Dataset').closest('tr')!
    expect(within(datasetRow).getByText('eval_hidden')).toHaveClass('diff')
  })

  it('imports a past run from JSON into the history', async () => {
    renderView()
    await screen.findByLabelText('Compare latest')
    const payload = { run_id: 'past-run', run_config: { llm_model: 'older-model' }, records: latest }
    const file = new File([JSON.stringify(payload)], 'past-run.json', { type: 'application/json' })
    // jsdom's File has no text(); every browser does.
    Object.defineProperty(file, 'text', { value: async () => JSON.stringify(payload) })
    fireEvent.change(screen.getByLabelText('Import run file'), { target: { files: [file] } })

    expect(await screen.findByText(/Imported past-run/)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText('Compare past-run')).toBeChecked())
    expect(screen.getByText('older-model')).toBeInTheDocument()
  })
})
