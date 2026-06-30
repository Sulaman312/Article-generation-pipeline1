import { useCallback, useEffect, useState } from "react";
import * as api from "../../services/api";
import MarkdownArtifactPanel from "../shared/MarkdownArtifactPanel";

/** Fallback when API is unavailable (dev offline). */
export const WORKSPACE_ARTIFACT_SPECS = [
  {
    filename: "personas.md",
    title: "Audience personas",
    description:
      "Who you write for — roles, goals, objections, and vocabulary.",
    placeholder:
      "## Primary persona\n- Role:\n- Goals:\n- What they need from this content:\n",
  },
  {
    filename: "context.md",
    title: "Company context",
    description:
      "Positioning, offerings, and facts the pipeline should treat as ground truth.",
    placeholder:
      "## Company overview\n- Company name:\n- What you sell:\n- Key differentiators:\n",
  },
  {
    filename: "writing_guidelines.md",
    title: "Writing guidelines",
    description:
      "Tone, banned hype, preferred phrasing, and structure expectations.",
    placeholder:
      "## Voice\n- Tone:\n- Reading level:\n\n## Format (pipeline-enforced)\n" +
      "Sentence case headings, BLUF under every H2/H3, max 30 words per sentence, " +
      "max 4 sentences per paragraph, no em dashes, 2–3 inline CTAs at H2 breaks.\n\n" +
      "## Avoid\n- …\n\n## Preferred words\n- …\n",
  },
];

function ContextArtifactEditor({ client, spec, toast, variant = "card" }) {
  const [draft, setDraft] = useState("");
  const [baseline, setBaseline] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [savedFlash, setSavedFlash] = useState(false);
  const [editing, setEditing] = useState(false);

  const dirty = draft !== baseline;
  const { filename, title, description, placeholder } = spec;
  const isPage = variant === "page";
  const isCustom = Boolean(spec.custom);

  const load = useCallback(async () => {
    if (!client) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.getContextFile(client, filename);
      const text = data?.content ?? "";
      setDraft(text);
      setBaseline(text);
    } catch (e) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }, [client, filename]);

  useEffect(() => {
    setEditing(false);
    load();
  }, [load]);

  function handleCancelEdit() {
    setDraft(baseline);
    setEditing(false);
  }

  async function handleSave() {
    if (!dirty || saving) return;
    setSaving(true);
    setError(null);
    try {
      await api.saveContextFile(client, filename, draft);
      setBaseline(draft);
      setEditing(false);
      setSavedFlash(true);
      window.setTimeout(() => setSavedFlash(false), 2200);
      toast?.("Saved", { variant: "success", duration: 2500 });
    } catch (e) {
      const msg = e?.message || String(e);
      setError(msg);
      toast?.(msg, { variant: "error", duration: 10000 });
    } finally {
      setSaving(false);
    }
  }

  const taId = `ctx-${filename.replace(/\W/g, "")}`;

  const wrapClass = isPage
    ? "client-context-card client-context-card--page"
    : "client-context-card";

  return (
    <div className={wrapClass}>
      <div className="client-context-card-head">
        <div>
          <h3 className="client-context-card-title">{title}</h3>
          <p className="client-context-card-desc">{description}</p>
        </div>
        <div className="client-context-card-actions">
          {savedFlash ? (
            <span className="client-context-saved">Saved</span>
          ) : null}
          {editing ? (
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              disabled={saving || loading}
              onClick={handleCancelEdit}
            >
              Cancel
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-sm btn-secondary"
              disabled={loading}
              onClick={() => setEditing(true)}
            >
              Edit
            </button>
          )}
          <button
            type="button"
            className="btn btn-sm btn-primary"
            disabled={!dirty || saving || loading || !editing}
            onClick={handleSave}
          >
            {saving ? (
              <>
                <span className="spinner spinner-light" /> Saving…
              </>
            ) : (
              "Save"
            )}
          </button>
        </div>
      </div>
      {error && !loading ? (
        <div className="client-context-error" role="alert">
          {error}
        </div>
      ) : null}
      {loading ? (
        <div className="client-context-loading">
          <span className="spinner" /> Loading…
        </div>
      ) : (
        <>
          <label className="label visually-hidden" htmlFor={taId}>
            {title} (Markdown)
          </label>
          <div className="client-context-artifact-panel">
            <MarkdownArtifactPanel
              content={draft}
              baseline={baseline}
              draft={draft}
              editing={editing}
              onDraftChange={setDraft}
              onEditingChange={setEditing}
              showEditInToolbar={false}
              textareaRows={isPage ? 22 : 14}
              textareaPlaceholder={
                placeholder ||
                "Write Markdown here — headings, lists, and links are supported."
              }
              previewNode={
                !editing && !draft.trim() ? (
                  <p className="client-context-empty-preview">
                    No content yet. Click <strong>Edit</strong> to add Markdown.
                  </p>
                ) : null
              }
            />
          </div>
          <div className="client-context-meta">
            <code className="client-context-filename">{filename}</code>
            <span>
              {" "}
              · Markdown
              {isCustom ? " · custom artifact" : " · used by the content pipeline"}
            </span>
          </div>
        </>
      )}
    </div>
  );
}

