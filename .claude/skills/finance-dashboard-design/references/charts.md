# Recharts Configuration & Chart Patterns

Read this file when building or modifying any chart component.
All Recharts usage in the app MUST follow these patterns — never use Recharts defaults on a dark background.

---

## Global Chart Theme

```ts
// src/design/chartTheme.ts
import { tokens } from './tokens';

export const chartTheme = {
  // Grid
  grid: {
    stroke: 'rgba(255,255,255,0.06)',
    strokeDasharray: '0',       // solid, very faint
    vertical: false,            // horizontal lines only
  },
  // Axes
  axis: {
    stroke: 'none',             // no axis lines
    tick: {
      fill: tokens.textMuted,
      fontSize: 11,
      fontFamily: 'Inter, sans-serif',
    },
  },
  // Tooltip
  tooltip: {
    contentStyle: {
      background: tokens.surfaceRaised,
      border: `1px solid ${tokens.surfaceBorder}`,
      borderRadius: 12,
      padding: '10px 14px',
      boxShadow: 'none',
    },
    labelStyle: {
      color: tokens.textMuted,
      fontSize: 11,
      marginBottom: 4,
    },
    itemStyle: {
      color: tokens.textPrimary,
      fontSize: 13,
      fontWeight: 600,
    },
    cursor: { fill: 'rgba(255,255,255,0.04)' },
  },
  // Legend
  legend: {
    iconType: 'circle' as const,
    iconSize: 8,
    wrapperStyle: {
      fontSize: 12,
      color: tokens.textMuted,
      paddingTop: 8,
    },
  },
} as const;
```

---

## Custom Tooltip Component

Always use this instead of Recharts' default tooltip:

```tsx
// src/components/charts/CustomTooltip.tsx
import { formatCurrency } from '@/utils/format';

interface TooltipProps {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string }>;
  label?: string;
}

export const CustomTooltip = ({ active, payload, label }: TooltipProps) => {
  if (!active || !payload?.length) return null;

  return (
    <div style={{
      background: 'var(--surface-raised)',
      border: '1px solid var(--surface-border)',
      borderRadius: 12,
      padding: '10px 14px',
      minWidth: 140,
    }}>
      {label && (
        <p style={{ color: 'var(--text-muted)', fontSize: 11, marginBottom: 6 }}>
          {label}
        </p>
      )}
      {payload.map((entry) => (
        <div key={entry.name} style={{ display: 'flex', justifyContent: 'space-between', gap: 16 }}>
          <span style={{ color: entry.color, fontSize: 12 }}>{entry.name}</span>
          <span style={{ color: 'var(--text-primary)', fontWeight: 600, fontSize: 13 }}>
            {formatCurrency(entry.value)}
          </span>
        </div>
      ))}
    </div>
  );
};
```

---

## Chart Patterns

### 1. Spending Over Time (Area Chart)

Used on the main dashboard. Shows monthly spend vs income.

```tsx
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, ResponsiveContainer, Tooltip } from 'recharts';
import { chartTheme } from '@/design/chartTheme';
import { CustomTooltip } from './CustomTooltip';
import { tokens } from '@/design/tokens';

export const SpendingAreaChart = ({ data }: { data: MonthlyData[] }) => (
  <ResponsiveContainer width="100%" height={200}>
    <AreaChart data={data} margin={{ top: 4, right: 0, bottom: 0, left: -20 }}>
      <defs>
        <linearGradient id="incomeGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="5%"  stopColor={tokens.positiveText} stopOpacity={0.25} />
          <stop offset="95%" stopColor={tokens.positiveText} stopOpacity={0} />
        </linearGradient>
        <linearGradient id="spendGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="5%"  stopColor={tokens.negativeText} stopOpacity={0.20} />
          <stop offset="95%" stopColor={tokens.negativeText} stopOpacity={0} />
        </linearGradient>
      </defs>
      <CartesianGrid
        strokeDasharray={chartTheme.grid.strokeDasharray}
        stroke={chartTheme.grid.stroke}
        vertical={chartTheme.grid.vertical}
      />
      <XAxis
        dataKey="month"
        axisLine={false}
        tickLine={false}
        tick={chartTheme.axis.tick}
      />
      <YAxis
        axisLine={false}
        tickLine={false}
        tick={chartTheme.axis.tick}
        tickFormatter={(v) => `€${(v / 1000).toFixed(0)}k`}
      />
      <Tooltip content={<CustomTooltip />} cursor={chartTheme.tooltip.cursor} />
      <Area
        type="monotone" dataKey="income" name="Income"
        stroke={tokens.positiveText} strokeWidth={2}
        fill="url(#incomeGrad)" dot={false} activeDot={{ r: 4, fill: tokens.positiveText }}
      />
      <Area
        type="monotone" dataKey="spend" name="Spending"
        stroke={tokens.negativeText} strokeWidth={2}
        fill="url(#spendGrad)" dot={false} activeDot={{ r: 4, fill: tokens.negativeText }}
      />
    </AreaChart>
  </ResponsiveContainer>
);
```

