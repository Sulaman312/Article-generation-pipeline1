import { useMemo } from "react";
import Markdown from "../shared/Markdown";
import {
  normalizeStepArtifactMarkdown,
  PIPELINE_MARKDOWN_CLASS,
} from "../../constants/markdownPreview";
import { computeTextStats } from "../../utils/textStats";
import "./SectionCards.css";

const DRAFT_START = "---DRAFT START---";
const DRAFT_END = "---DRAFT END---";

function extractDraftBody(text) {
  const raw = String(text || "");
  const s = raw.indexOf(DRAFT_START);
  const e = raw.indexOf(DRAFT_END);
  if (s !== -1 && e !== -1 && e > s) {
    return raw.slice(s + DRAFT_START.length, e).trim();
  }
  return raw.trim();
}

function extractHeadings(markdown) {
  const headings = [];
  const lines = String(markdown || "").split("\n");
  for (const line of lines) {
    const m = line.match(/^(#{1,3})\s+(.+)$/);
    if (m) {
      headings.push({
        level: m[1].length,
        title: m[2].trim(),
        id: `draft-h-${headings.length}`,
      });
    }
  }
  return headings.filter((h) => h.level <= 2).slice(0, 16);
}

export default function DraftStructured({ text }) {
  const body = useMemo(() => extractDraftBody(text), [text]);
  const headings = useMemo(() => extractHeadings(body), [body]);
  const stats = useMemo(() => computeTextStats(body), [body]);

  if (!body) return null;

  const display = normalizeStepArtifactMarkdown(
    `${DRAFT_START}\n${body}\n${DRAFT_END}`,
    "draft"
  );

  return (
    <div className="draft-structured">
      <div className="draft-chrome">
        <span className="draft-chrome-stat">
          {stats.words.toLocaleString()} words
        </span>
        {headings.length ? (
          <nav className="draft-toc" aria-label="Draft sections">
            {headings.map((h) => (
              <span key={h.id} className="draft-toc-link">
                {h.title}
              </span>
            ))}
          </nav>
        ) : null}
      </div>
      <Markdown
        text={display}
        className={PIPELINE_MARKDOWN_CLASS}
        stepKey="draft"
      />
    </div>
  );
}