function AddArtifactForm({ client, onCreated, onCancel, toast }) {
  const [slug, setSlug] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    const slugVal = slug.trim();
    const titleVal = title.trim();
    if (!slugVal || !titleVal) return;
    setSaving(true);
    setError(null);
    try {
      const artifact = await api.createWorkspaceArtifact(client, {
        slug: slugVal,
        title: titleVal,
        description: description.trim(),
      });
      toast?.("Artifact created", { variant: "success", duration: 2500 });
      onCreated?.(artifact);
    } catch (err) {
      const msg = err?.message || String(err);
      setError(msg);
      toast?.(msg, { variant: "error", duration: 10000 });
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="artifact-add-form" onSubmit={handleSubmit}>
      <h3 className="artifact-add-form-title">New artifact</h3>
      <p className="artifact-add-form-lede">
        Creates a Markdown file in this workspace. Use lowercase letters,
        numbers, and hyphens for the file id.
      </p>
      {error ? (
        <div className="client-context-error" role="alert">
          {error}
        </div>
      ) : null}
      <label className="label" htmlFor="artifact-slug">
        File id
      </label>
      <input
        id="artifact-slug"
        className="input"
        value={slug}
        onChange={(e) => setSlug(e.target.value)}
        placeholder="e.g. competitor-notes"
        autoComplete="off"
        disabled={saving}
      />
      <label className="label" htmlFor="artifact-title">
        Display title
      </label>
      <input
        id="artifact-title"
        className="input"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="e.g. Competitor notes"
        disabled={saving}
      />
      <label className="label" htmlFor="artifact-desc">
        Description <span className="label-optional">(optional)</span>
      </label>
      <input
        id="artifact-desc"
        className="input"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Short note for your team"
        disabled={saving}
      />
      <div className="artifact-add-form-actions">
        <button
          type="button"
          className="btn btn-ghost"
          onClick={onCancel}
          disabled={saving}
        >
          Cancel
        </button>
        <button
          type="submit"
          className="btn btn-primary"
          disabled={saving || !slug.trim() || !title.trim()}
        >
          {saving ? (
            <>
              <span className="spinner spinner-light" /> Creating…
            </>
          ) : (
            "Create artifact"
          )}
        </button>
      </div>
    </form>
  );
}

