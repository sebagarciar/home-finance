// Shared Recharts configuration for the light canvas.
// Never use Recharts defaults on the dashboard.

export const chart = {
  grid: {
    stroke: '#eceef3',
    vertical: false,
  },
  axis: {
    stroke: 'transparent',
    tick: { fill: '#646876', fontSize: 11 },
    tickLine: false,
    axisLine: false,
  },
  cursor: { fill: 'rgba(29,31,38,0.04)' },
} as const
