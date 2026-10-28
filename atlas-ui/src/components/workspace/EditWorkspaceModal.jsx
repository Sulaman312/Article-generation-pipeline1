import { useEffect, useRef, useState } from "react";
import * as api from "../../services/api";
import { useToast } from "../../context/ToastContext";
import { isImageFile, readImageFileAsBase64, LOGO_ACCEPT } from "../../utils/readImageFile";
import WorkspaceLogo from "./WorkspaceLogo";
import LogoFitImage from "./LogoFitImage";
import "./ManualArticleForm.css";
import "./EditWorkspaceModal.css";

const MAX_LOGO_BYTES = 2 * 1024 * 1024;

const EMPTY_CMS = {
  provider: "none",
  collection_id: "",
  site_short_name: "",
  field_body: "",
  field_run_id: "",
  field_meta_title: "",
  field_meta_description: "",
  field_published_date: "",
  token: "",
  token_set: false,
  token_hint: "",
};

export default function EditWorkspaceModal({
  clientId,
  displayName,
  logoVersion = 0,
  onClose,
  onSaved,
}) {
  const { toast } = useToast();
  const [name, setName] = useState(displayName || "");
  const [liveUrlBase, setLiveUrlBase] = useState("");
  const [cms, setCms] = useState(EMPTY_CMS);
  const [loadingSettings, setLoadingSettings] = useState(true);
  const [logoFile, setLogoFile] = useState(null);
  const [logoPreview, setLogoPreview] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const logoInputRef = useRef(null);
  const initialRef = useRef({
    name: displayName || "",
    liveUrlBase: "",
    cms: EMPTY_CMS,
  });

  useEffect(() => {
    let alive = true;
    setName(displayName || "");
    setLiveUrlBase("");
    setCms(EMPTY_CMS);
    setLoadingSettings(true);
    setLogoFile(null);
    setLogoPreview((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return null;
    });
    if (logoInputRef.current) logoInputRef.current.value = "";
    setError(null);

    api
      .getClientSettings(clientId)
      .then((data) => {
        if (!alive) return;
        const nextName = data?.display_name || displayName || "";
        const nextLive = data?.live_url_base || "";
        const c = data?.cms || {};
        const nextCms = {
          ...EMPTY_CMS,
          provider: c.provider === "webflow" ? "webflow" : "none",
          collection_id: c.collection_id || "",
          site_short_name: c.site_short_name || "",
          field_body: c.field_body || "",
          field_run_id: c.field_run_id || "",
          field_meta_title: c.field_meta_title || "",
          field_meta_description: c.field_meta_description || "",
          field_published_date: c.field_published_date || "",
          token: "",
          token_set: Boolean(c.token_set),
          token_hint: c.token_hint || "",
        };
        setName(nextName);
        setLiveUrlBase(nextLive);
        setCms(nextCms);
        initialRef.current = {
          name: nextName,
          liveUrlBase: nextLive,
          cms: { ...nextCms },
        };
      })
      .catch((err) => {
        if (!alive) return;
        setError(err?.message || String(err));
      })
      .finally(() => {
        if (alive) setLoadingSettings(false);
      });

    return () => {
      alive = false;
    };
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

  function setCmsField(key, value) {
    setCms((prev) => ({ ...prev, [key]: value }));
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
      const initial = initialRef.current;
      const nameChanged = trimmed !== (initial.name || "").trim();
      const liveChanged =
        liveUrlBase.trim().replace(/\/+$/, "") !==
        (initial.liveUrlBase || "").trim().replace(/\/+$/, "");
      const cmsChanged =
        cms.provider !== initial.cms.provider ||
        cms.collection_id !== initial.cms.collection_id ||
        cms.site_short_name !== initial.cms.site_short_name ||
        cms.field_body !== initial.cms.field_body ||
        cms.field_run_id !== initial.cms.field_run_id ||
        cms.field_meta_title !== initial.cms.field_meta_title ||
        cms.field_meta_description !== initial.cms.field_meta_description ||
        cms.field_published_date !== initial.cms.field_published_date ||
        Boolean(cms.token.trim());

      const settingsChanged = nameChanged || liveChanged || cmsChanged;
      const patch = {};
      // Always send display_name when saving settings so older backends
      // that still require it accept CMS-only updates.
      if (settingsChanged) patch.display_name = trimmed;
      if (liveChanged || cmsChanged) patch.live_url_base = liveUrlBase.trim();
      if (cmsChanged) {
        patch.cms = {
          provider: cms.provider === "webflow" ? "webflow" : "none",
        };
        if (cms.provider === "webflow") {
          patch.cms.collection_id = cms.collection_id.trim();
          patch.cms.site_short_name = cms.site_short_name.trim();
          patch.cms.field_body = cms.field_body.trim();
          patch.cms.field_run_id = cms.field_run_id.trim();
          patch.cms.field_meta_title = cms.field_meta_title.trim();
          patch.cms.field_meta_description = cms.field_meta_description.trim();
          patch.cms.field_published_date = cms.field_published_date.trim();
          if (cms.token.trim()) patch.cms.token = cms.token.trim();
        }
      }

      if (Object.keys(patch).length) {
        await api.updateClient(clientId, patch);
      }
      if (logoFile) {
        const b64 = await readImageFileAsBase64(logoFile);
        await api.uploadClientLogo(clientId, b64, logoFile.name);
        logoUpdated = true;
      }
      if (!Object.keys(patch).length && !logoUpdated) {
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

  const busy = saving || loadingSettings;

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
              disabled={busy}
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
                  accept={LOGO_ACCEPT}
                  onChange={handleLogoChange}
                  disabled={busy}
                />
                <label htmlFor="ws-edit-logo" className="btn btn-secondary btn-sm">
                  {logoFile ? "Change logo" : "Upload logo"}
                </label>
                {logoFile ? (
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={clearLogo}
                    disabled={busy}
                  >
                    Remove
                  </button>
                ) : null}
              </div>
            </div>
          </div>

          <fieldset className="ws-edit-cms" disabled={busy}>
            <legend className="ws-edit-cms-legend">Content to CMS</legend>
            <p className="manual-article-logo-hint ws-edit-cms-hint">
              Choose a CMS per workspace. Use <strong>None</strong> when this
              client has no CMS integration. Webflow fields fall back to global
              `.env` when left blank. Token is never shown; leave blank to keep
              the current token.
            </p>

            <div>
              <label className="label" htmlFor="ws-edit-cms-provider">
                CMS provider
              </label>
              <select
                id="ws-edit-cms-provider"
                className="input"
                value={cms.provider}
                onChange={(e) => setCmsField("provider", e.target.value)}
                disabled={busy}
              >
                <option value="none">None (disabled)</option>
                <option value="webflow">Webflow</option>
              </select>
            </div>

            {cms.provider === "webflow" ? (
              <>
                <div>
                  <label className="label" htmlFor="ws-edit-live-url">
                    Live URL base
                  </label>
                  <input
                    id="ws-edit-live-url"
                    className="input"
                    value={liveUrlBase}
                    onChange={(e) => setLiveUrlBase(e.target.value)}
                    placeholder="https://example.com/blog"
                    disabled={busy}
                  />
                </div>

                <div>
                  <label className="label" htmlFor="ws-edit-token">
                    Webflow token
                    {cms.token_set ? (
                      <span className="ws-edit-token-hint">
                        {" "}
                        (saved {cms.token_hint || "••••"})
                      </span>
                    ) : null}
                  </label>
                  <input
                    id="ws-edit-token"
                    className="input"
                    type="password"
                    autoComplete="off"
                    value={cms.token}
                    onChange={(e) => setCmsField("token", e.target.value)}
                    placeholder={
                      cms.token_set
                        ? "Leave blank to keep current token"
                        : "API token"
                    }
                    disabled={busy}
                  />
                </div>

                <div>
                  <label className="label" htmlFor="ws-edit-collection">
                    Collection ID
                  </label>
                  <input
                    id="ws-edit-collection"
                    className="input"
                    value={cms.collection_id}
                    onChange={(e) => setCmsField("collection_id", e.target.value)}
                    placeholder="Webflow collection ID"
                    disabled={busy}
                  />
                </div>

                <div>
                  <label className="label" htmlFor="ws-edit-site-short">
                    Designer site short name
                  </label>
                  <input
                    id="ws-edit-site-short"
                    className="input"
                    value={cms.site_short_name}
                    onChange={(e) =>
                      setCmsField("site_short_name", e.target.value)
                    }
                    placeholder="arsuno-site"
                    disabled={busy}
                  />
                  <p className="ws-edit-cms-hint">
                    From your Designer URL:{" "}
                    <code>https://arsuno-site.design.webflow.com/…</code> → use{" "}
                    <code>arsuno-site</code>. Used to open the CMS item after
                    Content to CMS.
                  </p>
                </div>

                <div className="ws-edit-cms-grid">
                  <div>
                    <label className="label" htmlFor="ws-edit-field-body">
                      Body field slug
                    </label>
                    <input
                      id="ws-edit-field-body"
                      className="input"
                      value={cms.field_body}
                      onChange={(e) => setCmsField("field_body", e.target.value)}
                      placeholder="content---1"
                      disabled={busy}
                    />
                  </div>
                  <div>
                    <label className="label" htmlFor="ws-edit-field-run">
                      Run ID field slug
                    </label>
                    <input
                      id="ws-edit-field-run"
                      className="input"
                      value={cms.field_run_id}
                      onChange={(e) => setCmsField("field_run_id", e.target.value)}
                      placeholder="(optional)"
                      disabled={busy}
                    />
                  </div>
                  <div>
                    <label className="label" htmlFor="ws-edit-field-meta-title">
                      Meta title field
                    </label>
                    <input
                      id="ws-edit-field-meta-title"
                      className="input"
                      value={cms.field_meta_title}
                      onChange={(e) =>
                        setCmsField("field_meta_title", e.target.value)
                      }
                      placeholder="(optional)"
                      disabled={busy}
                    />
                  </div>
                  <div>
                    <label className="label" htmlFor="ws-edit-field-meta-desc">
                      Meta description field
                    </label>
                    <input
                      id="ws-edit-field-meta-desc"
                      className="input"
                      value={cms.field_meta_description}
                      onChange={(e) =>
                        setCmsField("field_meta_description", e.target.value)
                      }
                      placeholder="description"
                      disabled={busy}
                    />
                  </div>
                  <div>
                    <label className="label" htmlFor="ws-edit-field-date">
                      Published date field
                    </label>
                    <input
                      id="ws-edit-field-date"
                      className="input"
                      value={cms.field_published_date}
                      onChange={(e) =>
                        setCmsField("field_published_date", e.target.value)
                      }
                      placeholder="published-date"
                      disabled={busy}
                    />
                  </div>
                </div>
              </>
            ) : (
              <p className="manual-article-logo-hint">
                Content to CMS is off for this workspace. Articles stop at Final
                Output.
              </p>
            )}
          </fieldset>

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
              disabled={!name.trim() || busy}
            >
              {saving ? "Saving…" : "Save changes"}
            </button>
          </footer>
        </form>
      </div>
    </div>
  );
}
