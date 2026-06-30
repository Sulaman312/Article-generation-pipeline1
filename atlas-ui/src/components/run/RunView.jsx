import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as api from "../../services/api";
import { useToast } from "../../context/ToastContext";
import { stepsForPipeline } from "../../constants/pipelines";
import { inputSourceForStep } from "../../utils/pipelineFlow";
import { parseTopicCard } from "../../utils/parseTopicCard";
import { executeRunStep } from "../../utils/runStepAction";
import Markdown from "../shared/Markdown";
import MarkdownArtifactPanel from "../shared/MarkdownArtifactPanel";
import ArtifactFormattedPreview from "./ArtifactFormattedPreview";
import TopicCardStructured from "./TopicCardStructured";
import FinalOutputDocEditor from "./FinalOutputDocEditor";
import { copyFormattedMarkdown } from "../../utils/markdownExport";
import { PIPELINE_MARKDOWN_CLASS } from "../../constants/markdownPreview";
import { splitFinalOutput } from "../../utils/parseFinalOutput";

const AUTOSAVE_MS = 1000;

function statusClass(s) {
  if (s === "done" || s === "running" || s === "error" || s === "skipped")
    return s;
  return "";
}

function statusLabel(s) {
  if (s === "done") return "Done";
  if (s === "running") return "Running";
  if (s === "error") return "Error";
  if (s === "skipped") return "Skipped";
  return "Pending";
}

