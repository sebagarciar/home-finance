# Plan — Cost basis & investment performance

**Goal:** answer "what did I pay, what is it worth, how much did I make, and how much of
that was the asset vs. the currency?" for every holding, without disturbing the existing
valuation / net-worth model.

## Decisions (confirmed)

| Question | Decision |
|---|---|
| Quantity source of truth | `Holding.quantity` stays **manual**. The trade ledger only supplies basis. Mismatch → flagged, gains suppressed. Mirrors the cash-balance rule ("history is partial"). |
| Basis method | **Average cost.** Sells realize gain at the running average; they don't change it. |
| Entry | **Manual form + "opening position"** now. Broker parsers later, only after the user shares sample files. |

## Invariants this must respect

- Valuation and net worth are **unchanged**: still `Holding.quantity × current price → to_base_current`.
- Money is `Numeric`. Trades store native amounts plus the FX rate captured on the trade date, the same pattern as `transactions.fx_rate_to_base`.
- FX math goes only through `to_base` (historical, trade date) and `to_base_current` (now). Nothing else.
- ORM only, Alembic migration, generic types.

## 1. Data model — `investment_trades`

New model `app/models/investment_trades.py` + Alembic migration.

| column | type | notes |
|---|---|---|
| `id` | int PK | |
| `holding_id` | FK → holdings, `ondelete=CASCADE` | |
| `date` | Date | not in the future |
| `kind` | Enum `opening \| buy \| sell \| dividend \| fee` | |
| `quantity` | Numeric(20,8) | always ≥ 0; sign comes from `kind`. 0 for dividend/fee |
| `price` | Numeric(20,6) | per unit, native. Unused for dividend/fee |
| `amount` | Numeric(18,4) | cash amount for dividend/fee, native |
| `fees` | Numeric(18,4) default 0 | commission on buy/sell, native |
| `currency` | String(3) | must equal `holding.price_currency` at write time. Stored so that a later currency edit on the holding is detectable instead of silently corrupting the basis |
| `fx_rate_to_base` | Numeric(20,10) | `to_base(db, 1, currency, date)` at write time |
| `note` | String nullable | |
| `created_at` | DateTime | |

`opening` works like `buy`. It exists so the user can seed "I held 120 units at an average of 9,850" without full history. The UI treats it as the starting point. At most one per holding, and it must be the earliest row.

**Buy by amount:** the form takes either `quantity` or a total `amount`. The server derives `quantity = (amount − fees) / price`. Fintual statements show CLP deposited, not units.

## 2. Pure engine — `app/services/performance/`

### `basis.py` — `replay(trades) -> PositionState`

Walks the trades in date order (ties broken by id) and tracks, in native and in base:

