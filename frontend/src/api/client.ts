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
  value_native: string;
  value_in_base: string;
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
}

export interface Assumptions {
  income_user1: string;
  income_user1_currency: string;
  income_user2: string;
  income_user2_currency: string;
  income_growth_rate: number;
  income_noise_sigma: number;
  spending_baseline_monthly: string;
  spending_baseline_currency: string;
  spending_growth_rate: number;
  return_assumptions: Record<string, number>;
  asset_allocation: Record<string, number>;
  horizon_years: number;
  correlation_rho: number;
  inflation_rate: number;
  fx_drift_annual: number;
}

export type AssumptionsUpdate = Partial<Assumptions>;

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

// ---- Portfolio Health Review ----
export interface InvestorProfile {
  id: number;
  primary_goal: string;
  time_horizon: string;
  risk_tolerance: string;
  risk_capacity: string;
  loss_reaction: string;
  monthly_income: string;
  monthly_income_currency: string;
  monthly_expenses: string;
  monthly_expenses_currency: string;
  emergency_fund_amount: string;
  emergency_fund_currency: string;
  expected_large_expenses: { label: string; amount: number; currency: string; months_away: number }[];
  income_stability: string;
  investment_knowledge: string;
  tax_residence: string;
  base_currency: string;
  constraints: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
}

export interface InvestmentPolicyProfile {
  id: number;
  investor_profile_id: number;
  risk_profile: "conservative" | "moderate" | "growth" | "aggressive";
  target_allocation: Record<string, number>;
  allocation_ranges: Record<string, [number, number]>;
  max_single_holding_pct: number;
  max_sector_pct: number;
  max_country_pct: number;
  max_currency_pct: number;
  max_crypto_pct: number;
  max_employer_stock_pct: number;
  emergency_fund_target_months: number;
  rebalance_threshold_pct: number;
  version: number;
}

export interface PortfolioFinding {
  id?: number;
  category: string;
  severity: "low" | "medium" | "high";
  finding: string;
  evidence: Record<string, unknown>;
  whyItMatters: string;
  educationalGuidance: string;
  prohibitedSpecificAdvice: boolean;
}

export interface StressScenario {
  scenario: string;
  label: string;
  assumption: string;
  approx_impact_pct: number;
  approx_impact_base: string;
}

export interface LiquidityDiagnostics {
  cash_clp: string;
  monthly_expenses_clp: string;
  emergency_fund_declared_clp: string;
  ef_months_current: number | null;
  ef_months_target: number;
  near_term_large_expenses_clp: string;
  cash_gap_clp: string;
  data_available: boolean;
}

export interface SecurityMetadata {
  ticker: string;
  asset_class: string | null;
  sector: string | null;
  region: string | null;
  country: string | null;
  currency: string | null;
  product_type: string | null;
  expense_ratio: number | null;
  diversified_fund: boolean | null;
  liquidity_level: string | null;
  source: "auto" | "manual";
  updated_at: string | null;
}

export type SecurityMetadataInput = Partial<Omit<SecurityMetadata, "ticker" | "source" | "updated_at">>;

export interface PortfolioDiagnostics {
  allocation: {
    portfolio_value_in_base: string;
    current_pct: Record<string, number>;
    current_value_in_base: Record<string, string>;
    target_ranges: Record<string, [number, number]>;
    out_of_range: { bucket: string; current_pct: number; range: [number, number]; direction: "above" | "below" }[];
  };
  concentration: {
    top1_pct: number;
    top3_pct: number;
    top5_pct: number;
    largest_holding: { ticker: string; pct: number; value_in_base: string; bucket: string } | null;
    largest_single_stock: { ticker: string; pct: number } | null;
    crypto_pct: number;
    employer_stock_ticker: string | null;
    employer_stock_pct: number;
    holdings: { ticker: string; pct: number; value_in_base: string; bucket: string; is_single_stock: boolean }[];
  };
  liquidity: LiquidityDiagnostics;
  stress: StressScenario[];
  risk: Record<string, number>;
  sector: { by_sector_pct: Record<string, number>; max_sector_pct: number } | null;
  geography: { by_country_pct: Record<string, number>; max_country_pct: number } | null;
  currency_exposure: { by_currency_pct: Record<string, number>; max_currency_pct: number } | null;
  fees: {
    weighted_expense_ratio: number | null;
    fee_coverage_pct: number | null;
    holdings_with_fee_data: number;
    holdings_missing_fee_data: number;
    fee_warn_threshold: number;
    fee_high_threshold: number;
  } | null;
  data_quality: { unknown_count: number; missing_price_count: number; unknown_value_fraction: number; holdings_total: number };
  status: string;
  weights: Record<string, number>;
  score_explanation: Record<string, { finding_id: string; severity?: string; penalty?: number; cap?: number }[]>;
  policy: InvestmentPolicyProfile;
  flags: Record<string, boolean>;
}

