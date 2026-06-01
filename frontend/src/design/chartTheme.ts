// Shared Recharts configuration for the dark canvas.
// Never use Recharts defaults on the dashboard.

export const chart = {
  grid: {
    stroke: 'rgba(255,255,255,0.06)',
    vertical: false,
  },
  axis: {
    stroke: 'transparent',
    tick: { fill: '#8d969e', fontSize: 11 },
    tickLine: false,
    axisLine: false,
  },
  cursor: { fill: 'rgba(255,255,255,0.04)' },
} as const