export default function RunView({
  client,
  runId,
  activeStepKey,
  statusOverrides = {},
  onSelectStep,
  onBack,
}) {
  const { toast } = useToast();
  const [run, setRun] = useState(null);
  const [tab, setTab] = useState("output");
  const [error, setError] = useState(null);
  const [outputEditKey, setOutputEditKey] = useState(0);

  const refreshRun = useCallback(async () => {
    try {
      const r = await api.getRun(client, runId);
      setRun(r);
      setError(null);
    } catch (e) {
      setError(e?.message || String(e));
    }
  }, [client, runId]);

  useEffect(() => {
    refreshRun();
    const id = setInterval(refreshRun, 2000);
    return () => clearInterval(id);
  }, [refreshRun]);

  useEffect(() => {
    function onStepComplete(e) {
      const d = e.detail;
      if (d?.clientId !== client || d?.runId !== runId) return;
      refreshRun();
      setTab("output");
    }
    window.addEventListener("cf:run-step-complete", onStepComplete);
    return () => window.removeEventListener("cf:run-step-complete", onStepComplete);
  }, [client, runId, refreshRun]);

  useEffect(() => {
    setOutputEditKey(0);
  }, [activeStepKey]);

  useEffect(() => {
    refreshRun();
  }, [activeStepKey, refreshRun]);

  const serverStatuses = run?.statuses || {};
  const statuses = { ...serverStatuses, ...statusOverrides };
  const topic = run?.topic || "";
  const pipelineId = run?.pipeline_id || "article";
  const manualInputs = run?.manual_inputs;
  const isSocial = false;
  const runChromeLabel = topic?.trim() || "";
  const STEPS = useMemo(() => stepsForPipeline(pipelineId), [pipelineId]);

  const activeStep = useMemo(
    () => STEPS.find((s) => s.key === activeStepKey) || STEPS[0],
    [activeStepKey, STEPS]
  );
  const previousStep = useMemo(() => {
    const idx = STEPS.findIndex((s) => s.key === activeStepKey);
    return idx > 0 ? STEPS[idx - 1] : null;
  }, [activeStepKey, STEPS]);

  const status =
    statusOverrides[activeStep.key] ??
    serverStatuses[activeStep.key] ??
    "pending";
  const isFirstStep = activeStep.index === 1;

  const running = status === "running";
  const [stepError, setStepError] = useState(null);
  const [inlineRunning, setInlineRunning] = useState(false);

  const prevStatusRef = useRef(null);
  useEffect(() => {
    const prev = prevStatusRef.current;
    if (prev === "running" && status === "done") {
      setTab("output");
    }
    prevStatusRef.current = status;
  }, [status]);

  const inputTabTitle = previousStep
    ? `Input: ${previousStep.label}`
    : "Input: topic";
  const outputTabTitle = `Output: ${activeStep.label}`;

  return (
    <div className="run-shell">
      <header className="run-chrome-header run-chrome-header--minimal">
        <div className="run-chrome-minimal-row">
          <div className="run-chrome-step-meta">
            <h1 className="run-page-title run-page-title--inline">
              {activeStep.label}
            </h1>
            <span className={`status-pill status-pill--sm ${statusClass(status)}`}>
              <span className={`status-pip ${statusClass(status)}`} />
              {statusLabel(status)}
            </span>
            <span className="run-chrome-step-tag">
              {activeStep.index}/{STEPS.length}
            </span>
          </div>
          <div
            className="tab-bar tab-bar--compact run-chrome-tabs"
            role="tablist"
          >
            <button
              type="button"
              role="tab"
              aria-selected={tab === "input"}
              className={`tab tab--compact ${tab === "input" ? "active" : ""}`}
              onClick={() => setTab("input")}
              title={inputTabTitle}
            >
              Input
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "output"}
              className={`tab tab--compact ${tab === "output" ? "active" : ""}`}
              onClick={() => setTab("output")}
              title={outputTabTitle}
            >
              Output
            </button>
          </div>
        </div>
        {runChromeLabel ? (
          <p
            className="run-chrome-topic run-chrome-topic--minimal"
            title={runChromeLabel}
          >
            {runChromeLabel}
          </p>
        ) : null}
      </header>

      {stepError || error ? (
        <div className="run-alert" role="alert">
          {stepError || error}
        </div>
      ) : null}

      <div className="run-content-wrap run-content-wrap--compact">
        {tab === "input" ? (
          <InputPanel
            client={client}
            runId={runId}
            isFirstStep={isFirstStep}
            topic={topic}
            isSocial={isSocial}
            manualInputs={manualInputs}
            onRefreshRun={refreshRun}
            previousStep={previousStep}
            previousStatus={previousStep ? statuses[previousStep.key] : "done"}
            activeStepKey={activeStep.key}
            statuses={statuses}
            toast={toast}
            pipelineId={pipelineId}
          />
        ) : (
          <OutputPanel
            client={client}
            runId={runId}
            step={activeStep}
            manualInputs={run?.manual_inputs}
            targetWordCount={run?.target_word_count}
            status={status}
            running={running}
            toast={toast}
            headerEditKey={outputEditKey}
            pipelineId={pipelineId}
            topic={topic}
            statuses={statuses}
            inlineRunning={inlineRunning}
            onInlineRunningChange={setInlineRunning}
            onStepError={setStepError}
            onRunComplete={refreshRun}
            onShowOutput={() => setTab("output")}
            onGoToNextStep={() => {
              const i = STEPS.findIndex((s) => s.key === activeStepKey);
              const next = STEPS[i + 1];
              if (next) onSelectStep(next.key);
            }}
          />
        )}
      </div>
    </div>
  );
}

function copyMarkdownForStep(markdown, stepName) {
  if (stepName === "final_output") {
    const split = splitFinalOutput(markdown);
    return split.displayMarkdown || markdown;
  }
  return markdown;
}

function CopyOutputButton({ text, stepName, toast }) {
  const [copying, setCopying] = useState(false);
  async function handleCopy() {
    const source = copyMarkdownForStep(text, stepName);
    if (!String(source || "").trim()) return;
    setCopying(true);
    try {
      const ok = await copyFormattedMarkdown(source);
      if (ok) {
        toast?.("Copied formatted article — paste into Word or your CMS", {
          variant: "success",
          duration: 3500,
        });
      } else {
        toast?.("Could not copy", { variant: "error", duration: 4000 });
      }
    } finally {
      setCopying(false);
    }
  }
  return (
    <button
      type="button"
      className="btn btn-sm btn-edit-artifact"
      onClick={handleCopy}
      disabled={copying}
      title="Copy formatted article (not markdown source)"
    >
      {copying ? "Copying…" : "Copy"}
    </button>
  );
}

