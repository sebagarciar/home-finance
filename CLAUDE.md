# Home Finance — Notes for Claude

Personal finance app for a two-person household spanning Spain (EUR) and Chile (CLP), with USD-priced holdings. Manual data entry only (no bank APIs). Tax is out of scope.

Build plan: `~/.claude/plans/build-spec-household-stateless-wren.md`. Phases 1–7 done; Phase 8 (debt stub) is next.

## Repo layout

```
home_finance/
  backend/    FastAPI + SQLAlchemy 2.0 + Alembic + pytest
  frontend/   Vite + React + TS + Recharts
  input/      Real bank-statement samples (revolut, santander_es, scotiabank_cl)
```

## Run

For day-to-day launch the user runs `./dev.sh` (starts backend + frontend together).

```bash
# Backend (port 8000)
cd backend
.venv/bin/uvicorn app.main:app --reload --port 8000
.venv/bin/pytest
.venv/bin/ruff check app && .venv/bin/mypy app
.venv/bin/alembic upgrade head

# Frontend (port 5173)
cd frontend
npm run dev
npm run lint
npm run build       # TS check + bundle
```

Open http://localhost:5173. CORS is wired for the Vite dev origin.

## Architecture invariants — DO NOT VIOLATE

- **Base/reporting currency is CLP everywhere.** Hardcoded in `app/config.py`. EUR is a display-only toggle applied as a single CLP→EUR conversion at render time.
- **Money is never stored pre-converted.** Transactions store native `amount + currency + fx_rate_to_base` captured at the transaction date. Holdings store `quantity + price_currency`, valued at read-time with current FX.
- **All amounts are `Numeric(18, 4)`** — never floats for money. Currency codes are ISO 4217.
- **Only two conversion entry points exist:**
  - `to_base(db, amount, currency, on_date)` — historical, for spending. [backend/app/services/fx/conversion.py:55](backend/app/services/fx/conversion.py)
  - `to_base_current(db, amount, currency)` — latest, for holdings/net-worth.
  - Anywhere else doing FX math is a bug.
