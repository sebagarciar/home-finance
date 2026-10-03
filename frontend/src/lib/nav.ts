// Tab navigation with an optional "intent", so one page can open another
// already filtered (e.g. Needs attention → Transactions showing `Other`).
// The target reads the intent once, as initial state; plain tab clicks clear it.
import { createContext, useContext } from 'react'

export type Tab = 'dashboard' | 'portfolio' | 'forecast' | 'transactions'

export interface NavIntent {
  /** Transactions sub-view. */
  view?: 'transactions' | 'import'
  category?: string
  start?: string
  accountId?: number
}

interface NavCtx {
  go: (tab: Tab, intent?: NavIntent) => void
  intent: NavIntent | null
}

export const NavContext = createContext<NavCtx>({ go: () => {}, intent: null })

export function useNav(): NavCtx {
  return useContext(NavContext)
}
