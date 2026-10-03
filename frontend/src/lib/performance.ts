import type { PerformanceIssue } from '../api/client'

// Plain-language reasons a holding's gains/return are suppressed (see
// services/performance/service.py `HoldingPerformance.issue`).
export const ISSUE_TEXT: Record<PerformanceIssue, string> = {
  no_trades: 'No cost basis yet. Start with what you hold today: units and average cost per unit.',
  qty_mismatch: "The ledger's units don't match the holding's quantity. Gains are hidden until they match.",
  currency_mismatch: "Some trades are in a different currency than the holding's price currency.",
  missing_price: "No current price, so gains can't be computed.",
  ledger_error: "The ledger can't be replayed: a sell exceeds the units held at that date.",
}
