import { useEffect, useMemo, useRef, useState } from "react";
import * as api from "../../services/api";
import PageHeader from "../shared/PageHeader";
import WorkspaceLogo from "./WorkspaceLogo";
import LogoFitImage from "./LogoFitImage";
import { isImageFile, readImageFileAsBase64 } from "../../utils/readImageFile";
import {
  CONTEXT_FILE_LABELS,
  PIPELINE_CONTEXT_FILES_ORDERED,
} from "../../constants/contextFiles";
import { workspaceDisplayName } from "../../utils/formatWorkspaceLabel";
import "./ManualArticleForm.css";
import "./ClientsGrid.css";

const MAX_LOGO_BYTES = 2 * 1024 * 1024;

function fallbackCatalogEntries() {
  return PIPELINE_CONTEXT_FILES_ORDERED.map((filename) => ({
    filename,
    label: CONTEXT_FILE_LABELS[filename] || filename,
  }));
}

export default function ClientsGrid({
  onOpenClient,
  logoVersions = {},
  onClientLogoSaved,
}) {
  const [catalogEntries, setCatalogEntries] = useState(null);
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState("");
  const [seedContext, setSeedContext] = useState(() =>
    Object.fromEntries(
      PIPELINE_CONTEXT_FILES_ORDERED.map((filename) => [filename, ""])
    )
  );
  const [showSeedContext, setShowSeedContext] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState(null);
  const [logoFile, setLogoFile] = useState(null);
  const [logoPreview, setLogoPreview] = useState(null);
  const logoInputRef = useRef(null);

  async function load() {
    setLoading(true);
    try {
      const list = await api.getClients();
      setClients(list);
      setError(null);
    } catch (e) {
      const unreachable =
        e?.message?.includes("Failed to fetch") ||
        (e?.name === "TypeError" &&
          (String(e?.message).includes("fetch") ||
            String(e?.message).includes("NetworkError") ||
            String(e?.message).includes("NETWORK_ERROR"))) ||
        e?.message?.includes("timed out");
      setError(
        unreachable
          ? `Could not reach the API (${api.describeApiTargetForHumans()}). ` +
              `Terminal 1 (repo root): python main.py · ` +
              `Terminal 2 (atlas-ui): npm start · ` +
              `Then open http://localhost:3000 and click Retry.`
          : e?.message || String(e)
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    api
      .getContextFilesCatalog()
      .then((rows) => {
        const ok = rows.filter((r) => r?.filename);
        setCatalogEntries(ok.length ? ok : null);
      })
      .catch(() => setCatalogEntries(null));
  }, []);

  const pipelineEntries = useMemo(
    () =>
      catalogEntries?.length ? catalogEntries : fallbackCatalogEntries(),
    [catalogEntries]
  );

  const emptySeed = useMemo(
    () => () =>
      Object.fromEntries(
        pipelineEntries.map((entry) => [entry.filename, ""])
      ),
    [pipelineEntries]
  );

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

  function resetForm() {
    setNewName("");
    setSeedContext(emptySeed());
    setShowSeedContext(false);
    clearLogo();
    setAdding(false);
  }

  async function handleCreate(e) {
    e?.preventDefault();
    const name = newName.trim();
    if (!name) return;
    setCreating(true);
    setError(null);
    try {
      const createOpts = {};
      if (logoFile) {
        createOpts.logo_base64 = await readImageFileAsBase64(logoFile);
        createOpts.logo_filename = logoFile.name;
      }
      await api.createClient(name, { ...createOpts, display_name: name });
      if (logoFile) {
        onClientLogoSaved?.(name);
      }
      const writes = [];
      for (const entry of pipelineEntries) {
        const fn = entry.filename;
        const body = (seedContext[fn] || "").trim();
        if (body) {
          writes.push(api.saveContextFile(name, fn, body));
        }
      }
      if (writes.length > 0) {
        await Promise.all(writes);
      }
      resetForm();
      await load();
      onOpenClient(name);
    } catch (err) {
      setError(err?.message || String(err));
    } finally {
      setCreating(false);
    }
  }

  function updateSeed(fn, value) {
    setSeedContext((prev) => ({ ...prev, [fn]: value }));
  }

  const hasAnySeedContent = pipelineEntries.some(
    (entry) => (seedContext[entry.filename] || "").trim().length > 0
  );

  return (
    <div className="page">
      <PageHeader
        title="Workspaces"
        subtitle="Pick a client workspace to open the editorial pipeline."
        actions={
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setAdding((v) => !v)}
          >
            + New Client
          </button>
        }
      />

      {adding ? (
        <form
          onSubmit={handleCreate}
          style={{
            background: "var(--panel)",
            border: "1px solid var(--border)",
            borderRadius: 12,
            padding: 18,
            marginBottom: 20,
            boxShadow: "var(--shadow-sm)",
            display: "flex",
            flexDirection: "column",
            gap: 14,
          }}
        >
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: 10,
              alignItems: "flex-end",
            }}
          >
            <div style={{ flex: "1 1 200px", minWidth: 0 }}>
              <label className="label" htmlFor="new-client">
                Workspace name
              </label>
              <input
                id="new-client"
                className="input"
                placeholder="e.g. Gauchat or acme_co"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                autoFocus
              />
            </div>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={!newName.trim() || creating}
            >
              {creating ? "Creating…" : "Create"}
            </button>
            <button
              type="button"
              className="btn"
              disabled={creating}
              onClick={() => resetForm()}
            >
              Cancel
            </button>
          </div>

          <div className="manual-article-logo-row">
            <div className="manual-article-logo-preview" aria-hidden={!logoPreview}>
              {logoPreview ? (
                <LogoFitImage src={logoPreview} size={48} />
              ) : (
                <span className="manual-article-logo-placeholder">Logo</span>
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
                  id="new-client-logo"
                  type="file"
                  className="manual-article-logo-input"
                  accept="image/png,image/jpeg,image/webp,image/gif,image/svg+xml"
                  onChange={handleLogoChange}
                  disabled={creating}
                />
                <label htmlFor="new-client-logo" className="btn btn-secondary btn-sm">
                  {logoFile ? "Change logo" : "Upload logo"}
                </label>
                {logoFile ? (
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={clearLogo}
                    disabled={creating}
                  >
                    Remove
                  </button>
                ) : null}
              </div>
            </div>
          </div>

          <button
            type="button"
            className="btn"
            style={{ alignSelf: "flex-start", fontSize: 13 }}
            onClick={() => setShowSeedContext((v) => !v)}
          >
            {showSeedContext ? "▼" : "►"} Optional: seed context files (Markdown)
            {hasAnySeedContent ? " · has drafts" : ""}
          </button>

          {showSeedContext ? (
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 12,
                maxHeight: "min(62vh, 520px)",
                overflowY: "auto",
                paddingRight: 4,
              }}
            >
              <p
                style={{
                  margin: 0,
                  fontSize: 13,
                  color: "var(--text-muted)",
                  lineHeight: 1.5,
                }}
              >
                Only non-empty fields are saved to{" "}
                <code>clients/&lt;id&gt;/context/</code> after the workspace is
                created. You can always edit files later from the client
                workspace.
              </p>
              {pipelineEntries.map((entry) => (
                <div key={entry.filename}>
                  <label className="label" htmlFor={`seed-${entry.filename}`}>
                    {entry.label ?? CONTEXT_FILE_LABELS[entry.filename] ?? entry.filename}{" "}
                    <span style={{ fontWeight: 400, opacity: 0.75 }}>
                      ({entry.filename})
                    </span>
                  </label>
                  <textarea
                    id={`seed-${entry.filename}`}
                    className="input"
                    rows={5}
                    placeholder={`Paste Markdown for ${entry.filename}…`}
                    value={seedContext[entry.filename] ?? ""}
                    onChange={(e) => updateSeed(entry.filename, e.target.value)}
                    style={{
                      resize: "vertical",
                      fontFamily:
                        'ui-monospace, "Cascadia Code", Menlo, Consolas, monospace',
                      fontSize: 13,
                      lineHeight: 1.45,
                    }}
                  />
                </div>
              ))}
            </div>
          ) : null}
        </form>
      ) : null}

      {error ? (
        <div
          style={{
            background: "var(--error-soft)",
            border: "1px solid #fecaca",
            color: "var(--error-text)",
            padding: "12px 14px",
            borderRadius: 10,
            fontSize: 13.5,
            marginBottom: 16,
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            gap: 12,
          }}
        >
          <span style={{ flex: "1 1 280px" }}>{error}</span>
          <button type="button" className="btn btn-sm" onClick={() => load()}>
            Retry
          </button>
        </div>
      ) : null}

      {loading ? (
        <div className="empty-state">
          <span className="spinner" /> &nbsp; loading clients…
        </div>
      ) : clients.length === 0 ? (
        <div
          className="card"
          style={{
            textAlign: "center",
            color: "var(--text-muted)",
            padding: 36,
            borderStyle: "dashed",
          }}
          onClick={() => setAdding(true)}
        >
          No clients yet. Click{" "}
          <strong style={{ color: "var(--text)" }}>+ New Client</strong> to
          create your first workspace.
        </div>
      ) : (
        <div className="clients-grid">
          {clients.map((c) => (
            <ClientCard
              key={c.id}
              clientId={c.id}
              displayName={workspaceDisplayName(c.id, c.display_name)}
              logoVersion={logoVersions[c.id] || 0}
              onOpen={() => onOpenClient(c.id)}
            />
          ))}
          <div className="card client-card-add" onClick={() => setAdding(true)}>
            + New workspace
          </div>
        </div>
      )}
    </div>
  );
}

function ClientCard({ clientId, displayName, onOpen, logoVersion = 0 }) {
  return (
    <div className="card client-card" onClick={onOpen}>
      <div className="client-card-inner">
        <WorkspaceLogo clientId={clientId} size={44} cacheKey={logoVersion} />
        <div className="client-card-text">
          <div className="card-title client-card-name">{displayName}</div>
          <div className="client-card-action">Open workspace →</div>
        </div>
      </div>
    </div>
  );
}
