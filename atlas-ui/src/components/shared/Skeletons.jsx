/** Lightweight loading placeholders (no full-page spinner). */

export function MatrixSkeleton({ rows = 5 }) {
  return (
    <div className="skeleton-matrix" aria-busy="true" aria-label="Loading runs">
      <div className="skeleton-matrix-head">
        <span className="skeleton-bar skeleton-bar--lg" />
        <span className="skeleton-bar" />
        <span className="skeleton-bar" />
        <span className="skeleton-bar" />
      </div>
      {Array.from({ length: rows }, (_, i) => (
        <div className="skeleton-matrix-row" key={i}>
          <span className="skeleton-bar skeleton-bar--title" />
          <span className="skeleton-dot" />
          <span className="skeleton-dot" />
          <span className="skeleton-dot" />
          <span className="skeleton-dot" />
        </div>
      ))}
    </div>
  );
}

export function ClientsSkeleton({ cards = 6 }) {
  return (
    <div className="skeleton-clients" aria-busy="true" aria-label="Loading workspaces">
      {Array.from({ length: cards }, (_, i) => (
        <div className="skeleton-client-card" key={i}>
          <span className="skeleton-logo" />
          <span className="skeleton-bar skeleton-bar--title" />
          <span className="skeleton-bar" />
        </div>
      ))}
    </div>
  );
}

export function ArtifactSkeleton() {
  return (
    <div className="skeleton-artifact" aria-busy="true" aria-label="Loading artifact">
      <span className="skeleton-bar skeleton-bar--lg" />
      <span className="skeleton-bar" />
      <span className="skeleton-bar" />
      <span className="skeleton-bar skeleton-bar--short" />
      <span className="skeleton-bar" />
      <span className="skeleton-bar skeleton-bar--short" />
    </div>
  );
}
