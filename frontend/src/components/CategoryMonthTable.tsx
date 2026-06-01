// Spreadsheet-style matrix: months down, categories across, with row + column
// totals. Mirrors the layout Seba keeps in his own sheet.
import { useMemo } from 'react'
import { useCurrency } from '../lib/currency'
import { categoryStyle } from '../design/categories'

type ByMonthCategory = { month: string; category: string; total: string }[]

export function CategoryMonthTable({ data }: { data: ByMonthCategory }) {
  const { format, formatCompact } = useCurrency()

  const { months, categories, cell, rowTotal, colTotal, grand } = useMemo(() => {
    const totals = new Map<string, number>()
    const monthSet = new Set<string>()
    const cell = new Map<string, number>()
    for (const r of data) {
      const v = Number(r.total)
      totals.set(r.category, (totals.get(r.category) ?? 0) + v)
      monthSet.add(r.month)
      cell.set(`${r.month}|${r.category}`, v)
    }
    // Same ordering as the stacked bar: biggest category first.
    const categories = [...totals.keys()].sort((a, b) => (totals.get(b) ?? 0) - (totals.get(a) ?? 0))
    const months = [...monthSet].sort()

    const rowTotal = new Map<string, number>()
    for (const m of months) {
      let t = 0
      for (const c of categories) t += cell.get(`${m}|${c}`) ?? 0
      rowTotal.set(m, t)
    }
    const colTotal = new Map(categories.map((c) => [c, totals.get(c) ?? 0]))
    const grand = [...rowTotal.values()].reduce((s, v) => s + v, 0)
    return { months, categories, cell, rowTotal, colTotal, grand }
  }, [data])

  if (months.length === 0) {
    return <div className="empty">No spending recorded.</div>
  }

  return (
    <div className="matrix-scroll">
      <table className="matrix-table">
        <thead>
          <tr>
            <th className="month-col">Month</th>
            {categories.map((c) => {
              const s = categoryStyle(c)
              return (
                <th key={c} className="num-col">
                  <span className="dot" style={{ background: s.color }} />
                  {s.label}
                </th>
              )
            })}
            <th className="num-col total-col">Total</th>
          </tr>
        </thead>
        <tbody>
          {months.map((m) => (
            <tr key={m}>
              <td className="month-col">{monthLong(m)}</td>
              {categories.map((c) => {
                const v = cell.get(`${m}|${c}`) ?? 0
                return (
                  <td key={c} className="num num-col" style={v === 0 ? { color: 'var(--text-muted)' } : undefined}>
                    {formatCompact(v)}
                  </td>
                )
              })}
              <td className="num num-col total-col">{format(rowTotal.get(m) ?? 0)}</td>
            </tr>
          ))}
          <tr className="total-row">
            <td className="month-col">TOTAL</td>
            {categories.map((c) => (
              <td key={c} className="num num-col">{format(colTotal.get(c) ?? 0)}</td>
            ))}
            <td className="num num-col total-col">{format(grand)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}

function monthLong(m: string): string {
  return new Date(`${m}-01T00:00:00`).toLocaleString('en-US', { month: 'long', year: 'numeric' })
}
