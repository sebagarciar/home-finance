import { createContext, useContext, useState, useEffect, createElement } from 'react'
import type { ReactNode } from 'react'
import { api } from '../api/client'

type Display = 'CLP' | 'EUR'

// Display-only conversion. Base is always CLP (see backend config). The live
// rate is fetched from the backend (the single source of FX truth) on mount;
// this constant is only the offline fallback until/unless that request fails —
// the backend itself falls back to approximate rates without an API key.
const FALLBACK_EUR_PER_CLP = 1 / 1050

const SYMBOLS: Record<Display, string> = { CLP: '$', EUR: '€' }

interface CurrencyCtx {
  display: Display
  setDisplay: (d: Display) => void
  toDisplay: (clp: number) => number
  symbol: string
  /** Full formatted money string, currency-aware. */
  format: (clp: number) => string
  /** Format an amount already in display currency (no CLP conversion). */
  formatAs: (displayAmount: number) => string
  /** Compact axis label, e.g. $1.2M / €350K. */
  formatCompact: (clp: number) => string
  /** Privacy mode — when on, all formatted money is masked. */
  privacy: boolean
  setPrivacy: (p: boolean) => void
  /** Mask any string (e.g. a native-currency amount) when privacy is on. */
  mask: (s: string) => string
}

const Ctx = createContext<CurrencyCtx | null>(null)

const MASK = '••••'

export function CurrencyProvider({ children }: { children: ReactNode }) {
  const [display, setDisplay] = useState<Display>('CLP')
  const [privacy, setPrivacy] = useState<boolean>(false)
  const [eurPerClp, setEurPerClp] = useState<number>(FALLBACK_EUR_PER_CLP)

  useEffect(() => {
    let cancelled = false
    // 1 CLP = `rate` EUR. Keep the fallback if the request fails.
    api
      .fxRate('CLP', 'EUR')
      .then((r) => {
        const rate = Number(r.rate)
        if (!cancelled && Number.isFinite(rate) && rate > 0) setEurPerClp(rate)
      })
      .catch((e) => console.warn('FX rate fetch failed, using fallback', e))
    return () => {
      cancelled = true
    }
  }, [])

  const toDisplay = (clp: number) => (display === 'EUR' ? clp * eurPerClp : clp)
  const symbol = SYMBOLS[display]
  const locale = display === 'EUR' ? 'es-ES' : 'es-CL'

  const format = (clp: number) => {
    if (privacy) return `${symbol}${MASK}`
    const v = toDisplay(clp)
    const opts =
      display === 'EUR'
        ? { minimumFractionDigits: 2, maximumFractionDigits: 2 }
        : { maximumFractionDigits: 0 }
    const sign = v < 0 ? '-' : ''
    return `${sign}${symbol}${Math.abs(v).toLocaleString(locale, opts)}`
  }

  const formatCompact = (clp: number) => {
    if (privacy) return `${symbol}${MASK}`
    const v = toDisplay(clp)
    const abs = Math.abs(v)
    const sign = v < 0 ? '-' : ''
    if (abs >= 1_000_000) return `${sign}${symbol}${(abs / 1_000_000).toFixed(1)}M`
    if (abs >= 1_000) return `${sign}${symbol}${Math.round(abs / 1_000)}K`
    return `${sign}${symbol}${Math.round(abs)}`
  }

  const formatAs = (v: number) => {
    if (privacy) return `${symbol}${MASK}`
    const opts =
      display === 'EUR'
        ? { minimumFractionDigits: 2, maximumFractionDigits: 2 }
        : { maximumFractionDigits: 0 }
    const sign = v < 0 ? '-' : ''
    return `${sign}${symbol}${Math.abs(v).toLocaleString(locale, opts)}`
  }

  const mask = (s: string) => (privacy ? MASK : s)

  return createElement(
    Ctx.Provider,
    {
      value: {
        display, setDisplay, toDisplay, symbol, format, formatAs, formatCompact,
        privacy, setPrivacy, mask,
      },
    },
    children,
  )
}

export function useCurrency() {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useCurrency must be used within CurrencyProvider')
  return ctx
}
