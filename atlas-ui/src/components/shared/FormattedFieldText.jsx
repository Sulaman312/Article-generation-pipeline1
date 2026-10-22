import Markdown from "./Markdown";
import { PIPELINE_MARKDOWN_CLASS } from "../../constants/markdownPreview";

/** Renders artifact field copy with full markdown formatting (lists, bold, links). */
export default function FormattedFieldText({ text, className = "" }) {
  const raw = String(text ?? "").trim();
  if (!raw) {
    return <span className="muted">—</span>;
  }
  const cls = ["formatted-field-text", PIPELINE_MARKDOWN_CLASS, className]
    .filter(Boolean)
    .join(" ");
  return <Markdown text={text} className={cls} />;
}
