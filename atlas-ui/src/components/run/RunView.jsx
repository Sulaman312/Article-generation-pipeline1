import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as api from "../../services/api";
import { useToast } from "../../context/ToastContext";
import { stepsForPipeline } from "../../constants/pipelines";
import { inputSourceForStep, canRunStep } from "../../utils/pipelineFlow";
import { parseTopicCard } from "../../utils/parseTopicCard";
import { executeRunStep } from "../../utils/runStepAction";
import {
  invalidateArtifactCache,
  useLazyArtifact,
} from "../../hooks/useLazyArtifact";
import { isMetaSeoFormat } from "../../utils/parseMetaSeo";
import { isFactCheckFormat } from "../../utils/parseFactCheck";
import { isBriefFormat } from "../../utils/parseBrief";
import { isOutlineFormat } from "../../utils/parseOutlineStructured";
import {
  isResearchFormat,
  isSerpResearchFormat,
} from "../../utils/parseResearch";
import { copyFormattedMarkdown } from "../../utils/markdownExport";
import {
  formatStepStatusWithDuration,
  resolveStepTiming,
} from "../../utils/formatStepDuration";
import { preloadRunChunks } from "../../utils/preloadRunChunks";
import { ArtifactSkeleton } from "../shared/Skeletons";
import { PIPELINE_MARKDOWN_CLASS } from "../../constants/markdownPreview";
import { splitFinalOutput } from "../../utils/parseFinalOutput";

const FinalOutputDocEditor = lazy(() => import("./FinalOutputDocEditor"));
const MarkdownArtifactPanel = lazy(() =>
  import("../shared/MarkdownArtifactPanel")
);
const ArtifactFormattedPreview = lazy(() => import("./ArtifactFormattedPreview"));
const TopicCardStructured = lazy(() => import("./TopicCardStructured"));
const MetaSeoStructured = lazy(() => import("./MetaSeoStructured"));
const FactCheckStructured = lazy(() => import("./FactCheckStructured"));
const BriefStructured = lazy(() => import("./BriefStructured"));
const ResearchStructured = lazy(() => import("./ResearchStructured"));
const SerpResearchStructured = lazy(() => import("./SerpResearchStructured"));
const OutlineStructured = lazy(() => import("./OutlineStructured"));
const DraftStructured = lazy(() => import("./DraftStructured"));
const Markdown = lazy(() => import("../shared/Markdown"));

const AUTOSAVE_MS = 1000;

function statusClass(s) {
  if (s === "done" || s === "running" || s === "error" || s === "skipped")
    return s;
  return "pending";
}

function ArtifactChunkFallback() {
  return <ArtifactSkeleton />;
}

