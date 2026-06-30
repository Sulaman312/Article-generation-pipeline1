import { useEffect, useState } from "react";
import * as api from "../../services/api";

export default function ContextDrawer({ client, open, onClose }) {
  const [summary, setSummary] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!open || !client) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .getContextSummary(client)
      .then((text) => {
        if (cancelled) return;
        setSummary(text);
      })
      .catch((e) => {
        if (!cancelled) setError(e?.message || String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [client, open]);

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

  if (!open) return null;

  return (
    <div className="ctx-overlay" onClick={onClose}>
      <aside className="ctx-drawer" onClick={(e) => e.stopPropagation()}>
        <header className="ctx-header">
          <div>
            <div
              className="eyebrow"
              style={{ marginBottom: 4 }}
            >
              Loaded Context
            </div>
            <div
              style={{
                fontSize: 16,
                fontWeight: 600,
                letterSpacing: "-0.01em",
              }}
            >
              {client}
            </div>
          </div>
          <button
            className="btn btn-ghost btn-sm"
            onClick={onClose}
            aria-label="Close"
            title="Close (Esc)"
          >
            ✕
          </button>
        </header>
        <div className="ctx-body">
          {loading ? (
            <div className="empty-state">
              <span className="spinner" /> &nbsp; loading context…
            </div>
          ) : error ? (
            <div
              style={{
                margin: 18,
                background: "var(--error-soft)",
                border: "1px solid #fecaca",
                color: "var(--error-text)",
                padding: "12px 14px",
                borderRadius: 10,
                fontSize: 13,
              }}
            >
              {error}
            </div>
          ) : (
            <ContextSummary text={summary} />
          )}
        </div>
        <footer className="ctx-footer">
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
            Generated live from <code>clients/{client}/context/</code>
          </span>
          <button
            className="btn btn-sm"
            onClick={() => {
              navigator.clipboard?.writeText(summary || "");
            }}
          >
            Copy summary
          </button>
        </footer>
      </aside>
    </div>
  );
}

function ContextSummary({ text }) {
  const sections = parseSummary(text);
  if (!sections.length) {
    return <div className="empty-state">no context loaded yet</div>;
  }
  return (
    <div className="ctx-sections">
      {sections.map((s, i) => (
        <Section key={i} section={s} />
      ))}
    </div>
  );
}

function Section({ section }) {
  if (section.title === "__meta__") {
    return (
      <div className="ctx-meta">
        {renderItems(section.items)}
      </div>
    );
  }
  return (
    <section className="ctx-card">
      <h3 className="ctx-section-title">{section.title}</h3>
      <div className="ctx-section-body">{renderItems(section.items)}</div>
    </section>
  );
}

function renderItems(lines) {
  const out = [];
  let bullets = [];
  let key = 0;

  function flush() {
    if (bullets.length) {
      out.push(
        <ul className="ctx-list" key={`ul-${key++}`}>
          {bullets.map((b, i) => (
            <li key={i}>{b}</li>
          ))}
        </ul>
      );
      bullets = [];
    }
  }

  for (const raw of lines) {
    const line = raw.replace(/\s+$/, "");
    const t = line.trim();
    if (!t) continue;

    const bm = t.match(/^[-•]\s+(.+)$/);
    if (bm) {
      bullets.push(stripPlaceholder(bm[1]));
      continue;
    }
    const om = t.match(/^\d+\.\s+(.+)$/);
    if (om) {
      bullets.push(stripPlaceholder(om[1]));
      continue;
    }
    flush();

    const kvm = t.match(/^([A-Z][A-Za-z][A-Za-z &/_-]*):\s*(.+)$/);
    if (kvm) {
      out.push(
        <div className="ctx-kv" key={`kv-${key++}`}>
          <div className="ctx-key">{kvm[1]}</div>
          <div className="ctx-val">{stripPlaceholder(kvm[2])}</div>
        </div>
      );
      continue;
    }

    const subm = t.match(/^([A-Z][A-Za-z][A-Za-z &/_-]*):\s*$/);
    if (subm) {
      out.push(
        <div className="ctx-sublabel" key={`sl-${key++}`}>
          {subm[1]}
        </div>
      );
      continue;
    }

    out.push(
      <div className="ctx-text" key={`t-${key++}`}>
        {stripPlaceholder(t)}
      </div>
    );
  }
  flush();
  return out;
}

function stripPlaceholder(value) {
  if (!value) return value;
  if (
    value === "[NOT PROVIDED]" ||
    value === "[NOT YET PROVIDED]"
  ) {
    return <span className="ctx-missing">not provided</span>;
  }
  return value;
}

function parseSummary(text) {
  if (!text) return [];
  const lines = text
    .split(/\r?\n/)
    .filter((l) => !/^---CONTEXT SUMMARY (START|END)---\s*$/.test(l.trim()));

  const sections = [];
  let current = null;
  let meta = null;

  function ensureMeta() {
    if (!meta) {
      meta = { title: "__meta__", items: [] };
      sections.push(meta);
    }
    return meta;
  }

  for (const raw of lines) {
    const line = raw.replace(/\s+$/, "");
    if (!line.trim()) continue;

    const headerMatch = line.match(/^([A-Z][A-Z0-9 ()/&,'-]+):\s*$/);
    if (headerMatch && !line.startsWith(" ")) {
      current = {
        title: titleCase(headerMatch[1].trim()),
        items: [],
      };
      sections.push(current);
      continue;
    }

    const metaMatch =
      !line.startsWith(" ") &&
      line.match(/^([A-Z][A-Z0-9 _-]+):\s*(.+)$/);
    if (metaMatch && !current) {
      ensureMeta().items.push(`${titleCase(metaMatch[1])}: ${metaMatch[2]}`);
      continue;
    }

    if (current) {
      current.items.push(line.replace(/^ {2}/, ""));
    } else {
      ensureMeta().items.push(line.trim());
    }
  }

  return sections;
}

function titleCase(text) {
  return text
    .toLowerCase()
    .replace(/(^|\s)([a-z])/g, (_, sp, c) => sp + c.toUpperCase())
    .replace(/\bAi\b/g, "AI")
    .replace(/\bCta\b/g, "CTA")
    .replace(/\bIcp\b/g, "ICP");
}
