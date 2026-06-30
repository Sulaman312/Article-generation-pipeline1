import { useState } from "react";
import { copyFormattedMarkdown } from "../../utils/markdownExport";
import Markdown from "./Markdown";
import { PIPELINE_MARKDOWN_CLASS } from "../../constants/markdownPreview";

/** Preview by default; Edit opens Markdown source in a textarea. */
export default function MarkdownArtifactPanel({
  content = "",
  baseline = null,
  draft,
  editing = false,
  onDraftChange,
  onEditingChange,
  readOnly = false,
  canEdit = true,
  /** Custom preview (e.g. topic card fields). Falls back to rendered Markdown. */
  previewNode = null,
  savedHint = null,
  footer = null,
  bodyClassName = "",
  textareaRows = 18,
  textareaPlaceholder = "",
  showCopy = false,
  /** When false, parent renders Edit/Cancel (e.g. workspace artifact card header). */
  showEditInToolbar = true,
  /** When set, copy this markdown instead of raw content (e.g. final article only). */
  copySource = null,
  onCopySuccess,
  onCopyError,
}) {
  const text = draft ?? content;
  const [copying, setCopying] = useState(false);

  function startEdit() {
    onEditingChange?.(true);
  }

  function cancelEdit() {
    onDraftChange?.(baseline ?? content);
    onEditingChange?.(false);
  }

  async function handleCopy() {
    const payload = copySource ?? (editing && !readOnly ? text : content);
    if (!String(payload || "").trim()) return;
    setCopying(true);
    try {
      const ok = await copyFormattedMarkdown(payload);
      if (ok) onCopySuccess?.();
      else onCopyError?.(new Error("Copy failed"));
    } catch (e) {
      onCopyError?.(e);
    } finally {
      setCopying(false);
    }
  }

  const showToolbar =
    savedHint ||
    showCopy ||
    (showEditInToolbar && canEdit && !readOnly);

  return (
    <>
      {showToolbar ? (
        <div className="run-artifact-toolbar">
          <div className="run-artifact-toolbar-left">{savedHint}</div>
          <div className="run-artifact-toolbar-actions">
            {showCopy && Boolean(content || text) ? (
              <button
                type="button"
                className="btn btn-sm btn-edit-artifact"
                onClick={handleCopy}
                disabled={copying}
                title="Copy formatted text (ready to paste in Word or CMS)"
              >
                {copying ? "Copying…" : "Copy"}
              </button>
            ) : null}
            {showEditInToolbar && canEdit && !readOnly ? (
              editing ? (
                <button
                  type="button"
                  className="btn btn-sm btn-edit-artifact"
                  onClick={cancelEdit}
                >
                  Cancel
                </button>
              ) : (
                <button
                  type="button"
                  className="btn btn-sm btn-edit-artifact"
                  onClick={startEdit}
                >
                  Edit
                </button>
              )
            ) : null}
          </div>
        </div>
      ) : null}

      <div className={`run-artifact-body${bodyClassName ? ` ${bodyClassName}` : ""}`}>
        {editing && !readOnly ? (
          <textarea
            className="run-artifact-textarea"
            value={text}
            onChange={(e) => onDraftChange?.(e.target.value)}
            placeholder={textareaPlaceholder}
            spellCheck={false}
            rows={textareaRows}
          />
        ) : (
          previewNode ?? (
            <Markdown text={content} className={PIPELINE_MARKDOWN_CLASS} />
          )
        )}
      </div>

      {footer}
    </>
  );
}
