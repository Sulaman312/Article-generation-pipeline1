import { useEffect, useRef, useState } from "react";
import * as api from "../../services/api";
import { useToast } from "../../context/ToastContext";
import { isImageFile, readImageFileAsBase64 } from "../../utils/readImageFile";
import WorkspaceLogo from "./WorkspaceLogo";
import LogoFitImage from "./LogoFitImage";
import "./ManualArticleForm.css";
import "./EditWorkspaceModal.css";

const MAX_LOGO_BYTES = 2 * 1024 * 1024;

export default function EditWorkspaceModal({
  clientId,
  displayName,
  logoVersion = 0,
  onClose,
  onSaved,
}) {
  const { toast } = useToast();
  const [name, setName] = useState(displayName || "");
  const [logoFile, setLogoFile] = useState(null);
  const [logoPreview, setLogoPreview] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const logoInputRef = useRef(null);

  useEffect(() => {
    setName(displayName || "");
    setLogoFile(null);
    setLogoPreview((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return null;
    });
    if (logoInputRef.current) logoInputRef.current.value = "";
    setError(null);
  }, [clientId, displayName]);

  useEffect(() => {
    function onKey(e) {
      if (e.key === "Escape" && !saving) onClose?.();
    }
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [onClose, saving]);

  function clearLogo() {
    setLogoPreview((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return null;
    });
    setLogoFile(null);
    if (logoInputRef.current) logoInputRef.current.value = "";
  }

  function handleLogoChange(e) {
    const file = e.target.files?.[0];
    if (!file) {
      clearLogo();
      return;
    }
    if (!isImageFile(file)) {
      setError("Logo must be an image (PNG, JPG, WebP, GIF, or SVG).");
      clearLogo();
      return;
    }
    if (file.size > MAX_LOGO_BYTES) {
      setError("Logo must be 2 MB or smaller.");
      clearLogo();
      return;
    }
    setError(null);
    setLogoFile(file);
    setLogoPreview((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return URL.createObjectURL(file);
    });
  }

  async function handleSave(e) {
    e?.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Workspace name is required.");
      return;
    }
    setSaving(true);
    setError(null);
    let logoUpdated = false;
    try {
      const nameChanged = trimmed !== (displayName || "").trim();
      if (nameChanged) {
        await api.updateClient(clientId, { display_name: trimmed });
      }
      if (logoFile) {
        const b64 = await readImageFileAsBase64(logoFile);
        await api.uploadClientLogo(clientId, b64, logoFile.name);
        logoUpdated = true;
      }
      if (!nameChanged && !logoUpdated) {
        onClose?.();
        return;
      }
      toast("Workspace updated.", { variant: "success" });
      onSaved?.({ displayName: trimmed, logoUpdated });
    } catch (err) {
      const msg = err?.message || String(err);
      setError(msg);
      toast(msg, { variant: "error" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="ws-edit-overlay" onClick={() => !saving && onClose?.()}>
      <div
        className="ws-edit-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="ws-edit-title"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="ws-edit-header">
          <h2 id="ws-edit-title" className="ws-edit-title">
            Edit workspace
          </h2>
          <button
            type="button"
            className="ws-edit-close"
            aria-label="Close"
            disabled={saving}
            onClick={onClose}
          >
            ×
          </button>
        </header>

        <form className="ws-edit-body" onSubmit={handleSave}>
          <div>
            <label className="label" htmlFor="ws-edit-name">
              Workspace name
            </label>
            <input
              id="ws-edit-name"
              className="input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
              disabled={saving}
            />
          </div>

          <div className="manual-article-logo-row">
            <div className="manual-article-logo-preview">
              {logoPreview ? (
                <LogoFitImage src={logoPreview} size={48} />
              ) : (
                <WorkspaceLogo
                  clientId={clientId}
                  size={48}
                  cacheKey={logoVersion}
                />
              )}
            </div>
            <div className="manual-article-logo-fields">
              <span className="label">Workspace logo</span>
              <span className="manual-article-logo-hint">
                Optional — square favicon or logo (PNG/SVG, max 2 MB).
              </span>
              <div className="manual-article-logo-actions">
                <input
                  ref={logoInputRef}
                  id="ws-edit-logo"
                  type="file"
                  className="manual-article-logo-input"
                  accept="image/png,image/jpeg,image/webp,image/gif,image/svg+xml"
                  onChange={handleLogoChange}
                  disabled={saving}
                />
                <label htmlFor="ws-edit-logo" className="btn btn-secondary btn-sm">
                  {logoFile ? "Change logo" : "Upload logo"}
                </label>
                {logoFile ? (
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={clearLogo}
                    disabled={saving}
                  >
                    Remove
                  </button>
                ) : null}
              </div>
            </div>
          </div>

          {error ? (
            <p className="manual-article-error" role="alert">
              {error}
            </p>
          ) : null}

          <footer className="ws-edit-footer">
            <button
              type="button"
              className="btn"
              disabled={saving}
              onClick={onClose}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={!name.trim() || saving}
            >
              {saving ? "Saving…" : "Save changes"}
            </button>
          </footer>
        </form>
      </div>
    </div>
  );
}
