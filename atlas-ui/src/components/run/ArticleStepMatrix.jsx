import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { PIPELINE_STEPS as STEPS } from "../../constants/pipeline";
import {
  formatRunDate,
  formatRunDateTime,
  parseRunDate,
} from "../../utils/formatRelativeAge";
import MatrixRunActions from "./MatrixRunActions";
import "./ArticleStepMatrix.css";

const STEP_KEYS = STEPS.map((s) => s.key);

function MatrixDoneGlyph() {
  return (
    <span className="matrix-tick" aria-hidden>
      ✓
    </span>
  );
}

function MatrixCell({ status }) {
  const s = status || "pending";
  if (s === "done") {
    return (
      <td className="matrix-cell matrix-cell--done" title="Done">
        <MatrixDoneGlyph />
      </td>
    );
  }
  if (s === "running") {
    return (
      <td className="matrix-cell matrix-cell--run" title="Running">
        <span className="spinner matrix-spinner" aria-label="Running" />
      </td>
    );
  }
  if (s === "error") {
    return (
      <td className="matrix-cell matrix-cell--err" title="Error">
        <span className="matrix-err" aria-label="Error">
          !
        </span>
      </td>
    );
  }
  return (
    <td className="matrix-cell matrix-cell--pending" title="Pending">
      <span className="matrix-dash" aria-hidden>
        —
      </span>
    </td>
  );
}

const MATRIX_MENU_WIDTH = 260;

function MatrixInputCard({
  run,
  selected,
  selectionMode = false,
  selectGroupName,
  showRestore,
  onSelect,
  onOpen,
  onArchiveRun,
  onDeleteRun,
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [menuPos, setMenuPos] = useState({ top: 0, left: 0 });
  const menuRef = useRef(null);
  const menuBtnRef = useRef(null);
  const created = parseRunDate(run.timestamp, run.run_id);
  const createdLabel = formatRunDate(created);
  const createdTitle = formatRunDateTime(created);
  const title = run.topic?.trim() ? run.topic : "(untitled)";

  const syncMenuPosition = useCallback(() => {
    const btn = menuBtnRef.current;
    if (!btn) return;
    const rect = btn.getBoundingClientRect();
    setMenuPos({
      top: rect.bottom + 6,
      left: Math.max(8, Math.min(rect.right - MATRIX_MENU_WIDTH, window.innerWidth - MATRIX_MENU_WIDTH - 8)),
    });
  }, []);

  useEffect(() => {
    if (!menuOpen) return undefined;
    syncMenuPosition();
    function onDoc(e) {
      const target = e.target;
      if (
        menuRef.current?.contains(target) ||
        menuBtnRef.current?.contains(target)
      ) {
        return;
      }
      setMenuOpen(false);
    }
    function onReflow() {
      syncMenuPosition();
    }
    const timer = window.setTimeout(() => {
      document.addEventListener("click", onDoc);
    }, 0);
    window.addEventListener("resize", onReflow);
    window.addEventListener("scroll", onReflow, true);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("click", onDoc);
      window.removeEventListener("resize", onReflow);
      window.removeEventListener("scroll", onReflow, true);
    };
  }, [menuOpen, syncMenuPosition]);

  const showRadio = selectionMode;

  return (
    <div
      className={`matrix-input-card${
        showRadio && selected ? " matrix-input-card--selected" : ""
      }${showRadio ? " matrix-input-card--edit-mode" : ""}`}
    >
      {showRadio ? (
        <label
          className="matrix-input-select"
          onClick={(e) => e.stopPropagation()}
          onMouseDown={(e) => e.stopPropagation()}
        >
          <input
            type="radio"
            name={selectGroupName}
            checked={selected}
            aria-label={`Select ${title}`}
            onChange={() => onSelect?.(run.run_id)}
          />
        </label>
      ) : null}
      <button
        type="button"
        className="matrix-input-card-main"
        onClick={() => onOpen?.(run.run_id)}
      >
        <span className="matrix-input-title">{title}</span>
        {createdLabel ? (
          <span className="matrix-input-meta">
            <span className="matrix-input-meta-item" title={createdTitle || "Created"}>
              <IconClock />
              {createdLabel}
            </span>
          </span>
        ) : null}
      </button>
      <div
        className={`matrix-input-menu-wrap${menuOpen ? " matrix-input-menu-wrap--open" : ""}`}
        onMouseDown={(e) => e.stopPropagation()}
        onClick={(e) => e.stopPropagation()}
      >
        <button
          ref={menuBtnRef}
          type="button"
          className={`matrix-input-menu-btn${menuOpen ? " matrix-input-menu-btn--open" : ""}`}
          aria-label="Article actions"
          aria-expanded={menuOpen}
          aria-haspopup="menu"
          onClick={() => {
            if (selectionMode) onSelect?.(run.run_id);
            setMenuOpen((v) => !v);
          }}
        >
          ⋮
        </button>
      </div>
      {menuOpen
        ? createPortal(
            <div
              ref={menuRef}
              className="matrix-input-menu matrix-input-menu--portal"
              style={{ top: menuPos.top, left: menuPos.left }}
              onMouseDown={(e) => e.stopPropagation()}
              onClick={(e) => e.stopPropagation()}
            >
              <button
                type="button"
                className="matrix-input-menu-open"
                onClick={() => {
                  setMenuOpen(false);
                  onOpen?.(run.run_id);
                }}
              >
                Open pipeline
              </button>
              <MatrixRunActions
                articleTopic={title}
                showRestore={showRestore}
                onArchive={async () => {
                  setMenuOpen(false);
                  await onArchiveRun?.(run.run_id);
                }}
                onDelete={async () => {
                  setMenuOpen(false);
                  await onDeleteRun?.(run.run_id);
                }}
              />
            </div>,
            document.body
          )
        : null}
    </div>
  );
}

