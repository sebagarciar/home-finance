// Option vocabularies for profile forms (mirror the backend Literal enums).
export const CURRENCIES = ['CLP', 'EUR', 'USD', 'GBP']

export const HORIZONS = [
  ['lt_1y', 'Under 1 year'],
  ['1_3y', '1–3 years'],
  ['3_7y', '3–7 years'],
  ['7_15y', '7–15 years'],
  ['gt_15y', 'Over 15 years'],
] as const

export const SCALE = [
  ['low', 'Low'],
  ['moderate', 'Moderate'],
  ['high', 'High'],
  ['very_high', 'Very high'],
] as const

export const LOSS = [
  ['sell_after_10', 'Would sell after a 10% drop'],
  ['hold_uncomfortable', 'Uncomfortable but would hold'],
  ['invest_more', 'Would invest more after a drop'],
  ['unsure', 'Unsure'],
] as const