- **No raw SQL.** Everything through SQLAlchemy ORM so we can swap SQLite → Postgres without query rewrites. Use generic types (not SQLite-specific). Alembic is the source of truth for schema.
- **All external API keys server-side only.** Frontend talks only to FastAPI.
- **FX and price providers are behind interfaces** (`FxProvider`, `PriceProvider`). The active price provider is `CompositePriceProvider`, which routes `FINTUAL:<serie_id>` tickers to `FintualPriceProvider` (Chilean mutual funds via the public `inversiones.fintual.com/api` that backs Fintual's fund pages — the old `fintual.cl/api/real_assets` is token-gated since 2026 and uses different ids) and everything else to `YFinancePriceProvider`. Manual-price override always wins.

## Categorization model

Pipeline lives in [backend/app/services/categorization/](backend/app/services/categorization/). The cascade runs for **every** imported row regardless of `txn_type` — there is no short-circuit for transfer/deposit/refund. The cascade in `cascade.py` walks, stopping at first hit:

1. **Exact match** in `category_rules` (learned + seeded). Includes manual corrections.
2. **Whole-word substring** — seeded rule key (≥4 chars) appears as a whole word in the merchant key.
3. **Fuzzy** — `rapidfuzz.fuzz.ratio` (NOT `partial_ratio` — see "lessons learned"), threshold 85, only for merchant keys ≥5 chars.
4. **Ollama** — local LLM at `http://localhost:11434`, default `llama3.1:8b`. Strict prompt, returns one taxonomy label or `None`. Graceful degradation if unreachable.
5. **Fallback** — `Other`, no writeback.

**Manual corrections always win.** `_writeback` will not overwrite a rule with `source=manual`. The recategorize endpoint (`PATCH /transactions/{id}/category`) sets `source=manual` when `propagate=true`.

**Empty / too-short merchant keys** (<3 chars) short-circuit to `Other` without writeback — prevents poisoning `category_rules`.

## Normalization rules (in `normalize.py`)

This is the SAME function used by the importer (for `normalized_description` + `dedup_hash`) and the categorizer. Key rules — don't undo without thinking:

- **Strip leading bank boilerplate**: `PAGO MOVIL EN`, `COMPRA`, `Card Payment`, `Bizum payment to:`, `Transfer to`, `Payment from`, `Money added via BIZUM`, etc.
- **Strip trailing card/commission noise**: `, TARJ. :*NNNN`, `, TARJETA NNNN , COMISION X,XX`.
- **Strip acquirer prefixes**: `SQ *` (Square), `PAYPAL *`, `STRIPE *`, `TRANSBANK `, `WEBPAY `, `AMZN MKTP ES*<order_id>`.
- **Preserve merchant-kind tokens when stripping reference IDs.** `LICENCIA 10691` → `licencia` (not empty). `TAXI LIC. 13818` → `taxi lic`. This is load-bearing — taxi rows would otherwise collapse to bare city names.
- **Strip city stopwords as standalone tokens** (`madrid`, `santiago`, `amsterdam`, `palo alto`, etc.) so bare-city keys don't reach the LLM and get hallucinated answers that poison `category_rules`. List is in `_CITY_STOPWORDS`.
- **Strip accents** (NFD normalize), strip `*` and `+` as punctuation.

## Default taxonomy

12 categories, user-editable: Supermarket, Restaurant, Transport, Shopping, Entertainment, Travel, Housing, Health, Subscriptions, Salary, Transfers, Other. (Recurring household bills — telecom, electric, water — live under Subscriptions.)

Seeded rules + this taxonomy live in [backend/app/seeds/defaults.py](backend/app/seeds/defaults.py).

## Bank parsers

[backend/app/services/importers/](backend/app/services/importers/) — `Parser` interface with `parse(file) -> list[ParsedTxn]`. `ParsedTxn` carries date, signed native amount, currency, raw description, and `txn_type`.

Three parsers exist: `revolut` (CSV), `santander_es` (xlsx), `scotiabank_cl` (xls). Each handles bank-specific quirks (Santander's U+2212 minus sign and European decimals; Scotiabank's sparse-row .xls layout with country-driven currency derivation). Registry in `registry.py`.

**Future banks:** ask the user for a sample first. Do not guess formats.

## Email ingest (near-live Santander ES)

Santander ES sends a notification email per transaction. `POST /import/email/sync` pulls them over IMAP and feeds the **same** `preview_import`/`commit_import` pipeline, so the dashboard refreshes without a manual upload.

- **Fetch:** [services/email_ingest/gmail.py](backend/app/services/email_ingest/gmail.py) — Gmail IMAP with an **app password** (`GMAIL_USER`/`GMAIL_APP_PASSWORD`), filters by `SANTANDER_EMAIL_SENDER` (default `SantanderInforma@emailing.bancosantander-mail.es`) + `SINCE`. **Read-only** (`readonly=True`, never marks seen/deletes) — dedup, not IMAP flags, owns idempotency. Graceful degradation like the Ollama client.
- **Parse:** [services/importers/santander_es_email.py](backend/app/services/importers/santander_es_email.py) — `parse_santander_email(raw) -> ParsedTxn | None`. Prefers the email's `text/plain` part (HTML is fallback via bs4). Anchored regexes on confirmed wordings ("has pagado … en MERCHANT", "MERCHANT ha realizado una retención de …"); **accents optional** (plain-text strips them). Unrecognised emails → `None` (skipped, never guessed). Uses the email `Date` header as the txn date.
- **Provisional layer:** email rows are written with `Transaction.source="email"`. A **statement** import (`source="statement"`, the default) archives any overlapping `email` rows in its date range — the monthly `.xlsx` is the source of truth and supersedes the auth-amount/partial email rows. See `commit_import(..., source=)`.
- **Samples:** `input/santander_email_*.eml`. `tests/test_email_ingest.py` covers parser, idempotency, supersede, and a stubbed-fetcher endpoint test.

## Transaction types

Enum on `transactions.txn_type`: `card_payment | transfer | deposit | refund | direct_debit | fee | other`. Parsers fill it from each bank's hint. **`txn_type` is informational only** — it does NOT gate the spending dashboard. Every non-archived transaction contributes to aggregates. Internal bank-to-bank moves are removed by **archiving** them manually. Category is the source of truth for what a row "is".

## Spending dashboard model

- Only filter on rows: `archived = false` (plus optional date/account range).
- Aggregates are net per category (signed-base sum). Categories with a negative net are **still shown** — they're a signal that something is miscategorized or the date window is wrong, not noise to hide.
- Categories flagged **`is_income`** (`Category.is_income`; seeded: Salary) are excluded from the spending series; their positive inflows feed `by_month_income`. The flag — not the category name — drives the split, so renames are safe. Income categories are assigned manually (no auto-detection).

## Net-worth model (Phase 5)

- **Cash is NEVER derived from transaction sums.** Each account has a manual
  `current_balance` in its native currency, edited via `PUT /accounts/{id}/balance`.
  Net-worth reads it directly. Rationale: imported transaction history is
  partial (only the months the user actually statemented), so summing
  transactions silently mis-states net worth.
- Transactions still drive the spending dashboard. They just don't drive the
  bank balance.
- Debt accounts store a **positive** loan amount in `current_balance` and
  net-worth subtracts it (bucketed under `debt` in `by_asset_class`).
- Holdings value via `quantity × current price → price_currency → CLP` through
  `to_base_current`. Manual-price fallback shows a staleness flag.

## Known gotchas

- **FX providers**: `FX_PROVIDER=free` (default) is `CurrencyApiProvider` — the fawazahmed0/currency-api CDN dataset (no key, fast, daily snapshots incl. weekends, covers CLP; occasional gap days are handled by a ≤3-day walk-back). Alternatives: `mindicador` (official BCCh fixings + frankfurter for non-CLP pairs — authoritative but mindicador.cl is slow/flaky) and `exchangerate_host` (needs a paid `FX_API_KEY`). Fully offline, `to_base` still falls back to hardcoded `_FALLBACK_RATES` (never persisted); `POST /fx/rerate` later backfills real historical rates onto transactions and the fx_rates cache (idempotent — re-run if it reports transient failures). The 2026-06-10 backfill re-rated all 1,397 foreign-currency rows that had been sitting on fallback rates.
- **Ollama is on by default** (`OLLAMA_ENABLED=true`). The cascade gracefully skips it if unreachable. The user has `llama3.1:8b` installed locally.
- **In-memory SQLite tests need `StaticPool`** so multiple sessions share one connection — otherwise tables disappear between sessions. See `tests/test_endpoints_phase4.py`.
- **`category_rules` writeback flushes per row** (`db.flush()` inside `_writeback`) so same-batch repeat merchants don't collide on the unique constraint.
- **Cascade module is `cascade.py`, not `classify.py`** — the package re-exports `classify` as a function, so importing the module via that name shadows.

## Lessons learned (do not regress)

- `fuzz.partial_ratio` is **wrong** for categorization. A short merchant key like `madrid` matched `metro madrid` at 100% and poisoned the rules table. Always use `fuzz.ratio`.
- Writing back the LLM's guess for a bare city/location key spreads bad classifications across every subsequent transaction in that city. Hence the city stopword strip + the empty-key guard in the cascade.
- Normalization that strips the merchant name down to nothing (when only a reference ID remains) ruins categorization. Preserve "kind" tokens like `licencia`, `lic`, `taxi`.

## Files worth knowing

- Plan: `~/.claude/plans/build-spec-household-stateless-wren.md`
- Conversion contract: [backend/app/services/fx/conversion.py](backend/app/services/fx/conversion.py)
- Cascade: [backend/app/services/categorization/cascade.py](backend/app/services/categorization/cascade.py)
- Normalization: [backend/app/services/categorization/normalize.py](backend/app/services/categorization/normalize.py)
- Importers: [backend/app/services/importers/](backend/app/services/importers/)
- Seeds: [backend/app/seeds/defaults.py](backend/app/seeds/defaults.py)
- Frontend currency context: [frontend/src/lib/currency.ts](frontend/src/lib/currency.ts) (fetches CLP→EUR from `/fx` on mount; `FALLBACK_EUR_PER_CLP = 1/1050` is the offline fallback)
- Frontend API client: [frontend/src/api/client.ts](frontend/src/api/client.ts)
- Frontend query hooks: [frontend/src/api/hooks.ts](frontend/src/api/hooks.ts) (TanStack Query — use these from pages, not raw `useEffect + fetch`)
- Price providers: [backend/app/services/prices/](backend/app/services/prices/) — `provider.py` (composite + yfinance), `fintual.py` (Fintual API + name search), `valuation.py`
- Forecast engine: [backend/app/services/forecast/](backend/app/services/forecast/) — `blocks.py` (return sourcing + block bootstrap + `shock_mask`), `engine.py` (`run_forecast`). Endpoint `POST /forecast/run` in [backend/app/routers/forecast.py](backend/app/routers/forecast.py); UI in [frontend/src/pages/Forecast.tsx](frontend/src/pages/Forecast.tsx).

## Forecast model (Phase 6)

- **Pure NumPy, vectorized across paths** (default 10k; UI uses 5k). Monthly steps over `horizon_years`. Output is base CLP; the EUR toggle is display-only at render.
- **Returns** = historical block bootstrap (`block_len=6`) of asset-class proxies — `ASSET_PROXIES = {equity: VT, bonds: AGG}`, cash deterministic from its return assumption. Same time index sampled across classes preserves cross-asset correlation. Returns are disk-cached under `services/forecast/.forecast_cache/` (7-day TTL).
- **Graceful degradation:** `returns_mode="auto"` falls back to a parametric Normal model (`_PARAMETRIC_VOL`) when yfinance is unreachable. `deterministic` mode (zero vol) exists for offline/tests.
- **Correlated shocks (ρ):** in bottom-decile market months (`shock_mask`), income scales down and spending up by ρ × magnitude. ρ default 0.3.
- **Real terms by default** (deterministic inflation deflator); `real=false` for nominal. Inflation is not yet sampled (single `inflation_rate`) — future extension.
- **FX scenario** is flat by default; `fx_drift_annual` drifts only the foreign-currency income share, never bundled into returns.
- Reads the single seeded `assumptions` row; the Forecast page only exposes run controls (horizon, real/nominal, target). **Full assumptions editing is Phase 7.**

## Assumptions (Phase 7)

`GET/PUT /assumptions` ([backend/app/routers/assumptions.py](backend/app/routers/assumptions.py)) over the single seeded row; PUT is a partial update (only sent fields change), validates ranges, upper-cases currencies, and rejects negative allocations. UI in [frontend/src/pages/Assumptions.tsx](frontend/src/pages/Assumptions.tsx), rendered as an in-page sub-tab of the Forecast page (no separate sidebar entry — the `Forecast` wrapper in [frontend/src/pages/Forecast.tsx](frontend/src/pages/Forecast.tsx) switches Forecast ↔ Assumptions): sectioned form (income / spending / returns+allocation / forecast params), money fields with a currency select, rates shown as %. Saving invalidates the `['forecast']` query so the Forecast page recomputes. **"Use my avg" links** fill income/spending from the last ≤12 statemented months (`useSpendingSummary`) — the bridge between the (intentionally forecast-excluded) transaction history and the manual assumption inputs.

## What's next

**Phase 8 — debt stub.** Extend account types with `debt` (already in the enum) and add a `debt_terms` table (balance, rate, term_months, start_date, amortization JSON). Migration + surface balance in net-worth; no UI beyond that.

Phase 6 shipped: `services/forecast/` (block-bootstrap sampler over VT/AGG with parametric fallback, correlated ρ shocks, real/nominal, FX drift, life-event lumps), `POST /forecast/run`, and the Forecast page (fan chart with P10–P90 / P25–P75 bands + median, target-probability tile, horizon/terms/target controls). Three spec tests + an endpoint smoke test in `tests/test_forecast.py`.

## Working style for this project

- The user is comfortable with Python, React, APIs, ML. Don't hand-hold; favor clean architecture and concise updates.
- Stay in the active phase; don't scope-creep into future phases.
- When real-world data exposes a bug (it has, several times), fix the root cause — don't paper over with special cases.
- When a user-facing decision needs making (taxonomy choice, transfer auto-exclusion, sample files, etc.), ask via AskUserQuestion before committing to an approach.
