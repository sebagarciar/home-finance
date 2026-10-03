import { useInvestorProfile, usePortfolioReviewLatest } from '../../api/hooks'
import { useNav } from '../../lib/nav'
import { ReviewSurface } from './ReviewSurface'

// Container: the review surface once risk answers exist. The answers (and all
// money inputs) live in Forecast → Profile, the single household profile.
export function PortfolioHealth() {
  const profileQ = useInvestorProfile()
  const latestQ = usePortfolioReviewLatest()
  const { go } = useNav()
  const toProfile = () => go('forecast', { view: 'profile' })

  if (profileQ.isLoading || latestQ.isLoading) return <HealthSkeleton />

  if (profileQ.data?.profile == null) {
    return (
      <div className="card">
        <div className="card-header">
          <div>
            <h2 className="card-title">Portfolio Health Review</h2>
            <div className="card-meta">
              Answer the risk &amp; goal questions in your household profile first. The review
              checks your portfolio against the target they set; spending and cash come from your data.
            </div>
          </div>
          <button className="btn primary" onClick={toProfile}>Open profile</button>
        </div>
      </div>
    )
  }

  return <ReviewSurface review={latestQ.data?.review ?? null} onEdit={toProfile} />
}

function HealthSkeleton() {
  return (
    <div className="card">
      <div className="skel" style={{ height: 18, width: 220, marginBottom: 16 }} />
      <div className="skel" style={{ height: 72, marginBottom: 16 }} />
      <div className="skel" style={{ height: 120 }} />
    </div>
  )
}
