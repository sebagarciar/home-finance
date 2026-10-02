// Card-style Recharts tooltip used across all charts.

import type { ReactNode } from 'react'

interface Entry {
  name?: string
  value?: number | string
  color?: string
  dataKey?: string
}

interface Props {
  active?: boolean
  payload?: Entry[]
  label?: ReactNode
  format: (n: number) => string
  /** Show series name + dot for each row (stacked charts). Single-series omits. */
  multi?: boolean
}

export function MoneyTooltip({ active, payload, label, format, multi }: Props) {
  if (!active || !payload?.length) return null
  const rows = multi
    ? [...payload].sort((a, b) => Number(b.value ?? 0) - Number(a.value ?? 0)).filter((p) => Number(p.value ?? 0) > 0)
    : payload

  return (
    <div
      style={{
        background: 'var(--surface)',
        border: '1px solid var(--surface-border)',
        borderRadius: 12,
        padding: '10px 14px',
        minWidth: 160,
        boxShadow: '0 8px 24px rgba(29,31,38,0.12)',
      }}
    >
      {label != null && (
        <div style={{ color: 'var(--text-muted)', fontSize: 11, marginBottom: 8, fontWeight: 500 }}>
          {label}
        </div>
      )}
      {rows.map((p, i) => (
        <div
          key={i}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 16,
            padding: '2px 0',
          }}
        >
          {multi && (
            <span style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--text-secondary)', fontSize: 12 }}>
              <span
                style={{
                  width: 8, height: 8, borderRadius: '50%',
                  background: p.color ?? 'var(--text-muted)',
                }}
              />
              {p.name}
            </span>
          )}
          <span
            className="num"
            style={{ color: 'var(--text-primary)', fontWeight: 600, fontSize: 13, marginLeft: 'auto' }}
          >
            {format(Number(p.value ?? 0))}
          </span>
        </div>
      ))}
    </div>
  )
}
