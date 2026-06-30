import "./WorkspaceLogo.css";

/** Square favicon / logo slot (company icons are typically square). */
export default function LogoFitImage({
  src,
  size = 40,
  className = "",
  title = "",
  onError,
}) {
  const px = typeof size === "number" ? size : 40;

  return (
    <div
      className={`ws-logo-frame ws-logo-frame--favicon ${className}`.trim()}
      style={{ width: px, height: px }}
      title={title}
    >
      <img className="ws-logo" src={src} alt="" onError={onError} />
    </div>
  );
}