function IconClock() {
  return (
    <svg
      className="matrix-input-clock"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      aria-hidden
    >
      <circle cx="8" cy="8" r="6.25" />
      <path d="M8 4.5V8l2.5 1.5" strokeLinecap="round" />
    </svg>
  );
}

export default function ArticleStepMatrix({
  runs = [],
  loading = false,
  selectedRunId = null,
  selectionMode = false,
  onSelectRun,
  onOpenRun,
  onArchiveRun,
  onDeleteRun,
  showRestore = false,
  emptyMessage = "No articles yet. Create a run from the Article board.",
}) {
  return (
    <div
      className={`matrix-scroll${selectionMode ? " matrix-scroll--edit-mode" : ""}`}
    >
      <table className="article-matrix">
        <thead>
          <tr>
            <th className="matrix-th matrix-th--input">Input</th>
            {STEPS.map((s) => (
              <th
                key={s.key}
                className="matrix-th matrix-th--step"
                title={s.label}
              >
                {s.matrixLabel || s.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {runs.length === 0 && !loading ? (
            <tr>
              <td colSpan={STEPS.length + 1} className="matrix-empty">
                {emptyMessage}
              </td>
            </tr>
          ) : null}
          {runs.map((r) => {
            const selected = selectionMode && selectedRunId === r.run_id;
            return (
              <tr
                key={r.run_id}
                className={`matrix-row${selected ? " matrix-row--selected" : ""}`}
                onClick={(e) => {
                  if (
                    e.target.closest(
                      "button, .matrix-input-menu, .matrix-input-menu-wrap, .matrix-input-card-main, .matrix-input-select, input[type=radio]"
                    )
                  ) {
                    return;
                  }
                  onSelectRun?.(r.run_id);
                  onOpenRun?.(r.run_id);
                }}
                onKeyDown={(e) => {
                  if (!onOpenRun) return;
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelectRun?.(r.run_id);
                    onOpenRun(r.run_id);
                  }
                }}
                tabIndex={onOpenRun ? 0 : undefined}
                role={onOpenRun ? "button" : undefined}
                title={onOpenRun ? "Open step-by-step flow" : undefined}
              >
                <td
                  className="matrix-td matrix-td--input"
                  onClick={(e) => {
                    e.stopPropagation();
                    onSelectRun?.(r.run_id);
                  }}
                >
                  <MatrixInputCard
                    run={r}
                    selected={selectedRunId === r.run_id}
                    selectionMode={selectionMode}
                    selectGroupName="matrix-article-select"
                    showRestore={showRestore}
                    onSelect={onSelectRun}
                    onOpen={onOpenRun}
                    onArchiveRun={onArchiveRun}
                    onDeleteRun={onDeleteRun}
                  />
                </td>
                {STEPS.map((s) => (
                  <MatrixCell
                    key={s.key}
                    status={(r.statuses || {})[s.key]}
                  />
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
