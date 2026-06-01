# Home Finance

Two-person household finance app spanning Spain (EUR) and Chile (CLP). Monorepo with FastAPI backend and React frontend. **Base/reporting currency is CLP everywhere**; EUR is a display-only toggle.

Build plan: `~/.claude/plans/build-spec-household-stateless-wren.md`.

## Status

**Phase 1 complete:** scaffold, full data model, FX provider abstraction, conversion helpers (`to_base` historical, `to_base_current` latest), seeds, `/health` and `/fx` routes, Alembic migrations, pytest suite green.

Phases 2–8 (importer, categorization, spending, portfolio, Monte Carlo, assumptions, debt) are not implemented yet.

## Local dev

### Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env  # then edit FX_API_KEY if you have one
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Tests:

```bash
.venv/bin/pytest
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>.

## FX provider note

`exchangerate.host` (the planned default) changed to require a paid API key in late 2024. Phase 1 ships with it wired up but the live `/fx` route will 502 without `FX_API_KEY`. The provider is behind a one-file abstraction (`app/services/fx/provider.py`), so swapping to another CLP-capable provider is straightforward. Unit tests stub the provider and pass offline.

## Architecture invariants

- **Money is never stored pre-converted.** Transactions store native `amount + currency + fx_rate_to_base` at the transaction date.
- **Spending uses historical FX** (`to_base`); **net-worth/holdings use current FX** (`to_base_current`). These two functions are the only money-conversion entry points in the codebase.
- All amounts are `Numeric(18, 4)`, never floats.
- No raw SQL anywhere; everything through SQLAlchemy ORM so we can swap SQLite → Postgres without query rewrites.
- All external API keys server-side only.
