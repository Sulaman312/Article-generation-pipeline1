import { Fragment } from "react";
import { parseBlocks } from "../../utils/markdownBlocks";
import { normalizePipelineMarkdown } from "../../constants/markdownPreview";

const INLINE_TOKEN =
  /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(__[^_\n]+__)|(\*[^*\n]+\*)|(_[^_\n]+_)|(\[[^\]]+\]\([^)\s]+\))/g;

const PIPELINE_FIELD_KEY = /^[A-Z][A-Z0-9 _\-()]{2,}$/;
const PIPELINE_FIELD_LINE = /^([A-Z][A-Z0-9 _\-()]+):\s*(.*)$/s;
const OUTLINE_HEADING_LINE =
  /^H\s*([1-6])\s*:\s*(.+)$/i;
const OUTLINE_HEADING_STUB = /^H\s*([1-6])\s*:\s*$/i;

function renderInline(text, keyPrefix = "i") {
  if (!text) return null;
  const parts = [];
  let lastIdx = 0;
  let i = 0;
  let m;
  INLINE_TOKEN.lastIndex = 0;
  while ((m = INLINE_TOKEN.exec(text)) !== null) {
    if (m.index > lastIdx) {
      parts.push(text.slice(lastIdx, m.index));
    }
    const tok = m[0];
    const k = `${keyPrefix}-${i++}`;
    if (tok.startsWith("`")) {
      parts.push(<code key={k}>{tok.slice(1, -1)}</code>);
    } else if (tok.startsWith("**") || tok.startsWith("__")) {
      parts.push(<strong key={k}>{tok.slice(2, -2)}</strong>);
    } else if (tok.startsWith("*") || tok.startsWith("_")) {
      parts.push(<em key={k}>{tok.slice(1, -1)}</em>);
    } else if (tok.startsWith("[")) {
      const lm = tok.match(/^\[([^\]]+)\]\(([^)\s]+)\)$/);
      if (lm) {
        parts.push(
          <a
            key={k}
            href={lm[2]}
            target="_blank"
            rel="noopener noreferrer"
          >
            {lm[1]}
          </a>
        );
      } else {
        parts.push(tok);
      }
    }
    lastIdx = m.index + m[0].length;
  }
  if (lastIdx < text.length) parts.push(text.slice(lastIdx));
  return parts.map((p, idx) =>
    typeof p === "string" ? <Fragment key={`s-${idx}`}>{p}</Fragment> : p
  );
}

function isSystemMetaKey(key) {
  return /^(MODEL|VERSION|STATUS)$/i.test(String(key || "").trim());
}

function isPipelineFieldKey(key) {
  const k = String(key || "").trim().replace(/:$/, "");
  return PIPELINE_FIELD_KEY.test(k) && k.length >= 3;
}

function isMajorSectionTitle(text) {
  const t = String(text || "").trim().replace(/:$/, "");
  if (/^(MAIN RESPONSE|RESPONSE)$/i.test(t)) return true;
  if (/CITATION URLS/i.test(t)) return true;
  if (/RELATED QUESTIONS/i.test(t)) return true;
  // Short ALL-CAPS banners only (not long SERP category lines).
  if (
    t.length >= 4 &&
    t.length <= 36 &&
    t === t.toUpperCase() &&
    /[A-Z]/.test(t) &&
    /\s/.test(t)
  ) {
    return true;
  }
  return false;
}

function isSubsectionTitle(text) {
  const t = String(text || "").trim();
  return /^\d+\.\s/.test(t);
}

function renderSubsectionHeading(title, key) {
  return (
    <h4 key={key} className="md-section-heading md-section-heading--minor">
      {renderInline(title, key)}
    </h4>
  );
}