export default function RunView({
  client,
  runId,
  activeStepKey,
  statusOverrides = {},
  onSelectStep,
  onBack,
  run: sharedRun = null,
  refreshRun: sharedRefreshRun,
}) {
  const { toast } = useToast();
  const [localRun, setLocalRun] = useState(null);
  const [tab, setTab] = useState("output");
  const [error, setError] = useState(null);
  const [outputEditKey, setOutputEditKey] = useState(0);
  const [clockTick, setClockTick] = useState(0);
  const usesSharedRun = sharedRefreshRun != null;

  useEffect(() => {
    preloadRunChunks();
  }, []);

  const refreshRunLocal = useCallback(async () => {
    try {
      const r = await api.getRun(client, runId);
      setLocalRun(r);
      setError(null);
      return r;
    } catch (e) {
      setError(e?.message || String(e));
      return null;
    }
  }, [client, runId]);

  const refreshRun = sharedRefreshRun ?? refreshRunLocal;

  useEffect(() => {
    if (usesSharedRun) return undefined;
    let cancelled = false;
    let timerId = null;

    async function tick() {
      if (cancelled || document.visibilityState === "hidden") return;
      await refreshRunLocal();
    }

    function schedule() {
      if (timerId != null) {
        window.clearInterval(timerId);
        timerId = null;
      }
      if (document.visibilityState === "hidden") return;
      const running = Object.values(localRun?.statuses || {}).some(
        (s) => s === "running"
      );
      timerId = window.setInterval(tick, running ? 2500 : 30000);
    }

    tick().then(() => {
      if (!cancelled) schedule();
    });

    function onVisibilityChange() {
      if (document.visibilityState === "visible") {
        tick().then(() => {
          if (!cancelled) schedule();
        });
      } else if (timerId != null) {
        window.clearInterval(timerId);
        timerId = null;
      }
    }

    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      cancelled = true;
      if (timerId != null) window.clearInterval(timerId);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [usesSharedRun, refreshRunLocal, localRun?.statuses]);

  useEffect(() => {
    function onStepComplete(e) {
      const d = e.detail;
      if (d?.clientId !== client || d?.runId !== runId) return;
      invalidateArtifactCache(client, runId, d.stepKey);
      refreshRun();
      setTab("output");
    }
    window.addEventListener("cf:run-step-complete", onStepComplete);
    return () => window.removeEventListener("cf:run-step-complete", onStepComplete);
  }, [client, runId, refreshRun]);

  useEffect(() => {
    setOutputEditKey(0);
  }, [activeStepKey]);

  const run = usesSharedRun ? sharedRun : localRun;

  const serverStatuses = run?.statuses || {};
  const statuses = { ...serverStatuses, ...statusOverrides };
  const topic = run?.topic || "";
  const pipelineId = run?.pipeline_id || "article";
  const manualInputs = run?.manual_inputs;
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

  const activeTiming = useMemo(
    () =>
      resolveStepTiming(
        activeStep.key,
        run?.step_timings || {},
        {},
        status
      ),
    // clockTick keeps running elapsed fresh
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [activeStep.key, run?.step_timings, status, clockTick]
  );

  const statusText = useMemo(
    () => formatStepStatusWithDuration(status, activeTiming, Date.now()),
    [status, activeTiming, clockTick]
  );

  const inputSrc = useMemo(
    () => inputSourceForStep(activeStep.key, statuses, pipelineId),
    [activeStep.key, statuses, pipelineId]
  );
  const inputStep = useMemo(() => {
    if (inputSrc.kind !== "artifact") return null;
    return STEPS.find((s) => s.key === inputSrc.stepKey) || null;
  }, [inputSrc, STEPS]);

  useEffect(() => {
    if (!running) return undefined;
    const id = window.setInterval(() => setClockTick((t) => t + 1), 1000);
    return () => window.clearInterval(id);
  }, [running]);

  const prevStatusRef = useRef(null);
  useEffect(() => {
    const prev = prevStatusRef.current;
    if (prev === "running" && status === "done") {
      setTab("output");
    }
    prevStatusRef.current = status;
  }, [status]);

  // Prefer the resolved article input (skips publishing sidecars like meta_seo).
  const inputTabTitle =
    inputSrc.kind === "topic"
      ? "Input: topic"
      : inputStep
        ? `Input: ${inputStep.label}`
        : previousStep
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
            <span
              className={`status-pill status-pill--sm status-pill--fixed ${statusClass(status)}`}
              title={statusText}
            >
              <span className={`status-pip ${statusClass(status)}`} />
              {statusText}
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
            previousStep={previousStep}
            previousStatus={previousStep ? statuses[previousStep.key] : "done"}
            activeStepKey={activeStep.key}
            statuses={statuses}
            toast={toast}
            pipelineId={pipelineId}
            manualInputs={manualInputs}
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
            onGoToNextStep={(() => {
              const i = STEPS.findIndex((s) => s.key === activeStepKey);
              const next = STEPS[i + 1];
              if (!next) return undefined;
              return () => onSelectStep(next.key);
            })()}
          />
        )}
      </div>
    </div>
  );
}

