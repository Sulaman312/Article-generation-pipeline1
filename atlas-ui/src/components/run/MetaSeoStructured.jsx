import { useState } from "react";
import {
  charCountStatus,
  parseMetaSeoStructured,
} from "../../utils/parseMetaSeo";
import { copyTextToClipboard } from "../../utils/copyText";
import "./MetaSeoStructured.css";

const TITLE_RANGE = { min: 50, max: 60 };
const DESC_RANGE = { min: 120, max: 155 };

function CharBadge({ count, range }) {
  const status = charCountStatus(count, range.min, range.max);
  const label =
    status === "ok"
      ? `${count} chars`
      : status === "short"
        ? `${count} — short`
        : `${count} — long`;
  return (
    <span
      className={`meta-seo-char-badge meta-seo-char-badge--${status}`}
      title={`Target: ${range.min}–${range.max} characters`}
    >
      {label}
    </span>
  );
}

function OptionRow({ option, range, recommended = false, onCopy }) {
  const [copying, setCopying] = useState(false);

  async function handleCopy() {
    setCopying(true);
    try {
      await onCopy?.(option.text);
    } finally {
      setCopying(false);
    }
  }

  return (
    <li className={`meta-seo-option${recommended ? " meta-seo-option--pick" : ""}`}>
      <div className="meta-seo-option-head">
        <span className="meta-seo-option-num">{option.index}</span>
        {recommended ? (
          <span className="meta-seo-option-tag">Recommended</span>
        ) : null}
        <CharBadge count={option.charCount} range={range} />
        <button
          type="button"
          className="btn btn-sm meta-seo-copy-btn"
          onClick={handleCopy}
          disabled={copying}
          title="Copy this option"
        >
          {copying ? "…" : "Copy"}
        </button>
      </div>
      <p className="meta-seo-option-text">{option.text}</p>
    </li>
  );
}

function OptionSection({ title, hint, options, range, toast }) {
  if (!options?.length) return null;

  async function copyLine(text) {
    const ok = await copyTextToClipboard(text);
    if (ok) {
      toast?.("Copied to clipboard", { variant: "success", duration: 2500 });
    } else {
      toast?.("Could not copy", { variant: "error", duration: 3000 });
    }
  }

  return (
    <section className="meta-seo-section">
      <div className="meta-seo-section-head">
        <h3 className="meta-seo-section-title">{title}</h3>
        <span className="meta-seo-section-hint">{hint}</span>
      </div>
      <ol className="meta-seo-option-list">
        {options.map((opt, i) => (
          <OptionRow
            key={opt.index}
            option={opt}
            range={range}
            recommended={i === 0}
            onCopy={copyLine}
          />
        ))}
      </ol>
    </section>
  );
}

export default function MetaSeoStructured({ text, toast }) {
  const data = parseMetaSeoStructured(text);
  if (!data) return null;

  return (
    <div className="meta-seo-structured" aria-label="Meta title and description options">
      <div className="meta-seo-context">
        {data.pageType ? (
          <div className="meta-seo-context-item">
            <span className="meta-seo-context-label">Page type</span>
            <span className="meta-seo-context-value">{data.pageType}</span>
          </div>
        ) : null}
        {data.keyword ? (
          <div className="meta-seo-context-item">
            <span className="meta-seo-context-label">Target keyword</span>
            <span className="meta-seo-context-value">{data.keyword}</span>
          </div>
        ) : null}
      </div>

      <OptionSection
        title="Meta title options"
        hint="50–60 characters · keyword once"
        options={data.titleOptions}
        range={TITLE_RANGE}
        toast={toast}
      />

      <OptionSection
        title="Meta description options"
        hint="120–155 characters · keyword once"
        options={data.descriptionOptions}
        range={DESC_RANGE}
        toast={toast}
      />
    </div>
  );
}
