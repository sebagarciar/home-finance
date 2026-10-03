// Native-currency / quantity / date formatting shared by the Portfolio views.
// Base-currency money goes through `useCurrency().format` instead.

export function fmtQty(q: string) {
  const n = Number(q)
  if (!Number.isFinite(n)) return q
  return n.toLocaleString('es-CL', { maximumFractionDigits: 4 })
}

export function fmtNative(amount: string, currency: string) {
  const n = Number(amount)
  if (!Number.isFinite(n)) return amount
  // CLP has no minor unit in practice — render whole pesos. Other currencies
  // get standard 2dp (and up to 4 for tiny crypto-like fractions).
  const opts =
    currency === 'CLP'
      ? { maximumFractionDigits: 0 }
      : { minimumFractionDigits: 2, maximumFractionDigits: 4 }
  return `${n.toLocaleString('es-CL', opts)} ${currency}`
}

export function shortDate(iso: string) {
  const d = new Date(`${iso}T00:00:00`)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

/** Signed percentage from a fraction: 0.123 → "+12.3%". */
export function fmtPct(rate: number) {
  const sign = rate > 0 ? '+' : rate < 0 ? '−' : ''
  return `${sign}${Math.abs(rate * 100).toFixed(1)}%`
}
