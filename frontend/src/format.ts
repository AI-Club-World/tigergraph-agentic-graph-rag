export const num = (n: number): string => n.toLocaleString('en-US')

export const ms = (n: number): string => (n < 1000 ? `${Math.round(n)} ms` : `${(n / 1000).toFixed(2)} s`)

export const pct = (n: number): string => `${(n * 100).toFixed(0)}%`

export const dec = (n: number, places = 2): string => n.toFixed(places)

export const signed = (n: number, places = 2): string => `${n > 0 ? '+' : ''}${n.toFixed(places)}`

export const titleCase = (s: string): string => s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

export function mean(values: number[]): number {
  return values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0
}

export function median(values: number[]): number {
  if (!values.length) return 0
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}
