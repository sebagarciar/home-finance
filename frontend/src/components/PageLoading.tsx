/** Suspense fallback shown while a lazily-loaded page chunk downloads.
 * Mirrors the card-grid silhouette so the swap doesn't jump. */
export function PageLoading() {
  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div className="skel" style={{ height: 220 }} />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div className="skel" style={{ height: 160 }} />
        <div className="skel" style={{ height: 160 }} />
      </div>
    </div>
  )
}
