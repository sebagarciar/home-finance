// Risk answers (Forecast → Profile): the four questions that set the target
// mix the Portfolio page checks against. Saving adds a new version; the
// latest is active.
import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, type RiskProfile, type RiskProfileInput } from '../api/client'
import { HORIZONS, LOSS, SCALE } from '../lib/options'
import { Section, SelectField } from './fields'

const DEFAULTS: RiskProfileInput = {
  time_horizon: '7_15y',
  risk_tolerance: 'moderate',
  risk_capacity: 'moderate',
  loss_reaction: 'hold_uncomfortable',
}

const PROFILE_LABEL: Record<string, string> = {
  conservative: 'Conservative', moderate: 'Moderate', growth: 'Growth', aggressive: 'Aggressive',
}

export function RiskQuestions({ initial }: { initial: RiskProfile | null }) {
  const qc = useQueryClient()
  const [form, setForm] = useState<RiskProfileInput>(() => (initial ? {
    time_horizon: initial.time_horizon,
    risk_tolerance: initial.risk_tolerance,
    risk_capacity: initial.risk_capacity,
    loss_reaction: initial.loss_reaction,
  } : DEFAULTS))
  const [saving, setSaving] = useState(false)
  const [result, setResult] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const set = (patch: Partial<RiskProfileInput>) => {
    setForm((prev) => ({ ...prev, ...patch }))
    setResult(null)
  }

  const save = async () => {
    setSaving(true)
    setErr(null)
    try {
      const r = await api.portfolio.putRiskProfile(form)
      setResult(`Saved · target: ${PROFILE_LABEL[r.policy.risk_profile] ?? r.policy.risk_profile}`)
      await qc.invalidateQueries({ queryKey: ['portfolio'] })
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <h2 className="card-title">Risk</h2>
          <div className="card-meta">
            Sets the target mix the Portfolio page checks against. Educational only, not
            investment advice.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          {result && <span className="tag tag-info">{result}</span>}
          <button className="btn primary" onClick={save} disabled={saving}>
            {saving ? 'Saving…' : 'Save answers'}
          </button>
        </div>
      </div>
      {err && <div className="form-error" style={{ marginBottom: 12 }}>{err}</div>}

      <div className="grid-2">
        <Section title="Horizon">
          <SelectField label="When will you need most of this money?" value={form.time_horizon}
            options={HORIZONS} onChange={(v) => set({ time_horizon: v as RiskProfileInput['time_horizon'] })} />
          <SelectField label="Reaction to a market loss" value={form.loss_reaction}
            options={LOSS} onChange={(v) => set({ loss_reaction: v as RiskProfileInput['loss_reaction'] })} />
        </Section>
        <Section title="Risk" subtitle="The lower of the two sets your profile.">
          <SelectField label="Tolerance (how much swing you're comfortable with)" value={form.risk_tolerance}
            options={SCALE} onChange={(v) => set({ risk_tolerance: v as RiskProfileInput['risk_tolerance'] })} />
          <SelectField label="Capacity (how much loss you could absorb)" value={form.risk_capacity}
            options={SCALE} onChange={(v) => set({ risk_capacity: v as RiskProfileInput['risk_capacity'] })} />
        </Section>
      </div>
    </div>
  )
}
