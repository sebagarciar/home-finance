/**
 * TanStack Query hooks over the `api` client.
 *
 * `api/client.ts` stays the single fetch layer — these hooks only add caching,
 * deduplication, and shared loading/error state. Components never call `api.*`
 * for reads directly; they use these hooks so the same data fetched on two
 * surfaces (e.g. the summary bar + the dashboard) hits one shared cache entry.
 *
 * Mutations live with their callers; after a write they call
 * `queryClient.invalidateQueries({ queryKey: ... })` with the keys below.
 */
import { useQuery } from '@tanstack/react-query'
import { api } from './client'
import type { ForecastRequest, TxnType } from './client'

export const queryKeys = {
  spendingSummary: (params: SpendingParams = {}) => ['spending', 'summary', params] as const,
  networthCurrent: () => ['networth', 'current'] as const,
  networthHistory: () => ['networth', 'history'] as const,
  holdings: () => ['holdings'] as const,
  accounts: () => ['accounts'] as const,
  categories: () => ['categories'] as const,
  transactions: (params: TxnParams) => ['transactions', params] as const,
  forecast: (params: ForecastRequest) => ['forecast', params] as const,
  assumptions: () => ['assumptions'] as const,
}

interface SpendingParams {
  start?: string
  end?: string
  account_id?: number
}

export function useSpendingSummary(params: SpendingParams = {}) {
  return useQuery({
    queryKey: queryKeys.spendingSummary(params),
    queryFn: () => api.spending.summary(params),
  })
}

export function useNetworthCurrent() {
  return useQuery({
    queryKey: queryKeys.networthCurrent(),
    queryFn: () => api.networth.current(),
  })
}

export function useNetworthHistory() {
  return useQuery({
    queryKey: queryKeys.networthHistory(),
    queryFn: () => api.networth.history({}),
  })
}

export function useHoldings() {
  return useQuery({ queryKey: queryKeys.holdings(), queryFn: () => api.holdings.list() })
}

export function useAccounts() {
  return useQuery({ queryKey: queryKeys.accounts(), queryFn: () => api.accounts.list() })
}

export function useCategories() {
  return useQuery({ queryKey: queryKeys.categories(), queryFn: () => api.categories.list() })
}

export interface TxnParams {
  search?: string
  category?: string
  start?: string
  end?: string
  include_archived?: boolean
  limit?: number
}

export function useTransactions(params: TxnParams) {
  return useQuery({
    queryKey: queryKeys.transactions(params),
    queryFn: () =>
      api.transactions.list({
        search: params.search || undefined,
        category: params.category || undefined,
        start: params.start || undefined,
        end: params.end || undefined,
        include_archived: params.include_archived || undefined,
        limit: params.limit ?? 500,
      }),
    placeholderData: (prev) => prev, // keep previous rows visible while refetching on filter change
  })
}

export function useAssumptions() {
  return useQuery({ queryKey: queryKeys.assumptions(), queryFn: () => api.assumptions.get() })
}

// Forecast is a POST but behaves like a read (pure function of the run inputs),
// so it lives in TanStack Query keyed on those inputs. A fixed seed keeps the
// bands visually stable across re-runs when only the target changes.
export function useForecast(params: ForecastRequest) {
  return useQuery({
    queryKey: queryKeys.forecast(params),
    queryFn: () => api.forecast.run(params),
    placeholderData: (prev) => prev, // keep bands on screen while a new run computes
  })
}

// Re-exported for callers wiring mutations.
export type { TxnType }
