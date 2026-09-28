# Design Tokens Reference

Full token set for the personal finance dashboard. Read this file when:
- Setting up `src/styles/tokens.css` from scratch
- Adding a new component that needs colors beyond the quick-reference in SKILL.md
- Checking the full text or spacing scale

---

## CSS Custom Properties (tokens.css)

```css
:root {
  /* ── Surfaces ─────────────────────────────────── */
  --canvas:            #0a0a0a;
  --surface:           #111214;
  --surface-raised:    #16181a;
  --surface-border:    rgba(255, 255, 255, 0.08);
  --surface-border-strong: rgba(255, 255, 255, 0.14);
  --divider:           rgba(255, 255, 255, 0.06);

  /* ── Text ─────────────────────────────────────── */
  --text-primary:      #ffffff;
  --text-secondary:    rgba(255, 255, 255, 0.72);
  --text-muted:        #8d969e;
  --text-faint:        #c9c9cd;
  --text-disabled:     rgba(255, 255, 255, 0.24);

  /* ── Semantic ─────────────────────────────────── */
  --positive:          #428619;
  --positive-text:     #6fcf4a;
  --positive-bg:       rgba(67, 134, 25, 0.12);
  --negative:          #e61e49;
  --negative-text:     #ff6b8a;
  --negative-bg:       rgba(230, 30, 73, 0.12);
  --pending:           #b09000;
  --pending-text:      #f0c040;
  --pending-bg:        rgba(176, 144, 0, 0.12);

  /* ── Brand Accent (use sparingly) ─────────────── */
  --accent:            #494fdf;
  --accent-bright:     #4f55f1;
  --accent-deep:       #3a40c4;
  --accent-bg:         rgba(73, 79, 223, 0.12);

  /* ── Category Palette ─────────────────────────── */
  --cat-1:  #494fdf;   /* cobalt      — primary / uncategorized */
  --cat-2:  #00a87e;   /* teal        — food & dining */
  --cat-3:  #e61e49;   /* pink        — shopping */
  --cat-4:  #b09000;   /* yellow      — transport */
  --cat-5:  #007bc2;   /* blue        — bills & utilities */
  --cat-6:  #ec7e00;   /* orange      — entertainment */
  --cat-7:  #936d62;   /* brown       — health */
  --cat-8:  #8d969e;   /* stone       — other */

  /* ── Border Radius ────────────────────────────── */
  --radius-full: 9999px;
  --radius-lg:   20px;
  --radius-md:   12px;
  --radius-sm:   8px;

  /* ── Spacing ──────────────────────────────────── */
  --space-1:   4px;
  --space-2:   8px;
  --space-3:   12px;
  --space-4:   16px;
  --space-5:   20px;
  --space-6:   24px;
  --space-8:   32px;
  --space-10:  40px;
  --space-12:  48px;
  --space-16:  64px;

  /* ── Sidebar ──────────────────────────────────── */
  --sidebar-width:           240px;
  --sidebar-collapsed-width: 64px;

  /* ── Z-index ──────────────────────────────────── */
  --z-base:    0;
  --z-card:    10;
  --z-overlay: 20;
  --z-modal:   30;
  --z-tooltip: 40;
}
```

---

## TypeScript Token Map

For use in Recharts and JS-driven styling where CSS vars aren't accessible:

```ts
// src/design/tokens.ts
export const tokens = {
  canvas:           '#0a0a0a',
  surface:          '#111214',
  surfaceRaised:    '#16181a',
  surfaceBorder:    'rgba(255,255,255,0.08)',
  textPrimary:      '#ffffff',
  textSecondary:    'rgba(255,255,255,0.72)',
  textMuted:        '#8d969e',
  positiveText:     '#6fcf4a',
  negativeText:     '#ff6b8a',
  pendingText:      '#f0c040',
  accent:           '#494fdf',
  categories: [
    '#494fdf', // cat-1
    '#00a87e', // cat-2
    '#e61e49', // cat-3
    '#b09000', // cat-4
    '#007bc2', // cat-5
    '#ec7e00', // cat-6
    '#936d62', // cat-7
    '#8d969e', // cat-8
  ] as const,
} as const;

export type TokenKey = keyof typeof tokens;
```

---

## Category Config

```ts
// src/design/categories.ts
export interface CategoryConfig {
  key: string;
  label: string;
  color: string;        // CSS var reference
  colorHex: string;     // Hardcoded for Recharts
  icon: string;         // Lucide icon name
}

export const CATEGORIES: CategoryConfig[] = [
  { key: 'food',          label: 'Food & Dining',   color: 'var(--cat-2)', colorHex: '#00a87e', icon: 'UtensilsCrossed' },
  { key: 'shopping',      label: 'Shopping',        color: 'var(--cat-3)', colorHex: '#e61e49', icon: 'ShoppingBag' },
  { key: 'transport',     label: 'Transport',       color: 'var(--cat-4)', colorHex: '#b09000', icon: 'Car' },
  { key: 'bills',         label: 'Bills & Utilities',color: 'var(--cat-5)', colorHex: '#007bc2', icon: 'Zap' },
  { key: 'entertainment', label: 'Entertainment',   color: 'var(--cat-6)', colorHex: '#ec7e00', icon: 'Tv' },
  { key: 'health',        label: 'Health',          color: 'var(--cat-7)', colorHex: '#936d62', icon: 'Heart' },
  { key: 'income',        label: 'Income',          color: 'var(--positive-text)', colorHex: '#6fcf4a', icon: 'TrendingUp' },
  { key: 'other',         label: 'Other',           color: 'var(--cat-8)', colorHex: '#8d969e', icon: 'MoreHorizontal' },
];

export const getCategoryConfig = (key: string): CategoryConfig =>
  CATEGORIES.find(c => c.key === key) ?? CATEGORIES[CATEGORIES.length - 1];
```

---

## Sidebar Navigation

```ts
// src/design/navigation.ts
export const NAV_ITEMS = [
  { key: 'dashboard',     label: 'Dashboard',     icon: 'LayoutDashboard', path: '/' },
  { key: 'transactions',  label: 'Transactions',  icon: 'List',            path: '/transactions' },
  { key: 'accounts',      label: 'Accounts',      icon: 'CreditCard',      path: '/accounts' },
  { key: 'budgets',       label: 'Budgets',       icon: 'PieChart',        path: '/budgets' },
  { key: 'trends',        label: 'Trends',        icon: 'TrendingUp',      path: '/trends' },
  { key: 'settings',      label: 'Settings',      icon: 'Settings',        path: '/settings' },
];
```

Sidebar item styles:
- Inactive: background `transparent`, text `var(--text-muted)`
- Hover: background `var(--surface-raised)`, text `var(--text-primary)`, transition 120ms
- Active: background `var(--accent-bg)`, text `var(--accent-bright)`, icon in `var(--accent)`
- Height: 44px, `border-radius: var(--radius-md)`, padding `0 12px`, gap `10px`

---

## Responsive Breakpoints

| Name | Width | Changes |
|---|---|---|
| Desktop | ≥ 1280px | Sidebar 240px expanded, 3-col card grid |
| Tablet  | 768–1279px | Sidebar 64px (icons only), 2-col grid |
| Mobile  | < 768px | Sidebar becomes bottom nav bar, 1-col grid |

Mobile bottom nav: 5 icons, height 64px, background `var(--surface)`, `border-top: 1px solid var(--surface-border)`.
