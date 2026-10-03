// Shared goal helpers (Forecast page + chart markers).

/** ≥80% likely reads as on track, 50–80% as uncertain, below as at risk. */
export function probColor(p: number | null): string {
  if (p == null) return 'var(--text-faint)'
  return p >= 0.8 ? 'var(--positive-text)' : p >= 0.5 ? 'var(--pending-text)' : 'var(--negative-text)'
}

export function monthLabel(ym: string): string {
  return new Date(`${ym}-01T00:00:00`).toLocaleString('en-US', { month: 'short', year: 'numeric' })
}
