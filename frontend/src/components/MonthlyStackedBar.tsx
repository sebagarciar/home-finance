// Horizontal stacked bar — one bar per month, segments colored by category.
// Lets you compare monthly spending and see what drove each month at a glance.
import { useMemo } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { useCurrency } from '../lib/currency'
import { categoryStyle, categoryColorHex } from '../design/categories'
import { chart } from '../design/chartTheme'
import { MoneyTooltip } from './MoneyTooltip'

type ByMonthCategory = { month: string; category: string; total: string }[]

export function MonthlyStackedBar({ data }: { data: ByMonthCategory }) {
  const { format, formatCompact } = useCurrency()

  const { rows, categories } = useMemo(() => {
    // Grand total per category → stacking order (biggest stack first).
    const totals = new Map<string, number>()
    const monthSet = new Set<string>()
    for (const r of data) {
      const v = Number(r.total)
      totals.set(r.category, (totals.get(r.category) ?? 0) + v)
      monthSet.add(r.month)
    }
    const categories = [...totals.keys()].sort((a, b) => (totals.get(b) ?? 0) - (totals.get(a) ?? 0))

    const months = [...monthSet].sort()
    const byKey = new Map(data.map((r) => [`${r.month}|${r.category}`, Number(r.total)]))
    const rows = months.map((m) => {
      const row: Record<string, number | string> = { month: monthShort(m) }
      for (const c of categories) row[c] = byKey.get(`${m}|${c}`) ?? 0
      return row
    })
    return { rows, categories }
  }, [data])

  if (rows.length === 0) {
    return <div className="empty">No spending recorded.</div>
  }

  return (
    <ResponsiveContainer width="100%" height={Math.max(220, rows.length * 44)}>
      <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
        <CartesianGrid stroke={chart.grid.stroke} horizontal={false} />
        <XAxis type="number" {...chart.axis} tickFormatter={(v) => formatCompact(Number(v))} />
        <YAxis
          type="category"
          dataKey="month"
          {...chart.axis}
          tick={{ fill: '#646876', fontSize: 12 }}
          width={64}
        />
        <Tooltip cursor={chart.cursor} content={<MoneyTooltip format={format} multi />} />
        <Legend
          iconType="circle"
          iconSize={8}
          wrapperStyle={{ fontSize: 12, color: 'var(--text-muted)', paddingTop: 8 }}
        />
        {categories.map((c) => (
          <Bar
            key={c}
            dataKey={c}
            name={categoryStyle(c).label}
            stackId="spend"
            fill={categoryColorHex(c)}
            maxBarSize={22}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}

function monthShort(m: string): string {
  return new Date(`${m}-01T00:00:00`).toLocaleString('en-US', { month: 'short', year: '2-digit' })
}
