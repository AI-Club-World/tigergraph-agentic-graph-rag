export function BarChart({
  data,
  color = 'var(--accent)',
}: {
  data: Array<{ label: string; value: number }>
  color?: string
}) {
  if (!data.length) return <p className="muted">No data.</p>
  const max = Math.max(...data.map((d) => d.value), 1)

  return (
    <div className="bar-chart">
      {data.map((d) => (
        <div className="bar-row" key={d.label}>
          <span className="bar-label" title={d.label}>{d.label}</span>
          <div className="bar-track">
            <div
              className="bar-fill"
              style={{ width: `${(d.value / max) * 100}%`, background: color }}
            />
          </div>
          <span className="bar-value">{d.value}</span>
        </div>
      ))}
    </div>
  )
}

export interface ScatterSeries {
  name: string
  color: string
  points: Array<{ x: number; y: number; label: string }>
}

export function ScatterPlot({
  series,
  xLabel,
  yLabel,
}: {
  series: ScatterSeries[]
  xLabel: string
  yLabel: string
}) {
  const all = series.flatMap((s) => s.points)
  if (!all.length) return <p className="muted">No data.</p>

  const w = 640
  const h = 300
  const pad = { top: 16, right: 16, bottom: 44, left: 52 }
  const xMax = Math.max(...all.map((p) => p.x)) * 1.05
  const plotW = w - pad.left - pad.right
  const plotH = h - pad.top - pad.bottom
  const sx = (x: number) => pad.left + (x / xMax) * plotW
  const sy = (y: number) => pad.top + plotH - y * plotH

  const yTicks = [0, 0.25, 0.5, 0.75, 1]
  const xTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => Math.round((xMax * f) / 100) * 100)

  return (
    <figure className="scatter">
      <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`${yLabel} against ${xLabel}`}>
        {yTicks.map((t) => (
          <g key={`y${t}`}>
            <line x1={pad.left} x2={w - pad.right} y1={sy(t)} y2={sy(t)} className="grid" />
            <text x={pad.left - 8} y={sy(t) + 4} className="tick" textAnchor="end">
              {t.toFixed(2)}
            </text>
          </g>
        ))}
        {xTicks.map((t) => (
          <text key={`x${t}`} x={sx(t)} y={h - pad.bottom + 18} className="tick" textAnchor="middle">
            {t.toLocaleString('en-US')}
          </text>
        ))}
        {series.map((s) =>
          s.points.map((p, i) => (
            <circle
              key={`${s.name}-${i}`}
              cx={sx(p.x)}
              cy={sy(p.y)}
              r={5}
              style={{ fill: s.color, stroke: s.color }}
              fillOpacity={0.7}
            >
              <title>{`${s.name} — ${p.label}\n${xLabel}: ${p.x.toLocaleString('en-US')}\n${yLabel}: ${p.y.toFixed(2)}`}</title>
            </circle>
          )),
        )}
        <text x={pad.left + plotW / 2} y={h - 6} className="axis-label" textAnchor="middle">
          {xLabel}
        </text>
        <text
          x={-(pad.top + plotH / 2)}
          y={14}
          className="axis-label"
          textAnchor="middle"
          transform="rotate(-90)"
        >
          {yLabel}
        </text>
      </svg>
      <figcaption className="legend">
        {series.map((s) => (
          <span key={s.name}>
            <i style={{ background: s.color }} /> {s.name}
          </span>
        ))}
      </figcaption>
      <details className="chart-data">
        <summary>Show data table</summary>
        <table className="matrix">
          <thead>
            <tr>
              <th scope="col">Series</th>
              <th scope="col">Point</th>
              <th scope="col">{xLabel}</th>
              <th scope="col">{yLabel}</th>
            </tr>
          </thead>
          <tbody>
            {series.flatMap((s) =>
              s.points.map((p, i) => (
                <tr key={`${s.name}-${i}`}>
                  <th scope="row">{s.name}</th>
                  <td>{p.label}</td>
                  <td>{p.x.toLocaleString('en-US')}</td>
                  <td>{p.y.toFixed(2)}</td>
                </tr>
              )),
            )}
          </tbody>
        </table>
      </details>
    </figure>
  )
}
