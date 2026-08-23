// Option vocabularies (mirror the backend Literal enums + friendly labels)
export const GOALS = [
  ['long_term_growth', 'Long-term wealth growth'],
  ['retirement', 'Retirement'],
  ['capital_preservation', 'Capital preservation'],
  ['income', 'Income generation'],
  ['home_purchase', 'Home purchase'],
  ['education', 'Education'],
  ['other', 'Other'],
] as const
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
export const STABILITY = [
  ['stable', 'Stable salary'],
  ['variable', 'Variable income'],
  ['self_employed', 'Self-employed'],
  ['unemployed', 'Unemployed'],
  ['retired', 'Retired'],
] as const
export const KNOWLEDGE = [
  ['beginner', 'Beginner'],
  ['intermediate', 'Intermediate'],
  ['advanced', 'Advanced'],
] as const
export const CURRENCIES = ['CLP', 'EUR', 'USD', 'GBP']

export const SUBSCORE_LABELS: Record<string, string> = {
  goalAlignmentScore: 'Goal alignment',
  riskAlignmentScore: 'Risk alignment',
  diversificationScore: 'Diversification',
  liquidityScore: 'Liquidity',
  costEfficiencyScore: 'Cost efficiency',
  dataQualityScore: 'Data quality',
}

export const SEVERITY_RANK: Record<string, number> = { high: 0, medium: 1, low: 2 }
