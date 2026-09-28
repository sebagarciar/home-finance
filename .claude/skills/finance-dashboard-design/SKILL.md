---
name: finance-dashboard-design
description: >
  Design system and implementation guide for Seba's personal finance dashboard (Vite + React + TypeScript + Recharts).
  Use this skill whenever working on ANY part of the finance dashboard: adding components, styling pages, building charts,
  creating layouts, fixing visual inconsistencies, or refining existing UI. Also trigger when asked to "make it look better",
  "improve the design", "style this component", or "match the design system". This skill defines the canonical visual language,
  token set, chart config, and component patterns for the entire app. Never style dashboard components from scratch without consulting it.
---

# Finance Dashboard Design System

Inspired by Copilot Money (the benchmark for consumer fintech UX) and grounded in the Revolut design token vocabulary.
The app runs dark-mode first. Every decision prioritises data legibility over decoration.

> For full color tokens, typography scale, and component specs → read `references/tokens.md`
> For Recharts configuration and chart patterns → read `references/charts.md`

---

## Design Philosophy

**Dark-first, data-forward.** The canvas is near-black (`#0a0a0a`). Numbers and trends are the heroes — UI chrome recedes.

**Card hierarchy, not bands.** Unlike the Revolut marketing site (which alternates full-bleed dark/light bands), this app lives entirely in the dark canvas. Elevation is expressed through surface luminance steps: canvas → card → elevated card.

**Copilot Money reference points:**
- Summary bar at the top (net worth, month spend, month income) — always visible
- Left sidebar navigation with icon + label, collapsible on mobile
- Main content = responsive card grid
- Transactions list = the most-used surface; it must be fast, scannable, filterable
- Charts are contextual (inside cards), never full-page unless drilling down
- Category pills with color dots — consistent across the whole app
- Positive cash flow = green; negative = red/pink; neutral = muted white

**Revolut tokens that carry over to the app context:**
- Surface ladder: `canvas-dark` → `surface-deep` → `surface-elevated`
- Text ladder: `on-dark` → `on-dark-mute` → `stone` → `faint`
- Semantic colors: `accent-light-green` (income/positive), `accent-pink` (expense/negative), `accent-yellow` (pending)
- Border radius: `rounded-lg` (20px) on cards, `rounded-md` (12px) on inputs/chips, `rounded-full` on pills
- No drop shadows — elevation via luminance only

---

## Quick-Reference Tokens

These are the most-used tokens. Full list in `references/tokens.md`.

```css
/* Surfaces */
--canvas:          #0a0a0a;   /* page background */
--surface:         #111214;   /* default card */
--surface-raised:  #16181a;   /* elevated card, hover state */
--surface-border:  rgba(255,255,255,0.08); /* card border */

/* Text */
--text-primary:    #ffffff;
--text-secondary:  rgba(255,255,255,0.72);
--text-muted:      #8d969e;
--text-faint:      #c9c9cd;

/* Semantic */
--positive:        #428619;   /* income, gains */
--positive-text:   #6fcf4a;   /* readable green on dark */
--negative:        #e61e49;   /* expenses, losses */
--negative-text:   #ff6b8a;   /* readable pink on dark */
--pending:         #b09000;
--pending-text:    #f0c040;
--accent:          #494fdf;   /* cobalt — use sparingly, primary CTA only */

/* Chart palette (8 category colors) */
--cat-1: #494fdf;  /* cobalt — primary category */
--cat-2: #00a87e;  /* teal */
--cat-3: #e61e49;  /* pink */
--cat-4: #b09000;  /* yellow */
--cat-5: #007bc2;  /* blue */
--cat-6: #ec7e00;  /* orange */
--cat-7: #936d62;  /* brown */
--cat-8: #8d969e;  /* stone — "other" */
```

---

## Core Layout

```
┌─────────────────────────────────────────────────────┐
│  Sidebar (240px / collapsed 64px)                   │
│  ┌───────────────────────────────────────────────┐  │
│  │  Top Summary Bar (full width, 72px)           │  │
│  │  Net Worth · Month Spend · Month Income       │  │
│  ├───────────────────────────────────────────────┤  │
│  │  Content Grid (gap: 16px, padding: 24px)      │  │
│  │  ┌────────┐ ┌────────┐ ┌────────────────────┐ │  │
│  │  │ Card   │ │ Card   │ │  Chart Card        │ │  │
│  │  └────────┘ └────────┘ └────────────────────┘ │  │
│  │  ┌─────────────────────────────────────────┐  │  │
│  │  │  Transactions List Card                 │  │  │
│  │  └─────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

---

## Component Patterns

### Card (base)

```tsx
// Base card — all dashboard cards derive from this
<div className="card">
  {children}