function InputPanel({
  client,
  runId,
  isFirstStep,
  topic,
  isSocial,
  manualInputs,
  onRefreshRun,
  previousStep,
  previousStatus,
  activeStepKey,
  statuses,
  toast,
  pipelineId,
}) {
  const src = inputSourceForStep(activeStepKey, statuses, pipelineId);

  if (isFirstStep || src.kind === "topic") {
    /* article-only service */
  }

  if (isFirstStep) {
    return (
      <div className="run-artifact-shell">
        <div className="run-artifact-card">
          <div className="run-artifact-body run-input-topic-body">
            <div className="run-input-topic-eyebrow">Topic · this run</div>
            {topic?.trim() ? (
              <Markdown text={topic} className={`${PIPELINE_MARKDOWN_CLASS} md--topic-input`} />
            ) : (
              <p className="run-input-topic-lead muted">(no topic)</p>
            )}
          </div>
        </div>
      </div>
    );
  }
  if (src.kind === "blocked") {
    return (
      <div className="run-artifact-shell">
        <div className="run-artifact-card">
          <div className="run-artifact-body">
            <div className="empty-state empty-state-inline">
              Complete earlier steps first — then this step can use their output
              as input.
            </div>
          </div>
        </div>
      </div>
    );
  }
  if (src.kind === "topic") {
    return (
      <div className="run-artifact-shell">
        <div className="run-artifact-card">
          <div className="run-artifact-body run-input-topic-body">
            <div className="run-input-topic-eyebrow">Topic · this run</div>
            {topic?.trim() ? (
              <Markdown text={topic} className={`${PIPELINE_MARKDOWN_CLASS} md--topic-input`} />
            ) : (
              <p className="run-input-topic-lead muted">(no topic)</p>
            )}
          </div>
        </div>
      </div>
    );
  }
  const inputStep = stepsForPipeline(pipelineId).find((s) => s.key === src.stepKey);
  return (
    <ArtifactView
      client={client}
      runId={runId}
      stepName={inputStep?.key || previousStep.key}
      readOnly
      toast={toast}
      allowStructuredTopicCard
      manualInputs={manualInputs}
    />
  );
}

