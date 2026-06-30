import { useEffect, useMemo, useRef, useState } from "react";
import * as api from "../../services/api";

export default function ContextEditorDrawer({ client, open, onClose }) {
  const [catalog, setCatalog] = useState([]);
  const [files, setFiles] = useState([]);
  const [activeFile, setActiveFile] = useState("");
  const [draft, setDraft] = useState("");
  const [baseline, setBaseline] = useState("");
  const [loadingList, setLoadingList] = useState(false);
  const [loadingFile, setLoadingFile] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [savedFlash, setSavedFlash] = useState(false);
  const [dropActive, setDropActive] = useState(false);

  /** When switching tabs after drop: apply draft after fetching server baseline once. */
  const importSeedRef = useRef(null);

  const dirty = draft !== baseline;

  useEffect(() => {
    api
      .getContextFilesCatalog()
      .then((rows) => setCatalog(rows.filter((r) => r?.filename)))
      .catch(() => setCatalog([]));
  }, []);

  useEffect(() => {
    if (!open || !client) return;
    let cancelled = false;
    setLoadingList(true);
    setError(null);
    api
      .listContextFiles(client)
      .then((list) => {
        if (cancelled) return;
        setFiles(list);
        const first = list[0]?.filename || "";
        setActiveFile(first);
      })
      .catch((e) => {
        if (!cancelled) setError(e?.message || String(e));
      })
      .finally(() => {
        if (!cancelled) setLoadingList(false);
      });
    return () => {
      cancelled = true;
    };
  }, [client, open]);

  useEffect(() => {
    if (!open || !client || !activeFile) return;
    const seed = importSeedRef.current;
    if (seed && seed.filename === activeFile) {
      importSeedRef.current = null;
      let cancelled = false;
      setLoadingFile(true);
      setError(null);
      api
        .getContextFile(client, activeFile)
        .then(({ content }) => {
          if (cancelled) return;
          setDraft(seed.content);
          setBaseline(content ?? "");
        })
        .catch((e) => {
          if (!cancelled) setError(e?.message || String(e));
        })
        .finally(() => {
          if (!cancelled) setLoadingFile(false);
        });
      return () => {
        cancelled = true;
      };
    }

    let cancelled = false;
    setLoadingFile(true);
    setError(null);
    api
      .getContextFile(client, activeFile)
      .then(({ content }) => {
        if (cancelled) return;
        setDraft(content ?? "");
        setBaseline(content ?? "");
      })
      .catch((e) => {
        if (!cancelled) setError(e?.message || String(e));
      })
      .finally(() => {
        if (!cancelled) setLoadingFile(false);
      });
    return () => {
      cancelled = true;
    };
  }, [client, open, activeFile]);

  useEffect(() => {
    if (!open) return;
    function onKey(e) {
      if (e.key === "Escape") onClose?.();
    }
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  async function handleSave() {
    if (!client || !activeFile || saving) return;
    setSaving(true);
    setError(null);
    try {
      await api.saveContextFile(client, activeFile, draft);
      setBaseline(draft);
      setSavedFlash(true);
      window.setTimeout(() => setSavedFlash(false), 2000);
      const list = await api.listContextFiles(client);
      setFiles(list);
    } catch (e) {
      setError(e?.message || String(e));
    } finally {
      setSaving(false);
    }
  }

  const labelByFilename = useMemo(() => {
    const m = {};
    for (const row of catalog) {
      if (row.filename) m[row.filename] = row.label || row.filename;
    }
    return m;
  }, [catalog]);

  const orderedRows = useMemo(() => {
    if (!catalog.length) return [...files];
    const byFn = Object.fromEntries(
      files.map((f) => [f.filename, f])
    );
    const rows = catalog
      .map((c) => byFn[c.filename])
      .filter(Boolean);
    return rows.length ? rows : [...files];
  }, [catalog, files]);

  const counts = useMemo(() => {
    let present = 0;
    for (const f of files) if (f.exists) present++;
    return {
      present,
      missing: Math.max(files.length - present, 0),
    };
  }, [files]);

  const normalizeMdName = (name) => {
    const base = String(name || "")
      .split(/[/\\]/)
      .pop();
    const lower = base.toLowerCase();
    return /\.md$/i.test(lower) ? lower : null;
  };

  const trySwitchFile = (fnLower, text) => {
    const rows = catalog.length ? orderedRows : files;
    const matched = rows.find(
      (r) => String(r.filename).toLowerCase() === fnLower
    );
    if (!matched) {
      setError(`${fnLower} is not in the pipeline allow-list.`);
      return false;
    }
    else if (matched.filename !== activeFile && dirty) {
      const ok = window.confirm(
        "You have unsaved changes on the current file. Switch and load the dropped content?"
      );
      if (!ok) return false;
      importSeedRef.current = { filename: matched.filename, content: text };
      setActiveFile(matched.filename);
      return false;
    } else if (matched.filename !== activeFile) {
      importSeedRef.current = { filename: matched.filename, content: text };
      setActiveFile(matched.filename);
      return false;
    }
    return true;
  };

  async function onDropMarkdown(e) {
    e.preventDefault();
    setDropActive(false);
    const fileList = e.dataTransfer?.files;
    if (!fileList?.length) return;
    const picks = [...fileList]
      .map((f) => ({ f, key: normalizeMdName(f.name) }))
      .filter((x) => x.key);

    if (!picks.length) {
      setError("Drop a .md file (Markdown).");
      return;
    }

    setError(null);
    if (picks.length > 1) {
      setError("Drop one Markdown file at a time.");
      return;
    }

    const { f, key } = picks[0];
    try {
      const text = await f.text();
      if (key === activeFile.toLowerCase()) {
        setDraft(text);
        return;
      }
      const allowSwitch = trySwitchFile(key, text);
      if (allowSwitch) setDraft(text);
    } catch (err) {
      setError(err?.message || String(err));
    }
  }

  if (!open) return null;

  return (
    <div className="ctx-overlay" onClick={onClose}>
      <aside
        className="ctx-drawer"
        style={{ width: "min(720px, 96vw)" }}
        onClick={(evt) => evt.stopPropagation()}
      >
        <header className="ctx-header">
          <div>
            <div className="eyebrow" style={{ marginBottom: 4 }}>
              Edit context
            </div>
            <div style={{ fontSize: 16, fontWeight: 600 }}>{client}</div>
            <div style={{ fontSize: 12.5, color: "var(--text-muted)", marginTop: 2 }}>
              Markdown under <code>clients/{client}/context/</code> · Paste or drag a .md file
              onto the drop zone below.
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {savedFlash ? (
              <span style={{ fontSize: 12.5, color: "var(--success-text)" }}>
                ✓ saved
              </span>
            ) : null}
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={!dirty || saving || loadingFile}
              onClick={handleSave}
            >
              {saving ? (
                <>
                  <span className="spinner spinner-light" /> Saving…
                </>
              ) : (
                "Save file"
              )}
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={onClose}
              aria-label="Close"
            >
              ✕
            </button>
          </div>
        </header>

        <div className="ctx-body" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {error ? (
            <div
              style={{
                background: "var(--error-soft)",
                border: "1px solid #fecaca",
                color: "var(--error-text)",
                padding: "10px 12px",
                borderRadius: 8,
                fontSize: 13,
              }}
            >
              {error}
            </div>
          ) : null}

          <div className="ctx-status-pills" aria-live="polite">
            <span className={`ctx-chip ctx-chip-present`}>
              {counts.present} on disk
            </span>
            <span className={`ctx-chip ctx-chip-missing`}>
              {counts.missing} missing
            </span>
          </div>

          {loadingList ? (
            <div className="empty-state" style={{ padding: 24 }}>
              <span className="spinner" /> &nbsp; loading file list…
            </div>
          ) : (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {orderedRows.map((row) => {
                const lbl = labelByFilename[row.filename] ?? row.filename;
                return (
                  <button
                    key={row.filename}
                    type="button"
                    className={`btn btn-sm ${row.filename === activeFile ? "btn-primary" : ""}`}
                    onClick={() => {
                      if (row.filename === activeFile) return;
                      if (
                        dirty &&
                        !window.confirm(
                          "You have unsaved changes. Switch file anyway?"
                        )
                      ) {
                        return;
                      }
                      setActiveFile(row.filename);
                    }}
                    title={row.exists ? `${row.bytes} bytes on disk` : "Not saved yet"}
                  >
                    <span>{row.filename}</span>
                    {" · "}
                    <strong style={{ fontWeight: 700 }}>
                      {row.exists ? "present" : "missing"}
                    </strong>
                  </button>
                );
              })}
            </div>
          )}

          <div
            className={`ctx-drop-zone${dropActive ? " ctx-drop-zone-active" : ""}`}
            onDragEnter={(evt) => {
              evt.preventDefault();
              evt.stopPropagation();
              setDropActive(true);
            }}
            onDragOver={(evt) => {
              evt.preventDefault();
              evt.stopPropagation();
            }}
            onDragLeave={(evt) => {
              evt.preventDefault();
              evt.stopPropagation();
              if (!evt.currentTarget.contains(evt.relatedTarget))
                setDropActive(false);
            }}
            onDrop={onDropMarkdown}
          >
            Drop a <strong style={{ color: "var(--text)" }}>.md</strong> file — name must match
            a pipeline file (for example{" "}
            <code style={{ fontFamily: "var(--font-mono)" }}>personas.md</code>). Applies to{" "}
            <strong>{activeFile || "(select a file)"}</strong> when names match.
            {labelByFilename[activeFile] ? (
              <span>
                {" "}
                Selected:{" "}
                <span style={{ color: "var(--text)", fontWeight: 600 }}>
                  {labelByFilename[activeFile]}
                </span>
              </span>
            ) : null}
          </div>

          {loadingFile ? (
            <div className="empty-state" style={{ padding: 24 }}>
              <span className="spinner" /> &nbsp; loading file…
            </div>
          ) : (
            <textarea
              value={draft}
              onChange={(evt) => setDraft(evt.target.value)}
              spellCheck={false}
              style={{
                width: "100%",
                minHeight: 420,
                flex: 1,
                fontFamily: "var(--font-mono)",
                fontSize: 13,
                lineHeight: 1.55,
                padding: 14,
                borderRadius: 10,
                border: "1px solid var(--border-strong)",
                background: "var(--panel)",
                color: "var(--text)",
                resize: "vertical",
              }}
              placeholder={`# ${activeFile}\n\nWrite markdown here…`}
            />
          )}
        </div>

        <footer className="ctx-footer">
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
            {dirty ? "Unsaved changes" : "Matching server copy"}
          </span>
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
            Only allow-listed filenames accepted by the API.
          </span>
        </footer>
      </aside>
    </div>
  );
}
