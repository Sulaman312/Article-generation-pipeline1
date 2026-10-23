import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "../../services/api";
import "./CmsPublishPanel.css";

const CONFIRM_WORD = "UPDATE";

const PILL_TEXT = {
  disabled: "CMS disabled",
  not_sent: "Not sent yet",
  draft: "Draft (not published)",
  published: "Published",
  changes_in_draft: "Published, newer changes waiting",
  missing: "Draft not found in Webflow",
};

function isHttpUrl(value) {
  return /^https?:\/\//i.test(String(value || ""));
}

/** Webflow status + live link + "send draft again" (typed confirmation). */
export default function CmsPublishPanel({ client, runId, toast }) {
  const [info, setInfo] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [sending, setSending] = useState(false);
  const alive = useRef(true);
  const requestId = useRef(0);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const loadStatus = useCallback(async () => {
    const id = ++requestId.current;
    setLoading(true);
    setError("");
    try {
      const data = await api.getCmsStatus(client, runId);
      if (alive.current && id === requestId.current) setInfo(data);
    } catch (e) {
      if (alive.current && id === requestId.current) {
        setError(e?.message || String(e));
      }
    } finally {
      if (alive.current && id === requestId.current) setLoading(false);
    }
  }, [client, runId]);

  useEffect(() => {
    setInfo(null);
    setConfirming(false);
    setConfirmText("");
    loadStatus();
  }, [loadStatus]);

  const confirmOk =
    confirmText.trim().toUpperCase() === CONFIRM_WORD && !sending;

  async function handleSend() {
    if (!confirmOk) return;
    setSending(true);
    try {
      await api.runStep(client, runId, "content_to_cms", "");
      window.dispatchEvent(
        new CustomEvent("cf:run-step-complete", {
          detail: { clientId: client, runId, stepKey: "content_to_cms" },
        })
      );
      toast?.("Draft sent to Webflow again.", {
        variant: "success",
        duration: 3500,
      });
      if (alive.current) {
        setConfirming(false);
        setConfirmText("");
      }
      await loadStatus();
    } catch (e) {
      toast?.(e?.message || String(e), { variant: "error", duration: 12000 });
    } finally {
      if (alive.current) setSending(false);
    }
  }

  const status = info?.status || "";
  const disabled = status === "disabled" || info?.provider === "none";
  const isLive = status === "published" || status === "changes_in_draft";
  const liveUrl = isHttpUrl(info?.live_url) ? info.live_url : "";
  const title =
    info?.provider === "webflow"
      ? "Webflow"
      : disabled
        ? "CMS"
        : "CMS";

  return (
    <div className="cms-panel" aria-label="CMS status">
      <div className="cms-panel-head">
        <span className="cms-panel-title">{title}</span>
        {info ? (
          <span className={`cms-pill cms-pill--${status}`}>
            {PILL_TEXT[status] || status}
          </span>
        ) : loading ? (
          <span className="cms-panel-muted">Checking…</span>
        ) : null}
        <div className="cms-panel-actions">
          {!disabled ? (
            <button
              type="button"
              className="btn btn-sm btn-edit-artifact"
              onClick={loadStatus}
              disabled={loading || sending}
              title="Ask the CMS again whether this article is published"
            >
              {loading ? "Checking…" : "Refresh status"}
            </button>
          ) : null}
          {info?.sent && !confirming && !disabled ? (
            <button
              type="button"
              className="btn btn-sm btn-edit-artifact"
              onClick={() => setConfirming(true)}
              disabled={sending}
            >
              Update draft in CMS
            </button>
          ) : null}
        </div>
      </div>

      {disabled ? (
        <p className="cms-panel-muted">
          CMS is disabled for this workspace. Open{" "}
          <strong>Edit workspace</strong> and set the CMS provider to Webflow
          if this client publishes to Webflow.
        </p>
      ) : null}

      {error && !disabled ? <p className="cms-panel-error">{error}</p> : null}

      {!disabled && isLive ? (
        liveUrl ? (
          <p className="cms-panel-line">
            <span className="cms-panel-label">Live article</span>
            <a href={liveUrl} target="_blank" rel="noopener noreferrer">
              {liveUrl}
            </a>
          </p>
        ) : (
          <p className="cms-panel-muted">
            Published. Set a live URL base on this workspace (Edit workspace)
            or WEBFLOW_LIVE_URL_BASE in .env to show the link here.
          </p>
        )
      ) : null}

      {!disabled && status === "changes_in_draft" ? (
        <p className="cms-panel-muted">
          The live article is unchanged. Newer changes are saved in Webflow
          and go live only when you publish them there.
        </p>
      ) : null}
      {!disabled && status === "missing" ? (
        <p className="cms-panel-muted">
          Use the Re-run button in the sidebar to create a new draft.
        </p>
      ) : null}

      {!disabled && confirming ? (
        <div className="cms-confirm">
          <p className="cms-confirm-text">
            This overwrites the title, body, meta description and published
            date of the Webflow item with the current Final Output.
            {isLive
              ? " The live article does not change until you publish in Webflow."
              : ""}{" "}
            Type <strong>{CONFIRM_WORD}</strong> to confirm.
          </p>
          <div className="cms-confirm-row">
            <input
              type="text"
              className="cms-confirm-input"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSend();
              }}
              placeholder={CONFIRM_WORD}
              autoFocus
              disabled={sending}
              aria-label={`Type ${CONFIRM_WORD} to confirm`}
            />
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={handleSend}
              disabled={!confirmOk}
            >
              {sending ? "Sending…" : "Confirm and update"}
            </button>
            <button
              type="button"
              className="btn btn-sm btn-edit-artifact"
              onClick={() => {
                setConfirming(false);
                setConfirmText("");
              }}
              disabled={sending}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}