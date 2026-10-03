import { Overview } from '../components/Overview'
import { NeedsAttention } from '../components/NeedsAttention'

// The household home answers one question: are we OK? History and
// breakdowns live under Spending → Trends.
export function Dashboard() {
  return (
    <>
      <NeedsAttention />
      <Overview />
    </>
  )
}
