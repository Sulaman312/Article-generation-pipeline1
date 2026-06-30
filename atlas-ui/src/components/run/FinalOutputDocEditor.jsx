import { useEffect, useMemo, useRef, useState } from "react";
import Markdown from "../shared/Markdown";
import { splitFinalOutput } from "../../utils/parseFinalOutput";
import { computeTextStats, wordCountBounds } from "../../utils/textStats";
import PublishingMetadataStructured from "./PublishingMetadataStructured";
import FaqJsonLdPanel from "./FaqJsonLdPanel";
import {
  insertHorizontalRule,
  insertLink,
  setHeadingLevel,
  toggleLinePrefix,
  wrapSelection,
} from "../../utils/markdownEdit";
import "./FinalOutputDocEditor.css";

function ToolbarBtn({ title, onClick, children }) {
  return (
    <button
      type="button"
      className="fod-toolbar-btn"
      onMouseDown={(e) => e.preventDefault()}
      onClick={onClick}
      title={title}
      aria-label={title}
    >
      {children}
    </button>
  );
}

function ToolbarDivider() {
  return <span className="fod-toolbar-divider" aria-hidden />;
}

export default function FinalOutputDocEditor({
  value,
  onChange,
  readOnly = false,
  targetWordCount = null,
  onRequestEdit,
  toolbarExtra = null,
}) {
  const textareaRef = useRef(null);
  const [viewMode, setViewMode] = useState("preview");
  const [contentTab, setContentTab] = useState("article");
  const split = useMemo(() => splitFinalOutput(value), [value]);
  const isMetadataView =
    contentTab === "metadata" && split.hasStructuredMeta;
  const isJsonLdView = contentTab === "jsonld";
  const isAuxView = isMetadataView || isJsonLdView;
  const showContentTabs =
    split.hasStructuredMeta || split.hasArticle || Boolean(value?.trim());
  const stats = useMemo(
    () => computeTextStats(split.displayMarkdown || value),
    [split.displayMarkdown, value]
  );
  const wordTarget = Number(targetWordCount) > 0 ? Number(targetWordCount) : null;
  const [, wordHigh] = wordTarget ? wordCountBounds(wordTarget) : [0, 0];
  const wordOverCap = wordTarget && stats.words > wordHigh;

  useEffect(() => {
    if (readOnly) setViewMode("preview");
  }, [readOnly]);

  useEffect(() => {
    if (isAuxView) setViewMode("preview");
  }, [isAuxView]);

  const canChange = Boolean(onChange);
  const effectiveView = isAuxView ? "preview" : viewMode;
  const showEdit =
    canChange &&
    !readOnly &&
    !isAuxView &&
    (effectiveView === "edit" || effectiveView === "split");
  const showPreview =
    effectiveView === "preview" || effectiveView === "split" || readOnly;
  const showFormatRow =
    canChange && !readOnly && contentTab === "article" && !isAuxView;

  function enterEditMode(nextView = "split") {
    if (readOnly) onRequestEdit?.();
    else setViewMode(nextView);
  }

  function run(action) {
    const ta = textareaRef.current;
    if (!ta || readOnly) return;
    action(ta);
  }

  const contentTabs = showContentTabs ? (
    <div className="fod-content-tabs" role="tablist" aria-label="Final output content">
      <button
        type="button"
        role="tab"
        aria-selected={contentTab === "article"}
        className={`fod-content-tab${contentTab === "article" ? " active" : ""}`}
        onClick={() => setContentTab("article")}
      >
        Article
      </button>
      {split.hasStructuredMeta ? (
        <button
          type="button"
          role="tab"
          aria-selected={contentTab === "metadata"}
          className={`fod-content-tab${contentTab === "metadata" ? " active" : ""}`}
          onClick={() => setContentTab("metadata")}
        >
          Publishing info
        </button>
      ) : null}
      <button
        type="button"
        role="tab"
        aria-selected={contentTab === "jsonld"}
        className={`fod-content-tab${contentTab === "jsonld" ? " active" : ""}`}
        onClick={() => setContentTab("jsonld")}
      >
        JSON-LD
      </button>
    </div>
  ) : null;

  const viewTabs = !readOnly && !isAuxView ? (
    <div className="fod-view-tabs" role="tablist" aria-label="Editor view">
      <button
        type="button"
        role="tab"
        aria-selected={viewMode === "edit"}
        className={`fod-view-tab${viewMode === "edit" ? " active" : ""}`}
        onClick={() => enterEditMode("edit")}
      >
        Edit
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={viewMode === "split"}
        className={`fod-view-tab${viewMode === "split" ? " active" : ""}`}
        onClick={() => enterEditMode("split")}
      >
        Split
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={viewMode === "preview"}
        className={`fod-view-tab${viewMode === "preview" ? " active" : ""}`}
        onClick={() => setViewMode("preview")}
      >
        Preview
      </button>
    </div>
  ) : null;

  return (
    <div className="final-output-doc-root">
      <div className="fod-toolbar" role="toolbar" aria-label="Final output">
        <div className="fod-toolbar-primary">
          <div className="fod-stats-inline" aria-live="polite">
            <span className={wordOverCap ? "fod-stats-warn" : undefined}>
              <strong>{stats.words}</strong>w
              {wordTarget ? (
                <span className="fod-stats-target"> / {wordTarget}</span>
              ) : null}
            </span>
            <span aria-hidden>·</span>
            <span>
              <strong>{stats.chars}</strong>c
            </span>
            <span aria-hidden>·</span>
            <span>
              ~<strong>{stats.readingMinutes}</strong>m
            </span>
          </div>
          {contentTabs}
          <div className="fod-toolbar-primary-end">
            {viewTabs}
            {toolbarExtra}
          </div>
        </div>
        {showFormatRow ? (
          <div className="fod-toolbar-format" aria-label="Formatting">
            <div className="fod-toolbar-group">
              <ToolbarBtn
                title="Bold (Ctrl+B)"
                onClick={() =>
                  run((ta) =>
                    wrapSelection(ta, "**", "**", "bold text", onChange)
                  )
                }
              >
                <strong>B</strong>
              </ToolbarBtn>
              <ToolbarBtn
                title="Italic (Ctrl+I)"
                onClick={() =>
                  run((ta) =>
                    wrapSelection(ta, "*", "*", "italic text", onChange)
                  )
                }
              >
                <em>I</em>
              </ToolbarBtn>
            </div>
            <ToolbarDivider />
            <div className="fod-toolbar-group">
              <label className="fod-toolbar-select-wrap" title="Heading level">
                <span className="fod-sr-only">Heading level</span>
                <select
                  className="fod-toolbar-select"
                  defaultValue=""
                  onMouseDown={(e) => e.stopPropagation()}
                  onChange={(e) => {
                    const v = e.target.value;
                    run((ta) =>
                      setHeadingLevel(ta, v === "" ? 0 : Number(v), onChange)
                    );
                    e.target.value = "";
                  }}
                >
                  <option value="" disabled>
                    Style
                  </option>
                  <option value="0">Normal</option>
                  <option value="1">H1</option>
                  <option value="2">H2</option>
                  <option value="3">H3</option>
                </select>
              </label>
            </div>
            <ToolbarDivider />
            <div className="fod-toolbar-group">
              <ToolbarBtn
                title="Bullet list"
                onClick={() =>
                  run((ta) => toggleLinePrefix(ta, "- ", onChange))
                }
              >
                <span className="fod-toolbar-ico" aria-hidden>
                  •≡
                </span>
              </ToolbarBtn>
              <ToolbarBtn
                title="Link"
                onClick={() => run((ta) => insertLink(ta, onChange))}
              >
                <span className="fod-toolbar-ico fod-toolbar-ico--mono" aria-hidden>
                  Link
                </span>
              </ToolbarBtn>
              <ToolbarBtn
                title="Horizontal rule"
                onClick={() =>
                  run((ta) => insertHorizontalRule(ta, onChange))
                }
              >
                <span className="fod-toolbar-ico" aria-hidden>
                  ―
                </span>
              </ToolbarBtn>
            </div>
          </div>
        ) : null}
      </div>

      <div
        className={`fod-panes${
          effectiveView === "split" ? " fod-panes--split" : ""
        }${effectiveView === "preview" ? " fod-panes--preview-only" : ""}${
          effectiveView === "edit" ? " fod-panes--edit-only" : ""
        }${isAuxView ? " fod-panes--aux" : ""}`}
      >
        {showEdit ? (
          <div className="fod-pane fod-pane--edit">
            <textarea
              ref={textareaRef}
              className="final-output-doc-editor"
              value={value}
              onChange={(e) => onChange?.(e.target.value)}
              spellCheck
              aria-label="Final draft markdown source"
              onKeyDown={(e) => {
                if (readOnly) return;
                if (e.ctrlKey || e.metaKey) {
                  if (e.key === "b") {
                    e.preventDefault();
                    wrapSelection(
                      e.target,
                      "**",
                      "**",
                      "bold",
                      onChange
                    );
                  }
                  if (e.key === "i") {
                    e.preventDefault();
                    wrapSelection(e.target, "*", "*", "italic", onChange);
                  }
                }
              }}
            />
          </div>
        ) : null}

        {showPreview ? (
          <div className="fod-pane fod-pane--preview">
            {isMetadataView ? (
              <PublishingMetadataStructured fields={split.metadataFields} />
            ) : isJsonLdView ? (
              <FaqJsonLdPanel schemaScript={split.faqSchemaScript} />
            ) : (
              <article className="fod-preview-article">
                {split.displayMarkdown?.trim() ? (
                  <Markdown
                    text={split.displayMarkdown}
                    className="md md--article-site"
                  />
                ) : value?.trim() && !split.hasStructuredMeta ? (
                  <Markdown text={value} className="md md--article-site" />
                ) : (
                  <p className="fod-preview-empty">Nothing to preview yet.</p>
                )}
              </article>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
