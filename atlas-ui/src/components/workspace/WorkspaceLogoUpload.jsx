import { useRef, useState } from "react";
import * as api from "../../services/api";
import { useToast } from "../../context/ToastContext";
import { isImageFile, readImageFileAsBase64 } from "../../utils/readImageFile";
import WorkspaceLogo from "./WorkspaceLogo";
import LogoFitImage from "./LogoFitImage";
import "./ManualArticleForm.css";

const MAX_LOGO_BYTES = 2 * 1024 * 1024;

export default function WorkspaceLogoUpload({
  clientId,
  compact = false,
  inline = false,
  logoVersion = 0,
  onUpdated,
}) {
  const { toast } = useToast();
  const [preview, setPreview] = useState(null);
  const [localKey, setLocalKey] = useState(0);
  const cacheKey = localKey || logoVersion;
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const inputRef = useRef(null);

  function clearPreview() {
    setPreview((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return null;
    });
    if (inputRef.current) inputRef.current.value = "";
  }

  async function uploadFile(file) {
    if (!file || saving) return;
    if (!isImageFile(file)) {
      const msg = "Logo must be an image (PNG, JPG, WebP, GIF, or SVG).";
      setError(msg);
      toast(msg, { variant: "error" });
      clearPreview();
      return;
    }
    if (file.size > MAX_LOGO_BYTES) {
      const msg = "Logo must be 2 MB or smaller.";
      setError(msg);
      toast(msg, { variant: "error" });
      clearPreview();
      return;
    }

    setError(null);
    setSaving(true);
    const objectUrl = URL.createObjectURL(file);
    setPreview((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return objectUrl;
    });

    try {
      const b64 = await readImageFileAsBase64(file);
      await api.uploadClientLogo(clientId, b64, file.name);
      const stamp = Date.now();
      setLocalKey(stamp);
      onUpdated?.(stamp);
      toast("Workspace logo saved.", { variant: "success" });
    } catch (err) {
      const msg = err?.message || String(err);
      setError(msg);
      toast(msg, { variant: "error" });
      clearPreview();
    } finally {
      setSaving(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  async function handleFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    await uploadFile(file);
  }

  const showSavedLogo = !preview && cacheKey > 0;

  if (inline) {
    return (
      <div className="ws-logo-upload ws-logo-upload--inline">
        <input
          ref={inputRef}
          id={`ws-logo-inline-${clientId}`}
          type="file"
          className="manual-article-logo-input"
          accept="image/png,image/jpeg,image/webp,image/gif,image/svg+xml,.png,.jpg,.jpeg,.webp,.gif,.svg"
          onChange={handleFile}
          disabled={saving}
        />
        <label
          htmlFor={`ws-logo-inline-${clientId}`}
          className="ws-logo-upload-inline-link"
        >
          {saving ? "Saving logo…" : "Change logo"}
        </label>
        {error ? (
          <p className="manual-article-error ws-logo-upload-inline-error" role="alert">
            {error}
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <div className={`ws-logo-upload${compact ? " ws-logo-upload--compact" : ""}`}>
      <div className="manual-article-logo-row">
        <div className="manual-article-logo-preview">
          {preview ? (
            <LogoFitImage src={preview} size={48} />
          ) : (
            <WorkspaceLogo clientId={clientId} size={48} cacheKey={cacheKey} />
          )}
        </div>
        <div className="manual-article-logo-fields">
          <span className="label">Workspace logo</span>
          <span className="manual-article-logo-hint">
            {saving
              ? "Uploading…"
              : "Square favicon or logo — saves automatically (max 2 MB)."}
          </span>
          <div className="manual-article-logo-actions">
            <input
              ref={inputRef}
              id={`ws-logo-${clientId}`}
              type="file"
              className="manual-article-logo-input"
              accept="image/png,image/jpeg,image/webp,image/gif,image/svg+xml,.png,.jpg,.jpeg,.webp,.gif,.svg"
              onChange={handleFile}
              disabled={saving}
            />
            <label htmlFor={`ws-logo-${clientId}`} className="btn btn-secondary btn-sm">
              {saving ? "Saving…" : showSavedLogo ? "Replace logo" : "Upload logo"}
            </label>
          </div>
          {error ? (
            <p className="manual-article-error" role="alert">
              {error}
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
