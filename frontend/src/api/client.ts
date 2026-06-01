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
      ticker: string;
      quantity: string;
      price_currency: string;
      asset_class: string;
      manual_price: string;
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