function OutputPanel({
  client,
  runId,
  step,
  manualInputs,
  targetWordCount,
  status,
  running,
  toast,
  headerEditKey,
  pipelineId,
  topic,
  statuses,
  inlineRunning,
  onInlineRunningChange,
  onStepError,
  onRunComplete,
  onShowOutput,
  onGoToNextStep,
}) {
  const showInlineRun = false;

  async function handleInlineRun() {
    if (!showInlineRun) return;
    if (inlineRunning) return;
    onStepError?.(null);
    onInlineRunningChange?.(true);
    try {
      await executeRunStep(
        api,
        client,
        runId,
        step.key,
        topic,
        statuses,
        null,
        pipelineId
      );
      await onRunComplete?.();
      onShowOutput?.();
      toast?.(`Ran ${step.label}.`, { variant: "success", duration: 3500 });
    } catch (e) {
      const msg = e?.message || String(e);
      onStepError?.(msg);
      toast?.(msg, { variant: "error", duration: 12000 });
    } finally {
      onInlineRunningChange?.(false);
    }
  }

  if (inlineRunning || running || status === "running") {
    return (
      <div className="run-artifact-shell">
        <div className="run-artifact-card">
          <div className="run-artifact-body">
            <div className="empty-state empty-state-inline">
              <span className="spinner" /> Generating{" "}
              {step.label.toLowerCase()}…
            </div>
          </div>
        </div>
      </div>
    );
  }
  if (status !== "done") {
    return (
      <div className="run-artifact-shell">
        <div className="run-artifact-card">
          <div className="run-artifact-body">
            <div className="empty-state empty-state-inline">
              No output yet. Use{" "}
              <strong style={{ color: "var(--text)" }}>Run</strong> or{" "}
              <strong style={{ color: "var(--text)" }}>Re-run</strong> beside this
              step in the sidebar.
              {showInlineRun ? (
                <div style={{ marginTop: 12 }}>
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={handleInlineRun}
                  >
                    ▶ Run this step
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    );
  }
  return (
    <ArtifactView
      client={client}
      runId={runId}
      stepName={step.key}
      manualInputs={manualInputs}
      targetWordCount={targetWordCount}
      toast={toast}
      headerEditKey={headerEditKey}
      useHeaderEdit
      onSaveAndContinue={onGoToNextStep}
    />
  );
}

function ArtifactView({
  client,
  runId,
  stepName,
  readOnly,
  toast,
  manualInputs = null,
  targetWordCount = null,
  headerEditKey = 0,
  useHeaderEdit = false,
  allowStructuredTopicCard = false,
  onSaveAndContinue,
}) {
  const [content, setContent] = useState("");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [savedAt, setSavedAt] = useState(0);
  const lastKey = useRef("");
  const autosaveTimer = useRef(null);
  const lastHeaderEditKey = useRef(-1);
  const isFinalDoc = stepName === "final_output";
  const showCopyOutput = ["draft", "fact_check", "final_output", "captions"].includes(
    stepName
  );

  function clearAutosaveTimer() {
    if (autosaveTimer.current !== null) {
      window.clearTimeout(autosaveTimer.current);
      autosaveTimer.current = null;
    }
  }

  useEffect(() => {
    lastHeaderEditKey.current = -1;
    if (stepName === "final_output" && !readOnly) setEditing(true);
    else setEditing(false);
  }, [stepName, readOnly]);

  useEffect(() => {
    if (readOnly || !useHeaderEdit) return;
    if (headerEditKey <= 0 || headerEditKey === lastHeaderEditKey.current)
      return;
    lastHeaderEditKey.current = headerEditKey;
    setEditing(true);
  }, [headerEditKey, readOnly, useHeaderEdit]);

  useEffect(() => {
    const key = `${client}|${runId}|${stepName}`;
    lastKey.current = key;
    let cancelled = false;
    setLoading(true);
    api
      .getArtifact(client, runId, stepName)
      .then((c) => {
        if (cancelled || lastKey.current !== key) return;
        setContent(c);
        setDraft(c);
        setLoading(false);
      })
      .catch(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      clearAutosaveTimer();
    };
  }, [client, runId, stepName]);

  useEffect(() => {
    if (!editing || readOnly || loading) return;
    if (!content) return;
    if (draft === content) return;
    clearAutosaveTimer();
    autosaveTimer.current = window.setTimeout(async () => {
      autosaveTimer.current = null;
      try {
        await api.saveArtifact(client, runId, stepName, draft);
        setContent(draft);
        setSavedAt(Date.now());
      } catch (e) {
        const msg = e?.message || String(e);
        toast?.(msg, { variant: "error", duration: 11000 });
      }
    }, AUTOSAVE_MS);
    return clearAutosaveTimer;
  }, [draft, editing, readOnly, loading, content, client, runId, stepName, toast]);

  async function handleSave() {
    clearAutosaveTimer();
    try {
      await api.saveArtifact(client, runId, stepName, draft);
      setContent(draft);
      if (stepName !== "final_output") setEditing(false);
      setSavedAt(Date.now());
      toast?.("Saved", { variant: "success", duration: 3000 });
    } catch (e) {
      const msg = e?.message || String(e);
      toast?.(msg, { variant: "error", duration: 11000 });
    }
  }

  async function handleSaveAndContinue() {
    clearAutosaveTimer();
    try {
      await api.saveArtifact(client, runId, stepName, draft);
      setContent(draft);
      setEditing(false);
      setSavedAt(Date.now());
      onSaveAndContinue?.();
    } catch (e) {
      const msg = e?.message || String(e);
      toast?.(msg, { variant: "error", duration: 11000 });
    }
  }

  const showEditorDock =
    !readOnly && editing && typeof onSaveAndContinue === "function";

  const topicCardPreview =
    stepName === "topic_card" &&
    Boolean(parseTopicCard(content)) &&
    (!readOnly || allowStructuredTopicCard) ? (
      <TopicCardStructured text={content} manualInputs={manualInputs} />
    ) : null;

  const structuredOnly = topicCardPreview || null;

  const formattedPreview = structuredOnly ? (
    <ArtifactFormattedPreview
      structured={structuredOnly}
      content={content}
      showFullSource={false}
    />
  ) : null;

  const artifactShellClass = "run-artifact-shell";

  if (loading) {
    return (
      <div className="run-artifact-shell">
        <div className="empty-state">
          <span className="spinner" /> loading…
        </div>
      </div>
    );
  }
  if (!content) {
    return (
      <div className="run-artifact-shell">
        <div className="run-artifact-card">
          <div className="run-artifact-body">
            <div className="empty-state">empty artifact</div>
          </div>
        </div>
      </div>
    );
  }

  const savedHint =
    !readOnly && savedAt && Date.now() - savedAt < 2500 ? (
      <span className="run-save-hint">Saved</span>
    ) : null;

  const editorDock = showEditorDock ? (
    <div className="run-editor-dock">
      <button
        type="button"
        className="btn btn-dock-secondary"
        onClick={handleSave}
      >
        Save
      </button>
      <button
        type="button"
        className="btn btn-primary btn-dock-primary"
        onClick={handleSaveAndContinue}
      >
        Save &amp; continue
        <span className="btn-play-ico" aria-hidden>
          ▶
        </span>
      </button>
    </div>
  ) : null;

  return (
    <div className={artifactShellClass}>
      <div className="run-artifact-card">
        {isFinalDoc ? (
          <>
            <div
              className={`run-artifact-body run-artifact-body--flush`}
            >
              <FinalOutputDocEditor
                value={editing ? draft : content}
                onChange={setDraft}
                readOnly={!editing || readOnly}
                targetWordCount={targetWordCount}
                onRequestEdit={() => setEditing(true)}
                toolbarExtra={
                  !readOnly ? (
                    <>
                      {savedHint}
                      {showCopyOutput ? (
                        <CopyOutputButton
                          text={editing ? draft : content}
                          stepName={stepName}
                          toast={toast}
                        />
                      ) : null}
                    </>
                  ) : null
                }
              />
            </div>
            {editorDock}
          </>
        ) : (
          <MarkdownArtifactPanel
            content={content}
            draft={draft}
            editing={editing && !readOnly}
            onDraftChange={setDraft}
            onEditingChange={(v) => {
              if (!v) clearAutosaveTimer();
              setEditing(v);
            }}
            readOnly={readOnly}
            canEdit={!readOnly && !formattedPreview}
            bodyClassName={formattedPreview ? "run-artifact-body--flush" : ""}
            previewNode={formattedPreview}
            savedHint={formattedPreview ? null : savedHint}
            footer={editorDock}
            textareaRows={22}
            showCopy={Boolean(content) && !formattedPreview}
            copySource={
              stepName === "final_output"
                ? copyMarkdownForStep(content, stepName)
                : content
            }
            onCopySuccess={() =>
              toast?.("Copied formatted article — paste into Word or your CMS", {
                variant: "success",
                duration: 3500,
              })
            }
            onCopyError={() =>
              toast?.("Could not copy", { variant: "error", duration: 4000 })
            }
          />
        )}
      </div>
    </div>
  );
}