function renderOutlineHeading(line, key) {
  const cleaned = String(line || "").trim().replace(/^#+\s*/, "");
  let m = cleaned.match(OUTLINE_HEADING_LINE);
  if (!m) return null;
  const level = Math.min(6, Math.max(1, parseInt(m[1], 10)));
  const title = m[2].trim();
  if (!title) return null;
  const Tag = `h${level}`;
  const cls =
    level <= 2
      ? "md-section-heading md-section-heading--major"
      : "md-section-heading";
  return (
    <Tag key={key} className={cls}>
      {renderInline(title, key)}
    </Tag>
  );
}

function renderDelimiterHeading(text, key) {
  return (
    <h2 key={key} className="md-section-heading md-section-heading--major">
      {text}
    </h2>
  );
}

function renderBoldHeading(title, key) {
  const text = title.trim();
  const clean = text.replace(/:$/, "");
  if (isSubsectionTitle(clean)) {
    return renderSubsectionHeading(clean, key);
  }
  if (isMajorSectionTitle(clean)) {
    return renderDelimiterHeading(clean, key);
  }
  if (clean === clean.toUpperCase() && clean.length > 36) {
    return (
      <p key={key} className="md-category-label">
        <strong>{clean}</strong>
      </p>
    );
  }
  return (
    <h3 key={key} className="md-section-heading md-section-heading--minor">
      {clean}
    </h3>
  );
}

function renderPipelineField(label, bodyText, key) {
  const cleanLabel = label.trim().replace(/:$/, "");
  const body = bodyText.trim();
  return (
    <div key={key} className="md-labeled-block md-pipeline-field">
      <div className="md-field-heading">{cleanLabel}</div>
      {body ? (
        <div className="md-labeled-block-body">
          {body.split("\n").map((seg, j) => (
            <Fragment key={`${key}-b-${j}`}>
              {j > 0 ? <br /> : null}
              {renderInline(seg, `${key}-${j}`)}
            </Fragment>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function renderNestedBlocks(text, keySeed) {
  const blocks = parseBlocks(normalizePipelineMarkdown(text || ""));
  return blocks.map((b, i) => renderBlock(b, keySeed + i));
}

function isSplittablePipelineLine(line) {
  const t = String(line || "").trim();
  if (!t) return false;
  if (/^---.+---$/.test(t)) return true;
  if (/^MODEL:/i.test(t)) return true;
  if (OUTLINE_HEADING_LINE.test(t)) return true;
  if (OUTLINE_HEADING_STUB.test(t)) return true;
  if (/^[A-Z][A-Z0-9 _\-()]+:\s*/.test(t)) return true;
  if (/^\*\*[^*]+\*\*\s*$/.test(t)) return true;
  if (isMajorSectionTitle(t)) return true;
  return false;
}

function renderListItem(text, keyPrefix) {
  const task = String(text || "").match(/^\[([\sxX])\]\s+(.*)$/s);
  if (task) {
    const checked = task[1].toLowerCase() === "x";
    return (
      <li
        className={`md-task${checked ? " md-task--done" : ""}`}
        key={keyPrefix}
      >
        <span className="md-task-mark" aria-hidden>
          {checked ? "☑" : "☐"}
        </span>
        {renderInline(task[2].trim(), keyPrefix)}
      </li>
    );
  }
  const labeled = String(text || "").match(/^\*\*([^*]+)\*\*\s*:?\s*(.*)$/s);
  if (labeled) {
    const body = labeled[2].trim();
    return (
      <li key={keyPrefix} className="md-labeled-list-item">
        <span className="md-labeled-list-item-label">{labeled[1].trim()}</span>
        {body ? (
          <span className="md-labeled-list-item-body">
            {renderInline(body, keyPrefix)}
          </span>
        ) : null}
      </li>
    );
  }
  const plainField = String(text || "").match(PIPELINE_FIELD_LINE);
  if (plainField && !String(text).includes("**")) {
    const body = plainField[2].trim();
    return (
      <li key={keyPrefix} className="md-labeled-list-item">
        <span className="md-labeled-list-item-label">{plainField[1].trim()}</span>
        {body ? (
          <span className="md-labeled-list-item-body">
            {renderInline(body, keyPrefix)}
          </span>
        ) : null}
      </li>
    );
  }
  return <li key={keyPrefix}>{renderInline(text, keyPrefix)}</li>;
}

function renderParagraphBlock(block, key) {
  const rawLines = block.text.split("\n");
  const lines = rawLines.map((l) => l.trim()).filter(Boolean);

  if (lines.length > 1 && lines.every(isSplittablePipelineLine)) {
    return (
      <div key={key} className="md-compound-lines">
        {lines.map((line, i) =>
          renderParagraphBlock({ type: "p", text: line }, `${key}-l${i}`)
        )}
      </div>
    );
  }

  const trimmed = block.text.trim();
  const firstLine = lines[0] || "";

  if (OUTLINE_HEADING_STUB.test(firstLine) && lines.length > 1) {
    const title = lines.slice(1).join(" ").trim();
    const outline = renderOutlineHeading(`${firstLine} ${title}`, key);
    if (outline) return outline;
  }

  const outlineFromFirst = renderOutlineHeading(firstLine, key);
  if (outlineFromFirst) {
    if (lines.length === 1) return outlineFromFirst;
    return (
      <div key={key} className="md-outline-section">
        {outlineFromFirst}
        {renderNestedBlocks(rawLines.slice(1).join("\n"), 900000)}
      </div>
    );
  }

  const banner = trimmed.match(/^---(.+?)---$/);
  if (banner) {
    return renderDelimiterHeading(banner[1].trim(), key);
  }

  if (isMajorSectionTitle(trimmed) && !trimmed.includes(":")) {
    return renderBoldHeading(trimmed, key);
  }

  const boldOnly = trimmed.match(/^\*\*([^*]+)\*\*\s*$/);
  if (boldOnly) {
    const inner = boldOnly[1].trim();
    const outlineFromBold = renderOutlineHeading(inner, key);
    if (outlineFromBold) return outlineFromBold;
    if (inner.includes(":") && inner.length > 48 && !isMajorSectionTitle(inner)) {
      return (
        <p key={key} className="md-body-paragraph md-lead-line">
          <strong>{renderInline(inner, key)}</strong>
        </p>
      );
    }
    return renderBoldHeading(inner, key);
  }

  const numberedSection = trimmed.match(/^(\d+\.\s+.+)$/);
  if (numberedSection && !trimmed.includes("**")) {
    return renderSubsectionHeading(numberedSection[1], key);
  }

  const fieldMatch = firstLine.match(PIPELINE_FIELD_LINE);
  if (fieldMatch && !block.text.includes("**")) {
    const label = fieldMatch[1];
    const restFirst = fieldMatch[2];
    if (!isSystemMetaKey(label) && isPipelineFieldKey(label)) {
      const bodyText = [restFirst, ...rawLines.slice(1)].join("\n").trim();
      return renderPipelineField(label, bodyText, key);
    }
  }

  const metaLine = trimmed.match(/^([A-Z][A-Z0-9_ \-]+):\s*(.+)$/);
  if (metaLine && !trimmed.includes("**") && !/^H[1-6]$/i.test(metaLine[1].trim())) {
    return (
      <div key={key} className="md-meta-line">
        <span className="md-meta-line-key">{metaLine[1]}</span>
        <span className="md-meta-line-value">{metaLine[2].trim()}</span>
      </div>
    );
  }

  const inlineLabel = trimmed.match(/^\*\*([^*]+)\*\*\s*:?\s*(.+)$/s);
  if (inlineLabel?.[2]?.trim()) {
    const label = inlineLabel[1].trim();
    const body = inlineLabel[2].trim();
    const outlineFromLabel = renderOutlineHeading(`${label}: ${body}`, key);
    if (outlineFromLabel) return outlineFromLabel;
    if (isPipelineFieldKey(label)) {
      return renderPipelineField(label, body, key);
    }
    return (
      <div key={key} className="md-labeled-block">
        <div className="md-labeled-block-label">{label}</div>
        <p className="md-labeled-block-body">{renderInline(body, key)}</p>
      </div>
    );
  }

  if (OUTLINE_HEADING_LINE.test(trimmed)) {
    const outline = renderOutlineHeading(trimmed, key);
    if (outline) return outline;
  }

  return (
    <p key={key} className="md-body-paragraph">
      {block.text.split("\n").map((seg, j, arr) => (
        <Fragment key={`l-${j}`}>
          {renderInline(seg, `${key}-${j}`)}
          {j < arr.length - 1 ? <br /> : null}
        </Fragment>
      ))}
    </p>
  );
}

function renderBlock(block, idx) {
  const k = `b-${idx}`;
  switch (block.type) {
    case "heading": {
      const outline = renderOutlineHeading(block.text, k);
      if (outline) return outline;
      const level = Math.min(6, Math.max(1, block.level));
      const Tag = `h${level}`;
      let cls = "";
      if (level <= 2) cls = "md-section-heading md-section-heading--major";
      else if (level === 3) cls = "md-section-heading";
      return (
        <Tag key={k} className={cls || undefined}>
          {renderInline(block.text, k)}
        </Tag>
      );
    }
    case "p":
      return renderParagraphBlock(block, k);
    case "ul":
      return (
        <ul key={k} className="md-list">
          {block.items.map((it, j) => renderListItem(it, `u-${k}-${j}`))}
        </ul>
      );
    case "ol":
      return (
        <ol key={k} className="md-list">
          {block.items.map((it, j) => renderListItem(it, `o-${k}-${j}`))}
        </ol>
      );
    case "code":
      return (
        <pre key={k}>
          <code>{block.text}</code>
        </pre>
      );
    case "quote":
      return <blockquote key={k}>{renderInline(block.text, k)}</blockquote>;
    case "hr":
      return <hr key={k} />;
    case "table":
      return (
        <table key={k}>
          <thead>
            <tr>
              {block.header.map((h, j) => (
                <th key={`th-${j}`}>{renderInline(h, `${k}-h-${j}`)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {block.rows.map((row, ri) => (
              <tr key={`tr-${ri}`}>
                {row.map((cell, ci) => (
                  <td key={`td-${ri}-${ci}`}>
                    {renderInline(cell, `${k}-${ri}-${ci}`)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      );
    default:
      return null;
  }
}

export default function Markdown({ text, className = "md" }) {
  const blocks = parseBlocks(normalizePipelineMarkdown(text || ""));
  if (blocks.length === 0) {
    return <div className="empty-state">empty artifact</div>;
  }
  return (
    <div className={className}>{blocks.map((b, i) => renderBlock(b, i))}</div>
  );
}
