import { useState } from 'react'
import { useInvestorProfile, usePortfolioReviewLatest } from '../../api/hooks'
import { ProfileQuestionnaire } from './ProfileQuestionnaire'
import { ReviewSurface } from './ReviewSurface'

// Container: questionnaire until a profile exists (or while editing), then the
// review surface. The pieces live in sibling files; this file only routes
// between them.
export function PortfolioHealth() {
  const profileQ = useInvestorProfile()
  const latestQ = usePortfolioReviewLatest()
  const [editing, setEditing] = useState(false)

  if (profileQ.isLoading || latestQ.isLoading) return <HealthSkeleton />

  const profile = profileQ.data?.profile ?? null
  const review = latestQ.data?.review ?? null

  if (profile == null || editing) {
    return (
      <ProfileQuestionnaire
        initial={profile}
        onCancel={profile ? () => setEditing(false) : undefined}
        onDone={() => setEditing(false)}
      />
    )
  }

  return <ReviewSurface review={review} onEdit={() => setEditing(true)} />
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