/** Cards for all workspace artifacts; choosing one opens the editor in the parent. */
export function WorkspaceArtifactPicker({
  client,
  onSelect,
  onSpecsChange,
}) {
  const [specs, setSpecs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [adding, setAdding] = useState(false);
  const [deletingFn, setDeletingFn] = useState(null);

  const load = useCallback(async () => {
    if (!client) return;
    setLoading(true);
    setError(null);
    try {
      const rows = await api.listWorkspaceArtifacts(client);
      const ok = rows.filter((r) => r?.filename);
      const next = ok.length ? ok : WORKSPACE_ARTIFACT_SPECS;
      setSpecs(next);
      onSpecsChange?.(next);
    } catch (e) {
      setError(e?.message || String(e));
      setSpecs(WORKSPACE_ARTIFACT_SPECS);
      onSpecsChange?.(WORKSPACE_ARTIFACT_SPECS);
    } finally {
      setLoading(false);
    }
  }, [client, onSpecsChange]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleDelete(e, spec) {
    e.stopPropagation();
    e.preventDefault();
    if (!spec.removable || !spec.custom) return;
    const ok = window.confirm(
      `Delete "${spec.title}" (${spec.filename})?\n\nThis removes the file permanently.`
    );
    if (!ok) return;
    setDeletingFn(spec.filename);
    try {
      await api.deleteWorkspaceArtifact(client, spec.filename);
      await load();
    } catch (err) {
      window.alert(err?.message || String(err));
    } finally {
      setDeletingFn(null);
    }
  }

  function handleCreated(artifact) {
    setAdding(false);
    load().then(() => {
      if (artifact?.filename) onSelect?.(artifact.filename);
    });
  }

  return (
    <div className="artifact-picker-wrap">
      <div className="artifact-picker-toolbar">
        <p className="artifacts-page-lede">
          Markdown reference files for this workspace. Pipeline steps use the
          built-in context files; custom artifacts are for your team’s notes.
        </p>
        {!adding ? (
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => setAdding(true)}
          >
            + Add artifact
          </button>
        ) : null}
      </div>

      {adding ? (
        <AddArtifactForm
          client={client}
          onCreated={handleCreated}
          onCancel={() => setAdding(false)}
        />
      ) : null}

      {error && !loading ? (
        <div className="client-context-error" role="alert">
          {error}
        </div>
      ) : null}

      {loading ? (
        <div className="client-context-loading" style={{ marginTop: 24 }}>
          <span className="spinner" /> Loading artifacts…
        </div>
      ) : (
        <div className="artifact-picker-grid" role="list">
          {specs.map((spec) => (
            <div key={spec.filename} className="artifact-picker-card-wrap">
              <button
                type="button"
                className="artifact-picker-card"
                onClick={() => onSelect(spec.filename)}
                aria-label={`Open ${spec.title} editor`}
              >
                <span className="artifact-picker-card-kicker">
                  {spec.custom ? "Custom file" : "Workspace file"}
                </span>
                <span className="artifact-picker-card-title">{spec.title}</span>
                <span className="artifact-picker-card-desc">
                  {spec.description}
                </span>
                {spec.exists === false ? (
                  <span className="artifact-picker-card-empty">Empty</span>
                ) : null}
              </button>
              {spec.removable ? (
                <button
                  type="button"
                  className="artifact-picker-delete"
                  title={`Delete ${spec.title}`}
                  disabled={deletingFn === spec.filename}
                  onClick={(e) => handleDelete(e, spec)}
                >
                  {deletingFn === spec.filename ? "…" : "Delete"}
                </button>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** Full-width editor with back control (parent supplies breadcrumb / header). */
export function WorkspaceArtifactEditorPage({
  client,
  filename,
  spec: specProp,
  toast,
  onBack,
}) {
  const [spec, setSpec] = useState(specProp ?? null);
  const [loading, setLoading] = useState(!specProp);

  useEffect(() => {
    if (specProp) {
      setSpec(specProp);
      setLoading(false);
      return;
    }
    if (!client || !filename) return;
    let cancelled = false;
    setLoading(true);
    api
      .listWorkspaceArtifacts(client)
      .then((rows) => {
        if (cancelled) return;
        const found =
          rows.find((r) => r.filename === filename) ||
          WORKSPACE_ARTIFACT_SPECS.find((s) => s.filename === filename);
        setSpec(found ?? null);
      })
      .catch(() => {
        if (!cancelled) {
          setSpec(
            WORKSPACE_ARTIFACT_SPECS.find((s) => s.filename === filename) ?? null
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [client, filename, specProp]);

  if (loading) {
    return (
      <div className="client-context-loading" style={{ marginTop: 32 }}>
        <span className="spinner" /> Loading…
      </div>
    );
  }

  if (!spec) return null;

  return (
    <div className="artifact-editor-page">
      <button
        type="button"
        className="btn btn-ghost artifact-back-btn"
        onClick={onBack}
      >
        <span className="artifact-back-chev" aria-hidden>
          ‹
        </span>
        All artifacts
      </button>
      <ContextArtifactEditor
        client={client}
        spec={spec}
        toast={toast}
        variant="page"
      />
    </div>
  );
}
