import type { LiquidityDiagnostics } from '../../api/client'

export function LiquiditySection({ liq, format }: { liq: LiquidityDiagnostics; format: (n: number) => string }) {
  const cashNum = Number(liq.cash_clp)
  const expNum = Number(liq.monthly_expenses_clp)
  const efCurrent = liq.ef_months_current
  const efTarget = liq.ef_months_target
  const nearTermNum = Number(liq.near_term_large_expenses_clp)
  const gapNum = Number(liq.cash_gap_clp)

  // colour the EF bar: green ≥ target, amber 1–target, red < 1
  const efColor =
    efCurrent === null ? 'var(--text-muted)'
    : efCurrent >= efTarget ? 'var(--positive-text)'
    : efCurrent >= 1 ? 'var(--pending-text)'
    : 'var(--negative-text)'

  const efFillPct = efCurrent === null ? 0 : Math.min((efCurrent / efTarget) * 100, 100)

  return (
    <div className="card">
      <div className="card-header">
        <h2 className="card-title">Liquidity &amp; emergency fund</h2>
        {!liq.data_available && (
          <span className="phr-sev sev-low">needs monthly spending</span>
        )}
      </div>
      <div className="networth-tiles">
        <div className="networth-tile">
          <div className="tile-label">Liquid cash</div>
          <div className="tile-value num">{format(cashNum)}</div>
        </div>
        {liq.data_available && (
          <div className="networth-tile">
            <div className="tile-label">Monthly expenses</div>
            <div className="tile-value num">{format(expNum)}</div>
          </div>
        )}
        {efCurrent !== null && (
          <div className="networth-tile">
            <div className="tile-label">Emergency fund</div>
            <div className="tile-value num" style={{ color: efColor }}>
              {efCurrent.toFixed(1)} mo
            </div>
            <div className="card-meta">target: {efTarget.toFixed(1)} mo</div>
            <div className="phr-meter" style={{ marginTop: 6 }}>
              <div
                className="phr-meter-fill"
                style={{ width: `${efFillPct}%`, background: efColor }}
              />
            </div>
          </div>
        )}
        {nearTermNum > 0 && (
          <div className="networth-tile">
            <div className="tile-label">Near-term planned expenses</div>
            <div className="tile-value num" style={{ color: gapNum > 0 ? 'var(--negative-text)' : undefined }}>
              {format(nearTermNum)}
            </div>
            {gapNum > 0 && (
              <div className="card-meta" style={{ color: 'var(--negative-text)' }}>
                gap: {format(gapNum)} vs cash
              </div>
            )}
          </div>
        )}
      </div>
      {!liq.data_available && (
        <div className="card-meta" style={{ marginTop: 8 }}>
          No monthly spending yet: import a statement, or set a spending override in Forecast → Profile.
        </div>
      )}
    </div>
  )
}
