import { CURRENCIES } from './constants'

// Shared form components used by the questionnaire.

export function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div className="assumptions-section">
      <div className="assumptions-section-head">
        <h3 className="card-title" style={{ fontSize: 14 }}>{title}</h3>
        {subtitle && <div className="card-meta">{subtitle}</div>}
      </div>
      <div className="assumptions-fields">{children}</div>
    </div>
  )
}

export function SelectField({
  label, value, options, onChange,
}: {
  label: string; value: string; options: readonly (readonly [string, string])[]; onChange: (v: string) => void
}) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} className="phr-select">
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  )
}

export function MoneyField({
  label, value, ccy, onValue, onCcy, hint,
}: {
  label: string; value: string; ccy: string
  onValue: (v: string) => void; onCcy: (c: string) => void
  hint?: { text: string; onClick: () => void }
}) {
  return (
    <label className="field">
      <span className="field-label">
        {label}
        {hint && (
          <button type="button" className="link-btn" style={{ marginLeft: 8 }} onClick={hint.onClick}>
            {hint.text}
          </button>
        )}
      </span>
      <div className="field-money">
        <input value={value} inputMode="decimal" onChange={(e) => onValue(e.target.value.replace(/[^0-9.]/g, ''))} />
        <select value={ccy} onChange={(e) => onCcy(e.target.value)}>
          {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>
    </label>
  )
}
