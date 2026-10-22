/**
 * Compact page title row — navigation lives in the sidebar / back button.
 */
export default function PageHeader({
  title,
  subtitle,
  actions,
  back,
  onBack,
  backLabel,
}) {
  return (
    <header className="page-head">
      <div className="page-head-main">
        {back ? (
          <button
            type="button"
            className="page-head-back"
            onClick={onBack}
            aria-label={backLabel || "Back"}
          >
            ←
          </button>
        ) : null}
        <div className="page-head-text">
          <h1 className="page-head-title">{title}</h1>
          {subtitle ? (
            <p className="page-head-subtitle">{subtitle}</p>
          ) : null}
        </div>
      </div>
      {actions ? <div className="page-head-actions">{actions}</div> : null}
    </header>
  );
}