function copyMarkdownForStep(markdown, stepName) {
  if (stepName === "final_output") {
    const split = splitFinalOutput(markdown);
    return (split.displayMarkdown || markdown || "").trim();
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
        toast?.(
          stepName === "final_output"
            ? "Copied with formatting — paste into Word, Docs, or your CMS"
            : "Copied formatted article — paste into Word or your CMS",
          {
            variant: "success",
            duration: 3500,
          }
        );
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
      title="Copy with formatting (headings, bold, lists, links)"
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
  previousStep,
  previousStatus,
  activeStepKey,
  statuses,
  toast,
  pipelineId,
  manualInputs,
}) {
  const src = inputSourceForStep(activeStepKey, statuses, pipelineId);

  if (isFirstStep) {
    return (
      <div className="run-artifact-shell">
        <div className="run-artifact-card">
          <div className="run-artifact-body run-input-topic-body">
            <div className="run-input-topic-eyebrow">Topic · this run</div>
            {topic?.trim() ? (
              <Suspense fallback={<ArtifactChunkFallback />}>
                <Markdown
                  text={topic}
                  className={`${PIPELINE_MARKDOWN_CLASS} md--topic-input`}
                />
              </Suspense>
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
              <Suspense fallback={<ArtifactChunkFallback />}>
                <Markdown
                  text={topic}
                  className={`${PIPELINE_MARKDOWN_CLASS} md--topic-input`}
                />
              </Suspense>
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
  const showInlineRun =
    status !== "done" &&
    status !== "running" &&
    !inlineRunning &&
    canRunStep(step.key, statuses, topic, pipelineId);

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
      onSaveAndContinue={onGoToNextStep || undefined}
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
  enabled = true,
}) {
  const { content, loading, setContent } = useLazyArtifact(
    client,
    runId,
    stepName,
    { enabled }
  );
  const isFinalDoc = stepName === "final_output";
  const { content: metaSeoText } = useLazyArtifact(
    client,
    runId,
    "meta_seo",
    { enabled: enabled && isFinalDoc }
  );
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [savedAt, setSavedAt] = useState(0);
  const autosaveTimer = useRef(null);
  const lastHeaderEditKey = useRef(-1);
  const showCopyOutput = ["draft", "fact_check", "final_output", "captions"].includes(
    stepName
  );

  useEffect(() => {
    setDraft(content);
  }, [content, stepName]);

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
    return clearAutosaveTimer;
  }, [stepName, readOnly]);

  useEffect(() => {
    if (readOnly || !useHeaderEdit) return;
    if (headerEditKey <= 0 || headerEditKey === lastHeaderEditKey.current)
      return;
    lastHeaderEditKey.current = headerEditKey;
    setEditing(true);
  }, [headerEditKey, readOnly, useHeaderEdit]);

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

  const canContinue = typeof onSaveAndContinue === "function";
  const isDirty = !readOnly && draft !== content;
  // Save only after real edits; continue stays available on earlier steps while editing.
  const showEditorDock = !readOnly && editing && (isDirty || canContinue);

  const topicCardPreview =
    stepName === "topic_card" &&
    Boolean(parseTopicCard(content)) &&
    (!readOnly || allowStructuredTopicCard) ? (
      <Suspense fallback={null}>
        <TopicCardStructured text={content} manualInputs={manualInputs} />
      </Suspense>
    ) : null;

  const metaSeoPreview =
    stepName === "meta_seo" && isMetaSeoFormat(content) ? (
      <Suspense fallback={null}>
        <MetaSeoStructured text={content} toast={toast} />
      </Suspense>
    ) : null;
  const factCheckPreview =
    stepName === "fact_check" && isFactCheckFormat(content) ? (
      <Suspense fallback={null}>
        <FactCheckStructured text={content} />
      </Suspense>
    ) : null;
  const briefPreview =
    stepName === "assignment_brief" && isBriefFormat(content) ? (
      <Suspense fallback={null}>
        <BriefStructured text={content} />
      </Suspense>
    ) : null;
  const researchPreview =
    stepName === "research" && isResearchFormat(content) ? (
      <Suspense fallback={null}>
        <ResearchStructured text={content} />
      </Suspense>
    ) : null;
  const serpPreview =
    stepName === "serp_research" && isSerpResearchFormat(content) ? (
      <Suspense fallback={null}>
        <SerpResearchStructured text={content} />
      </Suspense>
    ) : null;
  const outlinePreview =
    stepName === "outline" && isOutlineFormat(content) ? (
      <Suspense fallback={null}>
        <OutlineStructured text={content} />
      </Suspense>
    ) : null;
  const draftPreview =
    stepName === "draft" && String(content || "").trim() ? (
      <Suspense fallback={null}>
        <DraftStructured text={content} />
      </Suspense>
    ) : null;
  const structuredOnly =
    topicCardPreview ||
    metaSeoPreview ||
    factCheckPreview ||
    briefPreview ||
    researchPreview ||
    serpPreview ||
    outlinePreview ||
    draftPreview ||
    null;

  const formattedPreview = structuredOnly ? (
    <Suspense fallback={null}>
      <ArtifactFormattedPreview
        structured={structuredOnly}
        content={content}
        showFullSource={false}
        stepKey={stepName}
      />
    </Suspense>
  ) : null;

  const artifactShellClass = "run-artifact-shell";

  if (loading) {
    return (
      <div className="run-artifact-shell">
        <ArtifactSkeleton />
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
      {isDirty ? (
        <button
          type="button"
          className={
            canContinue
              ? "btn btn-dock-secondary"
              : "btn btn-primary btn-dock-primary"
          }
          onClick={handleSave}
        >
          Save
        </button>
      ) : null}
      {canContinue ? (
        <button
          type="button"
          className="btn btn-primary btn-dock-primary"
          onClick={handleSaveAndContinue}
        >
          {isDirty ? "Save & continue" : "Continue"}
          <span className="btn-play-ico" aria-hidden>
            ▶
          </span>
        </button>
      ) : null}
    </div>
  ) : null;

  return (
    <div className={artifactShellClass}>
      <div className="run-artifact-card">
        <Suspense fallback={<ArtifactChunkFallback />}>
          {isFinalDoc ? (
            <>
              <div className="run-artifact-body run-artifact-body--flush">
                <FinalOutputDocEditor
                  value={editing ? draft : content}
                  onChange={setDraft}
                  readOnly={!editing || readOnly}
                  targetWordCount={targetWordCount}
                  metaSeoText={metaSeoText}
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
              stepKey={stepName}
              draft={draft}
              editing={editing && !readOnly}
              onDraftChange={setDraft}
              onEditingChange={(v) => {
                if (!v) clearAutosaveTimer();
                setEditing(v);
              }}
              readOnly={readOnly}
              canEdit={!readOnly}
              bodyClassName={formattedPreview ? "run-artifact-body--flush" : ""}
              previewNode={formattedPreview}
              savedHint={savedHint}
              footer={editorDock}
              textareaRows={22}
              showCopy={Boolean(content)}
              copySource={
                stepName === "final_output"
                  ? copyMarkdownForStep(content, stepName)
                  : content
              }
              onCopySuccess={() =>
                toast?.(
                  stepName === "final_output" || stepName === "draft"
                    ? "Copied formatted article — paste into Word or your CMS"
                    : "Copied to clipboard",
                  { variant: "success", duration: 3500 }
                )
              }
              onCopyError={() =>
                toast?.("Could not copy", { variant: "error", duration: 4000 })
              }
            />
          )}
        </Suspense>
      </div>
    </div>
  );
}
