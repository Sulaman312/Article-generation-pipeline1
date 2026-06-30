import { useEffect, useState } from "react";
import { clientLogoUrl } from "../../services/api";
import { formatWorkspaceLabel } from "../../utils/formatWorkspaceLabel";
import LogoFitImage from "./LogoFitImage";
import "./WorkspaceLogo.css";

export default function WorkspaceLogo({
  clientId,
  size = 40,
  className = "",
  cacheKey = 0,
}) {
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
  }, [clientId, cacheKey]);

  const initials = String(clientId || "?")
    .slice(0, 2)
    .toUpperCase();
  const label = formatWorkspaceLabel(clientId);
  const px = typeof size === "number" ? size : 40;
  const src =
    cacheKey != null && cacheKey !== 0
      ? `${clientLogoUrl(clientId)}?v=${encodeURIComponent(String(cacheKey))}`
      : clientLogoUrl(clientId);

  if (failed) {
    return (
      <div
        className={`ws-logo ws-logo--fallback ${className}`.trim()}
        style={{ width: px, height: px }}
        aria-hidden
      >
        {initials}
      </div>
    );
  }

  return (
    <LogoFitImage
      src={src}
      size={px}
      className={className}
      title={label}
      onError={() => setFailed(true)}
    />
  );
}
