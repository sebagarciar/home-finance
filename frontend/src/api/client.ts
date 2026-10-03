import { clearToken, getToken, triggerUnauthorized } from "../lib/auth";

const BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const authHeader: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};

  const r = await fetch(`${BASE}${path}`, {
    headers:
      init?.body instanceof FormData
        ? { ...authHeader, ...(init.headers as Record<string, string> ?? {}) }
        : { "Content-Type": "application/json", ...authHeader, ...(init?.headers as Record<string, string> ?? {}) },
    ...init,
  });

  if (r.status === 401) {
    clearToken();
    triggerUnauthorized();
    throw new Error("Session expired — please log in again");
  }

  if (!r.ok) {
    const body = await r.text().catch(() => "");
    throw new Error(`API ${r.status}: ${body || r.statusText}`);
  }
  if (r.status === 204) return undefined as T;
  return (await r.json()) as T;
}

// Downloads honor the same bearer auth as request(), so a plain <a href> won't
// work — fetch the blob here and hand the caller a filename + object URL to click.
async function requestBlob(path: string): Promise<{ blob: Blob; filename: string }> {
  const token = getToken();
  const r = await fetch(`${BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (r.status === 401) {
    clearToken();
    triggerUnauthorized();
    throw new Error("Session expired — please log in again");
  }
  if (!r.ok) {
    const body = await r.text().catch(() => "");
    throw new Error(`API ${r.status}: ${body || r.statusText}`);
  }
  const disposition = r.headers.get("Content-Disposition") ?? "";
  const match = /filename="?([^"]+)"?/.exec(disposition);
  return { blob: await r.blob(), filename: match?.[1] ?? "export.csv" };
}

export type AccountType = "checking" | "credit" | "savings" | "investment" | "debt";
export type TxnType =
  | "card_payment"
  | "transfer"
  | "deposit"
  | "refund"
  | "direct_debit"
  | "fee"
  | "other";

export interface Account {
  id: number;
  name: string;
  institution: string | null;
  country: string;
  type: AccountType;
  native_currency: string;
  current_balance: string;
  balance_updated_at: string | null;
}

export interface Category {
  id: number;
  name: string;
  is_system: boolean;
}

export interface Transaction {
  id: number;
  account_id: number;
  date: string;
  amount: string;
  currency: string;
  fx_rate_to_base: string;
  amount_in_base: string;
  txn_type: TxnType;
  category: string | null;
  raw_description: string;
  normalized_description: string;
  archived: boolean;
}

export interface SpendingSummary {
  currency: "CLP";
  total_spent: string;
  by_category: { category: string; total: string }[];
  by_month: { month: string; total: string }[];
  by_account: { account_id: number; total: string }[];
  by_month_category: { month: string; category: string; total: string }[];
  by_month_income: { month: string; total: string }[];
  count: number;
}

export interface Holding {
  id: number;
  account_id: number;
  ticker: string;
  quantity: string;
  price_currency: string;
  asset_class: string;
  manual_price: string | null;
  manual_price_updated_at: string | null;
  price: string;
  as_of: string;
  source: "yfinance" | "fintual" | "cache" | "manual";
  is_manual: boolean;
  missing_price: boolean;
  /** Why the live price lookup failed (set when falling back to manual / no price). */
  price_error: string | null;
  value_native: string;
  value_in_base: string;
}

/** Needs-attention items (GET /attention). Wording lives in the UI; the backend sends facts. */
export interface AttentionTxnRef {
  id: number;
  account_id: number;
  account_name: string;
  date: string;
  description: string;
}
export type AttentionItem =
  | { kind: "stale_balance"; key: string; account_id: number; account_name: string; currency: string;
      current_balance: string; updated_on: string | null; age_days: number | null }
  | { kind: "statement_missing"; key: string; account_id: number; account_name: string;
      month: string; email_rows: number }
  | { kind: "transfer_pair"; key: string; currency: string; amount: string;
      out: AttentionTxnRef; in: AttentionTxnRef }
  | { kind: "uncategorized"; key: string; count: number; since: string; category: string }
  | { kind: "stale_price"; key: string; holding_id: number; ticker: string; currency: string;
      manual_price: string | null; last_priced_on: string | null };

export interface AttentionResponse {
  items: AttentionItem[];
  /** Items currently hidden by a dismissal. */
  dismissed: number;
}

export type TradeKind = "opening" | "buy" | "sell" | "dividend" | "fee";

/** One cost-basis ledger row. Amounts are native (`currency` = holding's price currency). */
export interface Trade {
  id: number;
  holding_id: number;
  date: string;
  kind: TradeKind;
  quantity: string;
  price: string;
  amount: string;
  fees: string;
  currency: string;
  fx_rate_to_base: string;
  note: string | null;
}

/** Unit trades (opening/buy/sell) take price + exactly one of quantity|amount;
 *  dividend/fee take amount only. */
export interface TradeInput {
  date: string;
  kind: TradeKind;
  quantity?: string | null;
  price?: string | null;
  amount?: string | null;
  fees?: string;
  note?: string | null;
}

/** Why gains/return are suppressed for a holding. */
export type PerformanceIssue =
  | "no_trades"
  | "qty_mismatch"
  | "currency_mismatch"
  | "missing_price"
  | "ledger_error";

export interface HoldingPerformance {
  holding_id: number;
  ticker: string;
  currency: string;
  has_basis: boolean;
  reconciled: boolean;
  issue: PerformanceIssue | null;
  ledger_qty: string;
  holding_qty: string;
  since: string | null;
  avg_cost_native: string | null;
  cost_native: string;
  cost_base: string;
  value_base: string | null;
  unrealized_base: string | null;
  price_effect: string | null;
  fx_effect: string | null;
  realized_base: string;
  income_base: string;
  fees_base: string;
  /** Money-weighted return (XIRR) in base CLP; cumulative when `annualized` is false. */
  return: number | null;
  return_native: number | null;
  annualized: boolean;
}

export interface Performance {
  totals: {
    cost_base: string;
    value_base: string;
    unrealized_base: string;
    price_effect: string;
    fx_effect: string;
    realized_base: string;
    income_base: string;
    fees_base: string;
    return: number | null;
    annualized: boolean;
    /** Share (0–1) of priced portfolio value with a reconciled basis; totals cover only that share. */
    coverage_pct: number | null;
  };
  holdings: HoldingPerformance[];
}

export interface NetworthAccountRow {
  account_id: number;
  name: string;
  type: AccountType;
  native_currency: string;
  cash_native: string;
  cash_in_base: string;
  holdings_in_base: string;
  total_in_base: string;
  balance_updated_at: string | null;
}

export interface NetworthAssetClassRow {
  asset_class: string;
  total_in_base: string;
}

export interface NetworthCurrencyRow {
  currency: string;
  total_in_base: string;
}

export interface NetworthHoldingRow {
  holding_id: number;
  account_id: number;
  ticker: string;
  asset_class: string;
  quantity: string;
  price: string;
  price_currency: string;
  as_of: string;
  source: string;
  is_manual: boolean;
  missing_price: boolean;
  /** Why the live price lookup failed (set when falling back to manual / no price). */
  price_error: string | null;
  value_in_base: string;
}

export interface NetworthCurrent {
  currency: "CLP";
  total_in_base: string;
  cash_total_in_base: string;
  holdings_total_in_base: string;
  by_account: NetworthAccountRow[];
  by_asset_class: NetworthAssetClassRow[];
  by_currency: NetworthCurrencyRow[];
  holdings: NetworthHoldingRow[];
}

export interface NetworthHistoryPoint {
  date: string;
  total_in_base: string;
}

export interface FxRate {
  base: string;
  quote: string;
  date: string;
  rate: string;
}

export interface ForecastBand {
  month: number;
  date: string;
  p10: number;
  p25: number;
  p50: number;
  p75: number;
  p90: number;
}

export interface ForecastResult {
  currency: "CLP";
  real: boolean;
  n_paths: number;
  horizon_years: number;
  start_networth: number;
  bands: ForecastBand[];
  terminal: { p10: number; p50: number; p90: number };
  target: number | null;
  prob_hit_target: number | null;
  /** What the run used (base CLP), so the page can say where numbers came from. */
  inputs: {
    monthly_income: number;
    monthly_spending: number;
    spending_source: SpendingSource;
    spending_months: number;
    allocation: Record<string, number>;
    planned_expenses: number;
  };
}

export type SpendingSource = "override" | "derived" | "none";

export interface PlannedExpense {
  label: string;
  amount: string;
  currency: string;
  /** "YYYY-MM" */
  month: string;
}

/** The household profile (single row). Spending is derived unless overridden. */
export interface Assumptions {
  income_user1: string;
  income_user1_currency: string;
  income_user2: string;
  income_user2_currency: string;
  income_growth_rate: number;
  income_noise_sigma: number;
  /** null = use the average derived from statements. */
  spending_override_monthly: string | null;
  spending_override_currency: string;
  spending_growth_rate: number;
  planned_expenses: PlannedExpense[];
  return_assumptions: Record<string, number>;
  horizon_years: number;
  correlation_rho: number;
  inflation_rate: number;
  fx_drift_annual: number;
}

export type AssumptionsUpdate = Partial<Assumptions>;

/** GET /assumptions/derived — what the data says (base CLP). */
export interface AssumptionsDerived {
  currency: "CLP";
  spending: {
    derived_monthly: string | null;
    months: string[];
    effective_monthly: string;
    source: SpendingSource;
  };
  liquid_cash: string;
  allocation: Record<string, number>;
}

export interface ForecastRequest {
  horizon_years?: number;
  real?: boolean;
  target?: number | null;
  n_paths?: number;
  seed?: number | null;
  life_events?: { month: number; amount: number; currency?: string; label?: string }[];
}

export interface ImportPreview {
  total: number;
  duplicates: number;
  rows: {
    date: string;
    amount: string;
    currency: string;
    txn_type: TxnType;
    raw_description: string;
    normalized: string;
    is_duplicate: boolean;
  }[];
}

export interface ImportResult {
  imported: number;
  duplicates_skipped: number;
}

export interface EmailSyncResult {
  fetched: number;
  parsed: number;
  imported: number;
  skipped: number;
}

export interface FintualFund {
  fund: string;
  serie: string | null;
  symbol: string | null;
  ticker: string; // e.g. "FINTUAL:186" — ready to use as a holding ticker
  currency: string;
}

// ---- Portfolio checks ----
export type Horizon = "lt_1y" | "1_3y" | "3_7y" | "7_15y" | "gt_15y";
export type RiskScale = "low" | "moderate" | "high" | "very_high";
export type LossReaction = "sell_after_10" | "hold_uncomfortable" | "invest_more" | "unsure";

/** Risk answers that set the target mix (latest version is active). */
export interface RiskProfile {
  id: number;
  time_horizon: Horizon;
  risk_tolerance: RiskScale;
  risk_capacity: RiskScale;
  loss_reaction: LossReaction;
  created_at: string | null;
}

export type RiskProfileInput = Omit<RiskProfile, "id" | "created_at">;

export interface TargetPolicy {
  risk_profile: "conservative" | "moderate" | "growth" | "aggressive";
  target_allocation: Record<string, number>;
  allocation_ranges: Record<string, [number, number]>;
  /** Rules that shaped the target: tolerance_capacity_conflict | horizon_cap | loss_reaction_cap. */
  notes: { code: string; [k: string]: unknown }[];
}

export interface MixBucket {
  bucket: string;
  label: string;
  value: string;
  current_pct: number;
  /** null for "unclassified" holdings (no target). */
  target_pct: number | null;
  min_pct: number | null;
  max_pct: number | null;
  status: "below" | "in" | "above" | null;
  drift_pp: number | null;
  /** In range, but more than the rebalance threshold from the target midpoint. */
  drifting: boolean;
}

/** GET /portfolio/checks — all null until risk answers exist. */
export interface PortfolioChecks {
  profile: RiskProfile | null;
  policy: TargetPolicy | null;
  mix: {
    currency: "CLP";
    total: string;
    out_of_range: number;
    drifting: number;
    buckets: MixBucket[];
  } | null;
}

function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") u.set(k, String(v));
  }
  const s = u.toString();
  return s ? `?${s}` : "";
}

export const api = {
  health: () => request<{ status: string }>("/health"),
  fxRate: (base: string, quote: string, date?: string) =>
    request<FxRate>(`/fx${qs({ base, quote, date })}`),

  accounts: {
    list: () => request<Account[]>("/accounts"),
    create: (a: Omit<Account, "id" | "balance_updated_at">) =>
      request<Account>("/accounts", { method: "POST", body: JSON.stringify(a) }),
    setBalance: (id: number, current_balance: string) =>
      request<Account>(`/accounts/${id}/balance`, {
        method: "PUT",
        body: JSON.stringify({ current_balance }),
      }),
    remove: (id: number) => request<void>(`/accounts/${id}`, { method: "DELETE" }),
  },

  categories: {
    list: () => request<Category[]>("/categories"),
  },

  transactions: {
    list: (params: {
      start?: string;
      end?: string;
      account_id?: number;
      category?: string;
      txn_type?: TxnType;
      search?: string;
      include_archived?: boolean;
      limit?: number;
      offset?: number;
    }) => request<Transaction[]>(`/transactions${qs(params)}`),
    create: (payload: {
      account_id: number;
      date: string;
      amount: string;
      currency: string;
      raw_description?: string;
      txn_type?: TxnType;
      category?: string;
    }) =>
      request<Transaction>(`/transactions`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    setDescription: (id: number, raw_description: string) =>
      request<{ id: number; raw_description: string; normalized_description: string }>(
        `/transactions/${id}/description`,
        { method: "PATCH", body: JSON.stringify({ raw_description }) },
      ),
    setDate: (id: number, date: string) =>
      request<{ id: number; date: string; fx_rate_to_base: string; amount_in_base: string }>(
        `/transactions/${id}/date`,
        { method: "PATCH", body: JSON.stringify({ date }) },
      ),
    setAmount: (id: number, amount: string) =>
      request<{ id: number; amount: string; amount_in_base: string }>(
        `/transactions/${id}/amount`,
        { method: "PATCH", body: JSON.stringify({ amount }) },
      ),
    setCategory: (id: number, category: string, propagate = true) =>
      request<{ id: number; category: string; propagated: boolean }>(
        `/transactions/${id}/category`,
        { method: "PATCH", body: JSON.stringify({ category, propagate }) },
      ),
    archive: (id: number) =>
      request<{ id: number; archived: boolean }>(`/transactions/${id}/archive`, { method: "POST" }),
    unarchive: (id: number) =>
      request<{ id: number; archived: boolean }>(`/transactions/${id}/unarchive`, { method: "POST" }),
    remove: (id: number) => request<void>(`/transactions/${id}`, { method: "DELETE" }),
    exportCsv: (params: {
      start?: string;
      end?: string;
      account_id?: number;
      category?: string;
      txn_type?: TxnType;
      search?: string;
      include_archived?: boolean;
    }) => requestBlob(`/transactions/export.csv${qs(params)}`),
  },

  holdings: {
    list: () => request<Holding[]>("/holdings"),
    create: (payload: {
      account_id: number;
      ticker: string;
      quantity: string;
      price_currency: string;
      asset_class?: string;
      manual_price?: string | null;
    }) => request<Holding>("/holdings", { method: "POST", body: JSON.stringify(payload) }),
    update: (id: number, payload: Partial<{
      account_id: number;
      ticker: string;
      quantity: string;
      price_currency: string;
      asset_class: string;
      manual_price: string | null; // null clears the manual override
    }>) => request<Holding>(`/holdings/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
    setManualPrice: (id: number, manual_price: string | null) =>
      request<Holding>(`/holdings/${id}/manual_price`, {
        method: "PUT",
        body: JSON.stringify({ manual_price }),
      }),
    remove: (id: number) => request<void>(`/holdings/${id}`, { method: "DELETE" }),
  },

  trades: {
    list: (holdingId: number) => request<Trade[]>(`/holdings/${holdingId}/trades`),
    create: (holdingId: number, payload: TradeInput) =>
      request<Trade>(`/holdings/${holdingId}/trades`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    update: (id: number, payload: Partial<TradeInput>) =>
      request<Trade>(`/trades/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
    remove: (id: number) => request<void>(`/trades/${id}`, { method: "DELETE" }),
  },

  performance: () => request<Performance>("/performance"),

  attention: {
    list: () => request<AttentionResponse>("/attention"),
    dismiss: (key: string) =>
      request<void>("/attention/dismiss", { method: "POST", body: JSON.stringify({ key }) }),
    restoreAll: () => request<void>("/attention/dismissals", { method: "DELETE" }),
  },

  networth: {
    current: () => request<NetworthCurrent>("/networth/current"),
    history: (params: { start?: string; end?: string } = {}) =>
      request<NetworthHistoryPoint[]>(`/networth/history${qs(params)}`),
    snapshot: (date?: string) =>
      request<{ date: string; total_in_base: string }>(
        `/networth/snapshot${qs({ date })}`,
        { method: "POST" },
      ),
  },

  spending: {
    summary: (params: {
      start?: string;
      end?: string;
      account_id?: number;
    }) => request<SpendingSummary>(`/spending/summary${qs(params)}`),
    pace: (through_day: number, trailing_months = 6) =>
      request<{ currency: "CLP"; expected_by_day: string | null; months_sampled: number }>(
        `/spending/pace${qs({ through_day, trailing_months })}`,
      ),
  },

  forecast: {
    run: (body: ForecastRequest) =>
      request<ForecastResult>("/forecast/run", {
        method: "POST",
        body: JSON.stringify(body),
      }),
  },

  assumptions: {
    get: () => request<Assumptions>("/assumptions"),
    derived: () => request<AssumptionsDerived>("/assumptions/derived"),
    update: (body: AssumptionsUpdate) =>
      request<Assumptions>("/assumptions", { method: "PUT", body: JSON.stringify(body) }),
  },

  prices: {
    fintualSearch: (q: string) =>
      request<{ results: FintualFund[] }>(`/prices/fintual/search${qs({ q })}`),
  },

  portfolio: {
    riskProfile: () => request<{ profile: RiskProfile | null }>("/portfolio/risk-profile"),
    putRiskProfile: (body: RiskProfileInput) =>
      request<{ profile: RiskProfile; policy: TargetPolicy }>("/portfolio/risk-profile", {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    checks: () => request<PortfolioChecks>("/portfolio/checks"),
  },

  import: {
    preview: (parser: string, accountId: number, file: File, statementYear?: number) => {
      const fd = new FormData();
      fd.set("parser", parser);
      fd.set("account_id", String(accountId));
      if (statementYear) fd.set("statement_year", String(statementYear));
      fd.set("file", file);
      return request<ImportPreview>("/import/preview", { method: "POST", body: fd });
    },
    commit: (parser: string, accountId: number, file: File, force = false, statementYear?: number) => {
      const fd = new FormData();
      fd.set("parser", parser);
      fd.set("account_id", String(accountId));
      fd.set("force", String(force));
      if (statementYear) fd.set("statement_year", String(statementYear));
      fd.set("file", file);
      return request<ImportResult>("/import/commit", { method: "POST", body: fd });
    },
    syncEmail: (accountId?: number) =>
      request<EmailSyncResult>(`/import/email/sync${qs({ account_id: accountId })}`, {
        method: "POST",
      }),
  },
};

export const authApi = {
  login: (username: string, password: string) =>
    request<{ access_token: string; token_type: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
};
