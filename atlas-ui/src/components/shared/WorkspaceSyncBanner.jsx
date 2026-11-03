import { useEffect, useState } from "react";
import * as api from "../../services/api";

/**
 * Clear “Workspace syncing…” banner while Mongo hydration is in progress.
 * Separates API warm-up from app chrome loading.
 */
export default function WorkspaceSyncBanner() {
  const [syncing, setSyncing] = useState(false);
  const [detail, setDetail] = useState("");

  useEffect(() => {
    let cancelled = false;
    let timer = null;

    async function check() {
      try {
        const health = await api.getHealth();
        if (cancelled) return;
        const hydration = health?.hydration || {};
        const enabled = Boolean(hydration.enabled);
        const status = String(hydration.status || "");
        const warming =
          enabled &&
          status !== "ready" &&
          status !== "disabled";
        setSyncing(warming);
        if (warming) {
          const attempt = hydration.attempt ? ` (attempt ${hydration.attempt})` : "";
          setDetail(
            status === "failed" || status === "retrying"
              ? `Reconnecting to workspace storage${attempt}…`
              : `Workspace syncing${attempt}…`
          );
        } else {
          setDetail("");
        }
      } catch {
        /* ignore — network errors handled elsewhere */
      }
    }

    function onForcedSync(e) {
      setSyncing(true);
      setDetail(e?.detail?.message || "Workspace syncing…");
      check();
    }

    check();
    timer = window.setInterval(check, 4000);
    window.addEventListener("cf:workspace-syncing", onForcedSync);
    return () => {
      cancelled = true;
      if (timer) window.clearInterval(timer);
      window.removeEventListener("cf:workspace-syncing", onForcedSync);
    };
  }, []);

  if (!syncing) return null;

  return (
    <div className="workspace-sync-banner" role="status" aria-live="polite">
      <span className="workspace-sync-spinner" aria-hidden />
      <span>{detail || "Workspace syncing…"}</span>
      <span className="workspace-sync-hint">You can keep browsing — runs unlock when ready.</span>
    </div>
  );
}