</div>
```

```css
.card {
  background: var(--surface);
  border: 1px solid var(--surface-border);
  border-radius: 20px;       /* rounded-lg */
  padding: 20px 24px;
  /* NO box-shadow — elevation via background only */
}
.card:hover {
  background: var(--surface-raised);
}
```

### Summary Bar

Three stat blocks in a horizontal bar pinned to the top of the content area.

```tsx
<SummaryBar>
  <Stat label="Net Worth"     value={netWorth}    trend={+2.4} />
  <Stat label="Month Spend"   value={monthSpend}  type="negative" />
  <Stat label="Month Income"  value={monthIncome} type="positive" />
</SummaryBar>
```

- Background: `var(--surface)`, full-width, 72px tall, no border-radius (spans edge-to-edge inside content area)
- Dividers between stats: 1px `var(--surface-border)` vertical
- Value: `font-size: 22px; font-weight: 600; color: var(--text-primary)`
- Label: `font-size: 12px; font-weight: 400; color: var(--text-muted); letter-spacing: 0.04em; text-transform: uppercase`
- Trend badge: pill, `rounded-full`, `font-size: 12px`
  - Positive: background `rgba(67,134,25,0.15)`, text `var(--positive-text)`
  - Negative: background `rgba(230,30,73,0.15)`, text `var(--negative-text)`

### Transaction Row

```tsx
<TransactionRow
  icon={category.icon}
  color={category.color}    // one of --cat-1 through --cat-8
  merchant="Mercadona"
  category="Groceries"
  date="May 24"
  amount={-42.50}
/>
```

- Row height: 56px, padding `0 16px`, `border-radius: 12px` on hover bg
- Icon container: 36px × 36px circle, background = category color at 15% opacity, icon in category color
- Merchant: `font-size: 14px; font-weight: 500; color: var(--text-primary)`
- Category + date: `font-size: 12px; color: var(--text-muted)`
- Amount: right-aligned, `font-size: 14px; font-weight: 600`
  - Expense: `color: var(--negative-text)`
  - Income: `color: var(--positive-text)`
  - Pending: `color: var(--pending-text)`, add a `·` prefix
- Divider between rows: 1px `var(--surface-border)`, no divider on last row

### Category Pill

```tsx
<CategoryPill color="var(--cat-2)" label="Food & Dining" />
```

```css
.category-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(from var(--color) r g b / 0.12);
  font-size: 12px;
  font-weight: 500;
  color: var(--color);
}
.category-pill::before {
  content: '';
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--color);
}
```

---

## Typography

Use **Inter** throughout the app (already open-source, excellent at small sizes in dark UIs).
Do NOT use Aeonik Pro — that's for Revolut's marketing site, not appropriate for dense dashboard UI.

| Role | Size | Weight | Color |
|---|---|---|---|
| Page title | 24px | 600 | `--text-primary` |
| Section heading | 16px | 600 | `--text-primary` |
| Card label | 12px | 400 | `--text-muted` (uppercase, +0.04em tracking) |
| Body / row text | 14px | 400 | `--text-primary` |
| Amount (large) | 22px | 600 | `--text-primary` |
| Amount (row) | 14px | 600 | semantic color |
| Caption / meta | 12px | 400 | `--text-muted` |

---

## Do's and Don'ts

### Do
- Keep the canvas `#0a0a0a` — never use pure `#000000` inside the app (that's the Revolut marketing rule, inverted here)
- Express elevation through background lightness steps only — no shadows, no borders beyond `var(--surface-border)`
- Color code every category consistently — the same color for "Groceries" everywhere, always
- Show amounts with 2 decimal places and the `€` symbol
- Use semantic color (green/red) on amounts — users scan sign + color, not sign alone
- Animate number changes (`@keyframes countUp` or a spring-based counter) — financial numbers changing is a key interaction moment
- Recharts: always use `CustomTooltip` with the dark card style — never use the default Recharts tooltip

### Don't
- Don't use `box-shadow` anywhere — use background luminance for elevation
- Don't use Recharts default colors — always pass `stroke` / `fill` from the `--cat-*` palette
- Don't show raw category strings from the data layer — always map to a display label + color + icon
- Don't put accent cobalt (`#494fdf`) on text or chart lines — it's CTA-only
- Don't mix font weights 300 or 500 — only 400 (body) and 600 (emphasis)

---

## Implementation Notes for Vite + React + TS

1. Define all tokens in a single `src/styles/tokens.css` and import it at the root. Use `@layer base` if you're mixing with Tailwind.
2. Create a `src/design/categories.ts` that maps category keys → `{ label, color, icon }`. This is the single source of truth for consistent category coloring.
3. For Recharts config, create a `src/components/charts/chartTheme.ts` that exports shared props (colors, tooltip, grid style). See `references/charts.md`.
4. Wrap Recharts' `ResponsiveContainer` inside a `ChartCard` component that handles padding, label, and the dark surface — never use `ResponsiveContainer` naked in page code.
