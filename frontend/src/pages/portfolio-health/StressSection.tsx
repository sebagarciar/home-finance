import type { StressScenario } from '../../api/client'

const STRESS_ICONS: Record<string, string> = {
  equity_crash: '📉',
  bond_stress: '📊',
  crypto_crash: '₿',
  largest_holding_collapse: '🎯',
  home_currency_strength: '💱',
}

export function StressSection({
  scenarios,
  format,
}: {
  scenarios: StressScenario[]
  format: (n: number) => string
}) {
  const worst = scenarios.reduce(
    (m, s) => (s.approx_impact_pct < m.approx_impact_pct ? s : m),
    scenarios[0],
  )

  return (
    <div className="card">
      <div className="card-header">
        <h2 className="card-title">Stress scenarios</h2>
        <span className="phr-sev sev-low">estimates · not predictions</span>
      </div>
      <div className="phr-stress-grid">
        {scenarios.map((s) => {
          const isWorst = s.scenario === worst.scenario
          const impactAbs = Math.abs(s.approx_impact_pct)
          const impactBase = Number(s.approx_impact_base)
          const tone = s.approx_impact_pct < -15 ? 'var(--negative-text)' : s.approx_impact_pct < -5 ? 'var(--pending-text)' : 'var(--text-secondary)'
          return (
            <div className={`phr-stress-card${isWorst ? ' worst' : ''}`} key={s.scenario}>
              <div className="phr-stress-icon">{STRESS_ICONS[s.scenario] ?? '⚡'}</div>
              <div className="phr-stress-label">{s.label}</div>
              <div className="phr-stress-impact num" style={{ color: tone }}>
                −{impactAbs.toFixed(1)}%
              </div>
              <div className="phr-stress-base card-meta">{format(Math.abs(impactBase))}</div>
              <div className="phr-stress-assumption">{s.assumption}</div>
            </div>
          )
        })}
      </div>
      <div className="card-meta" style={{ marginTop: 12 }}>
        These are order-of-magnitude estimates based on historical shock magnitudes applied to
        current exposures. They are not predictions and do not account for portfolio adjustments,
        correlation changes, or offsetting factors. For scenario-specific analysis, consult a
        licensed professional.
      </div>
    </div>
  )
}