- `qty`, `cost_native`, `cost_base` (base cost uses each trade's own FX rate)
- buy/opening: `qty += q`; `cost_native += q·p + fees`; `cost_base += (q·p + fees)·fx`
- sell: `avg_n = cost_native/qty`, `avg_b = cost_base/qty`
  - `realized_native += q·p − fees − avg_n·q`
  - `realized_base += (q·p − fees)·fx_sell − avg_b·q`
  - `cost_native −= avg_n·q`; `cost_base −= avg_b·q`; `qty −= q`
- dividend: `income_native/base += amount (·fx)`
- fee: `fees_native/base += amount (·fx)`
- Raises `OversellError` if a sell exceeds the quantity held on that date.

### `attribution.py` — split the unrealized gain (base CLP)

```
value_base      = to_base_current(qty · P_now, ccy)
unrealized_base = value_base − cost_base
price_effect    = to_base_current(qty · P_now − cost_native, ccy)   # asset moved, at today's FX
fx_effect       = unrealized_base − price_effect                    # = cost_native·FX_now − cost_base
```

CLP-priced holdings (Fintual) always have `fx_effect = 0`. This is the "how much was the currency" number. It's the most useful output for a EUR/CLP/USD household.

### `returns.py` — money-weighted return (XIRR)

- Cash flows in base CLP: buys/opening −, sells/dividends +, standalone fees −, plus a terminal flow equal to today's `value_base`.
- Solver: Newton's method with a bisection fallback over [−0.99, 10]. No new dependency. Rates are floats; money stays Decimal until the flow list is built.
- Computed **per holding** in base *and* native: native minus base is the currency's share of the return. **Portfolio-level** is computed in base only, because native currencies can't be mixed.
- If the holding period is under 365 days, return the cumulative return and `annualized=false`. Annualizing a 3-week return gives nonsense figures like 400%.

### Reconciliation

`reconciled = (ledger qty == Holding.quantity)`, with a small tolerance (1e-6) for fund units.
- No trades → `has_basis=false`. The row shows value only.
- Unreconciled → cost basis is shown, but unrealized gain and XIRR are `null` with a reason. A gain computed on the wrong quantity looks right and is wrong, which is worse than no number.

## 3. API

In `app/routers/investment_trades.py`:

- `GET  /holdings/{id}/trades` — list
- `POST /holdings/{id}/trades` — create. Validates currency, date, positivity and the at-most-one-opening rule, then **replays the whole ledger** and rejects with 422 if any sell would oversell.
- `PATCH /trades/{id}`, `DELETE /trades/{id}` — same replay check. An edit or delete can invalidate a later sell.

In `app/routers/performance.py`:

- `GET /performance` →
  ```json
  { "totals": { "cost_base", "value_base", "unrealized_base", "price_effect", "fx_effect",
                "realized_base", "income_base", "xirr", "annualized", "coverage_pct" },
    "holdings": [ { "holding_id", "has_basis", "reconciled", "ledger_qty", "holding_qty",
                    "cost_base", "avg_cost_native", "value_base", "unrealized_base",
                    "price_effect", "fx_effect", "realized_base", "income_base",
                    "xirr", "xirr_native", "annualized", "since" } ] }
  ```
  `coverage_pct` is the share of portfolio value that has a reconciled basis. Totals cover only that share, and the UI says so ("covers 72% of portfolio").

This is a separate endpoint so `GET /holdings` stays cheap. Prices come from the existing daily cache via `price_holding`.

## 4. Frontend

- `api/client.ts` + `api/hooks.ts`: `useTrades(holdingId)`, `useCreateTrade` / `useUpdateTrade` / `useDeleteTrade` (each invalidates `['trades', id]` and `['performance']`), and `usePerformance()`.
- **Portfolio → Overview:**
  - Summary tiles: *Invested* (cost), *Unrealized* (with a "of which FX: X" sub-line), *Realized + income*, *Return (XIRR)*, plus a coverage note.
  - Holdings table, new columns: *Avg cost*, *Gain* (tooltip shows the price vs. FX split), *Return*. Holdings with no basis get an "Add cost basis" link. Unreconciled rows show a warning chip "ledger 118 vs 120 units".
- **Trades drawer** per holding: ledger table and an add/edit form (kind, date, qty-or-amount, price, fees, note). If the holding is empty, the first action offered is "Set starting position" (opening).
- The EUR toggle stays display-only, as everywhere else.

## 5. Tests — `backend/tests/test_performance.py`

1. Average cost: buy 10@100, buy 10@200 → avg 150. Sell 5@300 → realized 750, remaining cost 2,250, avg still 150.
2. Fees are added to basis on buys and subtracted from proceeds on sells.
3. FX attribution: USD holding bought at FX 900, now 1,000, price unchanged → `price_effect = 0`, `fx_effect = cost_native × 100`.
4. A CLP holding has `fx_effect == 0`.
5. XIRR: −100 one year ago, value 110 today → 10.0%. Plus one Excel reference case with irregular flows.
6. Period under 1 year → cumulative return, `annualized=false`.
7. Oversell is rejected on create, and on an edit or delete that breaks a later sell.
8. Mismatch → `reconciled=false`, gains and XIRR are null. No trades → `has_basis=false`.
9. Endpoint smoke test with a stubbed price provider and FX (StaticPool fixture, autouse auth override from `conftest.py`).
10. Migration upgrade and downgrade.

Before calling it done: `ruff`, `mypy`, `pytest`, then `npm run lint && npm run build`. Then a browser check on the Portfolio page: add an opening position and a buy, and confirm the tiles and the FX split.

## 6. Order of work

1. Commit or finish the current uncommitted `holdings.py` / `Portfolio.tsx` changes first, so this work starts from a clean tree.
2. Model + migration → `basis.py` / `attribution.py` / `returns.py` with unit tests (pure, no DB).
3. Routers + endpoint tests.
4. Frontend hooks → tiles/columns → trades drawer.
5. Update CLAUDE.md (new "Cost basis model" section, file pointers).

## Out of scope (follow-ups)

- **Time-weighted return (TWR):** needs historical prices at each flow date. That means adding `PriceProvider.fetch_history`; yfinance `history()` and the Fintual `/real_assets/{id}/days` endpoint already expose this. XIRR covers "how did *I* do" first.
- Splits / reverse splits (`split` kind with a ratio).
- Broker statement parsers (Fintual, IBKR, etc.), after the user shares samples.
- Feeding basis into Portfolio Health (e.g. a concentration-of-gains finding) or into tax views (tax remains out of scope).
- Performance history over time (adding basis to `networth_snapshots.breakdown`).