export interface PortfolioReview {
  id: number;
  created_at: string | null;
  overall_score: number;
  sub_scores: Record<string, number>;
  diagnostics: PortfolioDiagnostics;
  missing_data: string[];
  ai_explanation: Record<string, unknown> | null;
  rules_engine_version: string;
  ai_prompt_version: string | null;
  investor_profile_id: number;
  investment_policy_profile_id: number;
  findings: PortfolioFinding[];
  profile_incomplete: false;
}

export interface FactualSummary {
  profile_incomplete: true;
  factual_summary: {
    portfolio_value_in_base: string;
    allocation_pct: Record<string, number>;
    bucket_labels: Record<string, string>;
    top_holdings: { ticker: string; pct: number; value_in_base: string; bucket: string }[];
    by_currency: NetworthCurrencyRow[];
  };
}

export type ReviewResponse = PortfolioReview | FactualSummary;

export interface ProfileInput {
  primary_goal: string;
  time_horizon: string;
  risk_tolerance: string;
  risk_capacity: string;
  loss_reaction: string;
  monthly_income: string;
  monthly_income_currency: string;
  monthly_expenses: string;
  monthly_expenses_currency: string;
  emergency_fund_amount: string;
  emergency_fund_currency?: string;
  expected_large_expenses?: { label: string; amount: number; currency: string; months_away: number }[];
  income_stability: string;
  investment_knowledge: string;
  tax_residence: string;
  base_currency: string;
  constraints: Record<string, unknown>;
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
    update: (body: AssumptionsUpdate) =>
      request<Assumptions>("/assumptions", { method: "PUT", body: JSON.stringify(body) }),
  },

  prices: {
    fintualSearch: (q: string) =>
      request<{ results: FintualFund[] }>(`/prices/fintual/search${qs({ q })}`),
  },

  portfolioHealth: {
    getProfile: () => request<{ profile: InvestorProfile | null }>("/portfolio-health/profile"),
    putProfile: (body: ProfileInput) =>
      request<{ profile: InvestorProfile; policy: InvestmentPolicyProfile }>(
        "/portfolio-health/profile",
        { method: "PUT", body: JSON.stringify(body) },
      ),
    getPolicy: () => request<{ policy: InvestmentPolicyProfile | null }>("/portfolio-health/policy"),
    runReview: () =>
      request<ReviewResponse>("/portfolio-health/review", { method: "POST" }),
    latestReview: () => request<{ review: PortfolioReview | null }>("/portfolio-health/review/latest"),
    reviews: () =>
      request<{ id: number; created_at: string | null; overall_score: number; status: string | null;
        rules_engine_version: string; ai_prompt_version: string | null }[]>("/portfolio-health/reviews"),
    listMetadata: () => request<SecurityMetadata[]>("/portfolio-health/metadata"),
    getMetadata: (ticker: string) => request<SecurityMetadata>(`/portfolio-health/metadata/${ticker}`),
    putMetadata: (ticker: string, body: SecurityMetadataInput) =>
      request<SecurityMetadata>(`/portfolio-health/metadata/${ticker}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    deleteMetadata: (ticker: string) =>
      request<{ deleted: string }>(`/portfolio-health/metadata/${ticker}`, { method: "DELETE" }),
    triggerEnrich: () =>
      request<SecurityMetadata[]>("/portfolio-health/enrich", { method: "POST" }),
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
