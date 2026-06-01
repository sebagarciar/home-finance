import { useMemo } from 'react'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { useCurrency } from '../lib/currency'
import { useSpendingSummary } from '../api/hooks'
import { categoryStyle, categoryColorHex } from '../design/categories'
import { chart } from '../design/chartTheme'
import { MoneyTooltip } from '../components/MoneyTooltip'
import { HouseholdHealth } from '../components/HouseholdHealth'
import { MonthlyStackedBar } from '../components/MonthlyStackedBar'
import { CategoryMonthTable } from '../components/CategoryMonthTable'

export function Dashboard() {
  const { format, formatCompact } = useCurrency()
  const { data: summary, isLoading: loading } = useSpendingSummary()

  const flow = useMemo(() => {
    if (!summary) return []
    const incomeMap = Object.fromEntries(summary.by_month_income.map((r) => [r.month, Number(r.total)]))
    const months = Array.from(
      new Set([...summary.by_month.map((m) => m.month), ...summary.by_month_income.map((m) => m.month)]),
    ).sort()
    return months.map((m) => {
      const spend = Number(summary.by_month.find((x) => x.month === m)?.total ?? 0)
      const income = incomeMap[m] ?? 0
      return { month: monthShort(m), spend, income, net: income - spend }
    })
  }, [summary])

  const categories = useMemo(() => {
    if (!summary) return []
    return [...summary.by_category]
      .map((c) => ({ category: c.category, total: Number(c.total) }))
      .filter((c) => c.total > 0)
      .sort((a, b) => b.total - a.total)
  }, [summary])

  const totalSpend = categories.reduce((s, c) => s + c.total, 0)

  if (loading) return <DashboardSkeleton />
  if (!summary || (flow.length === 0 && categories.length === 0)) {
    return (
      <div className="card">
        <div className="empty">
          No data yet. Import a bank statement to populate your dashboard.
        </div>
      </div>
    )
  }

  return (
    <>
      <HouseholdHealth />

      {/* Cash flow ─ income vs spend per month */}
      <div className="card">
        <div className="card-header">
          <div>
            <h2 className="card-title">Cash flow</h2>
            <div className="card-meta">Income vs spending, last {flow.length} months</div>
          </div>
          <Legend items={[
            { label: 'Income', color: 'var(--positive-text)' },
            { label: 'Spend', color: 'var(--negative-text)' },
          ]} />
        </div>
        <ResponsiveContainer width="100%" height={280}>
          <AreaChart data={flow} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="g-income" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#6fcf4a" stopOpacity={0.35} />
                <stop offset="100%" stopColor="#6fcf4a" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="g-spend" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#ff6b8a" stopOpacity={0.35} />
                <stop offset="100%" stopColor="#ff6b8a" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke={chart.grid.stroke} vertical={false} />
            <XAxis dataKey="month" {...chart.axis} dy={6} />
            <YAxis {...chart.axis} tickFormatter={(v) => formatCompact(Number(v))} width={56} />
            <Tooltip
              cursor={chart.cursor}
              content={<MoneyTooltip format={format} multi />}
            />
            <Area
              type="monotone" dataKey="income" name="Income"
              stroke="#6fcf4a" strokeWidth={2} fill="url(#g-income)"
            />
            <Area
              type="monotone" dataKey="spend" name="Spend"
              stroke="#ff6b8a" strokeWidth={2} fill="url(#g-spend)"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Monthly spending comparison (stacked by category) + top categories */}
      <div className="grid-2">
        <div className="card">
          <div className="card-header">
            <h2 className="card-title">Spending by month</h2>
            <span className="card-meta">Stacked by category</span>
          </div>
          <MonthlyStackedBar data={summary.by_month_category} />
        </div>

        <div className="card">
          <div className="card-header">
            <h2 className="card-title">Top categories</h2>
            <span className="card-meta">This period</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {categories.slice(0, 6).map((c) => {
              const style = categoryStyle(c.category)
              const pct = totalSpend > 0 ? (c.total / totalSpend) * 100 : 0
              return (
                <div key={c.category}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                    <span
                      className="category-pill"
                      style={{
                        color: style.color,
                        background: 'transparent',
                      }}
                    >
                      <span className="dot" />
                      {style.label}
                    </span>
                    <span className="num" style={{ fontSize: 13, fontWeight: 600 }}>
                      {format(c.total)}
                    </span>
                  </div>
                  <div
                    style={{
                      height: 6,
                      borderRadius: 999,
                      background: 'var(--surface-raised)',
                      overflow: 'hidden',
                    }}
                  >
                    <div
                      style={{
                        height: '100%',
                        width: `${pct}%`,
                        background: categoryColorHex(c.category),
                        borderRadius: 999,
                      }}
                    />
                  </div>
                </div>
              )
            })}
            {categories.length === 0 && <div className="empty">Nothing to show.</div>}
          </div>
        </div>
      </div>

      {/* Category × month matrix */}
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Monthly breakdown</h2>
          <span className="card-meta">By category, all months</span>
        </div>
        <CategoryMonthTable data={summary.by_month_category} />
      </div>
    </>
  )
}

function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div style={{ display: 'flex', gap: 14 }}>
      {items.map((i) => (
        <span
          key={i.label}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            fontSize: 12, color: 'var(--text-muted)',
          }}
        >
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: i.color }} />
          {i.label}
        </span>
      ))}
    </div>
  )
}

function DashboardSkeleton() {
  return (
    <>
      <div className="card">
        <div className="skel" style={{ height: 18, width: 140, marginBottom: 16 }} />
        <div className="skel" style={{ height: 260 }} />
      </div>
      <div className="grid-2">
        <div className="card">
          <div className="skel" style={{ height: 18, width: 120, marginBottom: 16 }} />
          <div className="skel" style={{ height: 240 }} />
        </div>
        <div className="card">
          <div className="skel" style={{ height: 18, width: 120, marginBottom: 16 }} />
          <div className="skel" style={{ height: 240 }} />
        </div>
      </div>
    </>
  )
}

function monthShort(m: string): string {
  return new Date(`${m}-01T00:00:00`).toLocaleString('en-US', { month: 'short', year: '2-digit' })
}
