# Home Finance

A full-stack personal finance app for a two-person household spanning **Spain (EUR)** and **Chile (CLP)**, with USD-priced investment holdings — built to solve a real, personally-annoying problem: no existing budgeting app handles multi-currency households and manual bank-statement workflows without either mangling FX or requiring bank API access neither bank offers.

FastAPI + SQLAlchemy backend, React + TypeScript frontend, and a categorization pipeline that starts with rules and only falls back to a local LLM when rules run out.

![Overview dashboard — net worth by type, monthly spending by category, total, and recent activity (sample data)](screenshots/overview-mock.jpg)

## What it does

- **Imports real bank statements** — parsers for Revolut (CSV), Santander España (xlsx), and Scotiabank Chile (xls), each handling that bank's specific quirks (locale decimal formats, sparse layouts, minus-sign encoding). Plus **near-live ingestion**: Santander ES sends a transaction email per purchase, pulled over IMAP and fed through the same import pipeline so the dashboard updates without waiting for a monthly statement.
- **Categorizes automatically, and learns from corrections** — a five-stage cascade (exact rule match → whole-word substring → fuzzy match → local LLM via Ollama → fallback) that gets faster and more accurate as you correct it; manual corrections always win and are never overwritten by the automated stages.
- **Tracks net worth across currencies** — cash balances (manually maintained — imported transaction history is inherently partial, so it never drives the bank balance), investment holdings priced live (yfinance / Fintual) and converted through a single FX contract, and debt.
- **Runs Monte Carlo retirement/goal forecasts** — vectorized NumPy simulation using historical block-bootstrap sampling of real asset returns (not a Gaussian assumption), with correlated income/spending shocks in down markets, real or nominal terms, and a full assumptions editor.
- **Checks your mix against a target** — four risk questions set a target allocation range; the Portfolio page shows today's mix against it, live and deterministic, with no scores or advice.

Manual data entry only — no bank APIs, because none of the banks involved offer one to individual users. Tax is explicitly out of scope.

## Tech stack

**Backend:** FastAPI · SQLAlchemy 2.0 · Alembic · Pydantic · pytest
**Frontend:** Vite · React · TypeScript · TanStack Query · Recharts
**Data/ML:** NumPy (Monte Carlo forecasting) · RapidFuzz (categorization) · Ollama / Llama 3.1 8B (local LLM categorization fallback) · yfinance / Fintual (pricing)

## Architecture invariants

- **Base/reporting currency is CLP everywhere.** EUR is a display-only toggle applied as a single conversion at render time — never stored pre-converted.
- **Money is never stored pre-converted.** Transactions store native `amount + currency + fx_rate_to_base` captured at the transaction date; holdings store `quantity + price_currency`, valued at read time.
- **Exactly two FX conversion entry points exist**: `to_base` (historical, for spending) and `to_base_current` (latest, for holdings/net worth). Anywhere else doing FX math is a bug.
- **All amounts are `Numeric(18,4)`** — never floats for money.
- **No raw SQL** — everything through the SQLAlchemy ORM; Alembic is the source of truth for schema.
- **All external API keys are server-side only** — the frontend only ever talks to FastAPI.
- FX and price providers sit behind swappable interfaces (`FxProvider`, `PriceProvider`), so a provider outage or pricing change doesn't ripple through the codebase.

## Local dev

One-command launch (starts backend + frontend together):

```bash
./dev.sh
```

Or run them separately:

```bash
# Backend (port 8000)
cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env        # fill in FX/price/Gmail/Ollama keys — all optional, features degrade gracefully
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload --port 8000

# Frontend (port 5173)
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>.

```bash
# Backend checks
.venv/bin/pytest                            # 15 test files
.venv/bin/ruff check app && .venv/bin/mypy app

# Frontend checks
npm run lint
npm run build       # TS check + bundle
```

## Status

Phases 1–7 of the build plan are complete: data import, categorization, spending dashboard, net worth, Monte Carlo forecasting, and a full assumptions editor. Phase 8 (debt amortization) is deprioritized; see CLAUDE.md "What's next".

Since then: cost basis with asset-vs-currency attribution, a "Needs attention" list that keeps manual data current, one household profile that the forecast and the portfolio check share (spending, cash and the current mix are derived from data), and a slimmer Overview.