### 2. Category Breakdown (Donut Chart)

Used in the spending breakdown card. Inner label shows total.

```tsx
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts';

interface DonutProps {
  data: Array<{ key: string; label: string; value: number; color: string }>;
  total: number;
}

export const CategoryDonut = ({ data, total }: DonutProps) => (
  <div style={{ position: 'relative', width: '100%', height: 200 }}>
    <ResponsiveContainer>
      <PieChart>
        <Pie
          data={data}
          cx="50%"
          cy="50%"
          innerRadius={64}
          outerRadius={88}
          paddingAngle={2}
          dataKey="value"
          stroke="none"
        >
          {data.map((entry) => (
            <Cell key={entry.key} fill={entry.color} />
          ))}
        </Pie>
        <Tooltip content={<CustomTooltip />} />
      </PieChart>
    </ResponsiveContainer>
    {/* Inner label */}
    <div style={{
      position: 'absolute',
      top: '50%', left: '50%',
      transform: 'translate(-50%, -50%)',
      textAlign: 'center',
      pointerEvents: 'none',
    }}>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>Total</div>
      <div style={{ fontSize: 18, fontWeight: 600, color: 'var(--text-primary)' }}>
        {formatCurrency(total)}
      </div>
    </div>
  </div>
);
```

### 3. Monthly Bar Chart

Used for budget vs actual comparison.

```tsx
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, ResponsiveContainer, Tooltip, Cell } from 'recharts';
import { tokens } from '@/design/tokens';

export const MonthlyBarChart = ({ data }: { data: BudgetData[] }) => (
  <ResponsiveContainer width="100%" height={180}>
    <BarChart data={data} barSize={24} margin={{ top: 4, right: 0, bottom: 0, left: -20 }}>
      <CartesianGrid stroke={chartTheme.grid.stroke} vertical={false} />
      <XAxis dataKey="month" axisLine={false} tickLine={false} tick={chartTheme.axis.tick} />
      <YAxis axisLine={false} tickLine={false} tick={chartTheme.axis.tick} />
      <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)', radius: 6 }} />
      <Bar dataKey="actual" name="Actual" radius={[6, 6, 0, 0]}>
        {data.map((entry) => (
          <Cell
            key={entry.month}
            fill={entry.actual > entry.budget ? tokens.negativeText : tokens.positiveText}
            fillOpacity={0.85}
          />
        ))}
      </Bar>
      <Bar dataKey="budget" name="Budget" radius={[6, 6, 0, 0]}
        fill="rgba(255,255,255,0.08)"
      />
    </BarChart>
  </ResponsiveContainer>
);
```

### 4. Sparkline (inline trend, no axes)

Used inside stat cards for a quick trend line.

```tsx
import { LineChart, Line, ResponsiveContainer, Tooltip } from 'recharts';

interface SparklineProps {
  data: number[];
  color?: string;
  height?: number;
}

export const Sparkline = ({ data, color = tokens.accent, height = 40 }: SparklineProps) => {
  const chartData = data.map((value, i) => ({ i, value }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={chartData}>
        <Line
          type="monotone" dataKey="value"
          stroke={color} strokeWidth={1.5}
          dot={false} activeDot={false}
        />
        <Tooltip content={() => null} />
      </LineChart>
    </ResponsiveContainer>
  );
};
```

---

## ChartCard Wrapper

Wrap every chart in this component — never use `ResponsiveContainer` naked:

```tsx
// src/components/charts/ChartCard.tsx
interface ChartCardProps {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  minHeight?: number;
}

export const ChartCard = ({ title, subtitle, action, children, minHeight = 240 }: ChartCardProps) => (
  <div className="card" style={{ minHeight }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
      <div>
        <h3 style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)', margin: 0 }}>
          {title}
        </h3>
        {subtitle && (
          <p style={{ fontSize: 12, color: 'var(--text-muted)', margin: '2px 0 0' }}>
            {subtitle}
          </p>
        )}
      </div>
      {action}
    </div>
    {children}
  </div>
);
```

---

## Format Utilities

```ts
// src/utils/format.ts
export const formatCurrency = (value: number, currency = 'EUR'): string =>
  new Intl.NumberFormat('es-ES', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
  }).format(value);

export const formatCompact = (value: number): string =>
  new Intl.NumberFormat('es-ES', {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value);

export const formatSign = (value: number): string =>
  value >= 0 ? `+${formatCurrency(value)}` : formatCurrency(value);
```
