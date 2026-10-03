// Mix vs target (Portfolio page): today's net worth by bucket against the
// range your risk answers allow. One plain check, computed live — no score.
import { type MixBucket, type TargetPolicy } from '../api/client'
import { usePortfolioChecks } from '../api/hooks'
import { useCurrency } from '../lib/currency'
import { useNav } from '../lib/nav'

const PROFILE_LABEL: Record<string, string> = {
  conservative: 'Conservative', moderate: 'Moderate', growth: 'Growth', aggressive: 'Aggressive',
}

const NOTE_TEXT: Record<string, string> = {
  tolerance_capacity_conflict: 'your tolerance and capacity differ, so the lower one applies',
  horizon_cap: 'your horizon is short',
  loss_reaction_cap: 'you said you would sell after a drop, or your tolerance is low',
}

export function MixCheck() {
  const q = usePortfolioChecks()
  const { go } = useNav()
  const toProfile = () => go('forecast', { view: 'profile' })

  if (q.isLoading) {
    return (
      <div className="card">
        <div className="skel" style={{ height: 18, width: 160, marginBottom: 16 }} />
        <div className="skel" style={{ height: 120 }} />
      </div>
    )
  }
  const data = q.data
  if (!data?.policy || !data.mix) {
    return (
      <div className="card">
        <div className="card-header">
          <div>
            <h2 className="card-title">Mix vs target</h2>
            <div className="card-meta">
              Answer four risk questions in your profile to get a target mix to check against.
            </div>
          </div>
          <button className="btn" onClick={toProfile}>Open profile</button>
        </div>
      </div>
    )
  }

  const { policy, mix } = data
  const headline = mix.out_of_range > 0
    ? `${mix.out_of_range} ${mix.out_of_range === 1 ? 'bucket is' : 'buckets are'} outside your range`
    : mix.drifting > 0
      ? 'In range, but drifting from target'
      : 'On target'
  const tone = mix.out_of_range > 0 ? 'warn' : mix.drifting > 0 ? 'info' : 'pos'

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <h2 className="card-title">Mix vs target</h2>
          <div className="card-meta">
            {PROFILE_LABEL[policy.risk_profile]} profile{whyText(policy)}.{' '}
            <button className="link-btn" onClick={toProfile}>Edit answers</button>
          </div>
        </div>
        <span className={`trend-pill ${tone}`}>{headline}</span>
      </div>
      <div className="mix-rows">
        {mix.buckets.map((b) => <MixRow key={b.bucket} b={b} />)}
      </div>
      <div className="card-meta" style={{ marginTop: 12 }}>
        Bars show today&rsquo;s share; the shaded band is your range and the tick its midpoint.
        Educational only, not investment advice.
      </div>
    </div>
  )
}

function MixRow({ b }: { b: MixBucket }) {
  const { format } = useCurrency()
  const color =
    b.status === 'above' || b.status === 'below' ? 'var(--pending-text)' : 'var(--accent)'
  return (
    <div className="mix-row">
      <div className="mix-label">
        <span>{b.label}</span>
        <span className="muted num">{format(Number(b.value))}</span>
      </div>
      <div className="mix-track" aria-hidden="true">
        {b.min_pct != null && b.max_pct != null && (
          <div className="mix-range" style={{ left: `${b.min_pct}%`, width: `${b.max_pct - b.min_pct}%` }} />
        )}
        {b.target_pct != null && <div className="mix-target" style={{ left: `${b.target_pct}%` }} />}
        <div className="mix-fill" style={{ width: `${Math.min(b.current_pct, 100)}%`, background: color }} />
      </div>
      <div className="mix-figures num">
        <strong style={{ color: b.status === 'in' || b.status == null ? undefined : 'var(--pending-text)' }}>
          {b.current_pct}%
        </strong>
        <span className="muted">
          {b.min_pct != null && b.max_pct != null
            ? `range ${b.min_pct}–${b.max_pct}%${statusText(b)}`
            : 'no target (set an asset class)'}
        </span>
      </div>
    </div>
  )
}

function statusText(b: MixBucket): string {
  if (b.status === 'above') return ` · ${round(b.current_pct - (b.max_pct ?? 0))}pp above`
  if (b.status === 'below') return ` · ${round((b.min_pct ?? 0) - b.current_pct)}pp below`
  if (b.drifting && b.drift_pp != null) {
    return ` · ${round(Math.abs(b.drift_pp))}pp ${b.drift_pp < 0 ? 'under' : 'over'} target`
  }
  return ''
}

function whyText(p: TargetPolicy): string {
  const reasons = p.notes.map((n) => NOTE_TEXT[n.code]).filter(Boolean)
  return reasons.length ? `, because ${reasons.join(' and ')}` : ''
}

const round = (x: number) => Math.round(x * 10) / 10
