// Single source of truth for category appearance.
// Color + glyph for each category in the default taxonomy.
// Unknown categories fall through to "Other".

export interface CategoryStyle {
  label: string
  color: string  // CSS var ref or hex
  icon: string   // single-char glyph
}

const STYLES: Record<string, CategoryStyle> = {
  Supermarket:   { label: 'Supermarket',   color: 'var(--cat-2)', icon: '🛒' },
  Restaurant:    { label: 'Restaurant',    color: 'var(--cat-6)', icon: '🍽' },
  Transport:     { label: 'Transport',     color: 'var(--cat-5)', icon: '🚇' },
  Shopping:      { label: 'Shopping',      color: 'var(--cat-3)', icon: '🛍' },
  Entertainment: { label: 'Entertainment', color: 'var(--cat-1)', icon: '🎬' },
  Travel:        { label: 'Travel',        color: 'var(--cat-4)', icon: '✈' },
  Housing:       { label: 'Housing',       color: 'var(--cat-7)', icon: '🏠' },
  Health:        { label: 'Health',        color: 'var(--cat-3)', icon: '＋' },
  Subscriptions: { label: 'Subscriptions', color: 'var(--cat-1)', icon: '↻' },
  Salary:        { label: 'Salary',        color: 'var(--cat-2)', icon: '$' },
  Transfers:     { label: 'Transfers',     color: 'var(--cat-8)', icon: '⇄' },
  Other:         { label: 'Other',         color: 'var(--cat-8)', icon: '•' },
}

const FALLBACK_COLORS = [
  'var(--cat-1)', 'var(--cat-2)', 'var(--cat-3)', 'var(--cat-4)',
  'var(--cat-5)', 'var(--cat-6)', 'var(--cat-7)', 'var(--cat-8)',
]

export function categoryStyle(name: string | null | undefined): CategoryStyle {
  if (!name) return STYLES.Other
  if (STYLES[name]) return STYLES[name]
  // Stable hash → palette slot, so unknown categories still get a consistent color
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0
  return {
    label: name,
    color: FALLBACK_COLORS[h % FALLBACK_COLORS.length],
    icon: name.charAt(0).toUpperCase(),
  }
}

// Resolved hex value for use in inline styles where CSS vars aren't supported
// (e.g. some Recharts internals). Resolves at call-time from the document.
let _resolved: Record<string, string> | null = null
function resolveVars(): Record<string, string> {
  if (_resolved) return _resolved
  if (typeof window === 'undefined') return {}
  const cs = getComputedStyle(document.documentElement)
  _resolved = {
    'var(--cat-1)': cs.getPropertyValue('--cat-1').trim() || '#494fdf',
    'var(--cat-2)': cs.getPropertyValue('--cat-2').trim() || '#00a87e',
    'var(--cat-3)': cs.getPropertyValue('--cat-3').trim() || '#e61e49',
    'var(--cat-4)': cs.getPropertyValue('--cat-4').trim() || '#b09000',
    'var(--cat-5)': cs.getPropertyValue('--cat-5').trim() || '#007bc2',
    'var(--cat-6)': cs.getPropertyValue('--cat-6').trim() || '#ec7e00',
    'var(--cat-7)': cs.getPropertyValue('--cat-7').trim() || '#936d62',
    'var(--cat-8)': cs.getPropertyValue('--cat-8').trim() || '#8d969e',
  }
  return _resolved
}

export function categoryColorHex(name: string | null | undefined): string {
  const style = categoryStyle(name)
  return resolveVars()[style.color] ?? style.color
}
