import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "../../services/api";
import { useToast } from "../../context/ToastContext";
import { stepsForPipeline } from "../../constants/pipelines";
import {
  SIDEBAR_WIDTH_MAX,
  SIDEBAR_WIDTH_MIN,
  useSidebarResize,
} from "../../hooks/useSidebarResize";
import { formatWorkspaceLabel } from "../../utils/formatWorkspaceLabel";
import {
  isSocialPipeline,
  socialAdditionalDetails,
  socialPostParagraph,
  socialRunTitle,
} from "../../utils/socialRunTopic";
import {
  formatStepStatusWithDuration,
  resolveStepTiming,
} from "../../utils/formatStepDuration";
import { canRunStep } from "../../utils/pipelineFlow";
import { executeRunStep } from "../../utils/runStepAction";
import WorkspaceLogo from "../workspace/WorkspaceLogo";

function IconEditorial(props) {
  return (
    <svg
      className="sb-nav-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      {...props}
    >
      <path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 9.5-9.5z" />
    </svg>
  );
}

function IconArtifacts(props) {
  return (
    <svg
      className="sb-nav-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      {...props}
    >
      <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
      <path d="M14 2v6h6M16 13H8M16 17H8M10 9H8" />
    </svg>
  );
}

function IconMatrix(props) {
  return (
    <svg
      className="sb-nav-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      {...props}
    >
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </svg>
  );
}

function IconPipelines(props) {
  return (
    <svg
      className="sb-nav-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      {...props}
    >
      <path d="M4 6h6v4H4zM14 6h6v4h-6zM4 14h6v4H4zM14 14h6v4h-6z" />
    </svg>
  );
}

function IconChevronLeft(props) {
  return (
    <svg
      className="sb-collapse-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      {...props}
    >
      <path d="M15 18l-6-6 6-6" />
    </svg>
  );
}

function IconChevronRight(props) {
  return (
    <svg
      className="sb-collapse-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      {...props}
    >
      <path d="M9 18l6-6-6-6" />
    </svg>
  );
}

function NavItem({
  collapsed,
  icon,
  label,
  active = false,
  accent = false,
  onClick,
}) {
  return (
    <button
      type="button"
      className={[
        "sb-item",
        active ? "active" : "",
        accent ? "sb-item--accent" : "",
        collapsed ? "sb-item--collapsed" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      onClick={onClick}
      title={collapsed ? label : undefined}
      aria-label={label}
      aria-current={active ? "page" : undefined}
    >
      {icon}
      <span className="sb-item-label">{label}</span>
    </button>
  );
}

function SidebarSection({ collapsed, title, children, className = "" }) {
  return (
    <div className={`sb-section ${className}`.trim()}>
      {!collapsed ? (
        <div className="sb-section-title">{title}</div>
      ) : null}
      {children}
    </div>
  );
}

function WorkspaceHomeNav({
  collapsed,
  workspaceView,
  onGoToPipeline,
  onGoToArtifacts,
}) {
  return (
    <SidebarSection collapsed={collapsed} title="Workspace">
      <NavItem
        collapsed={collapsed}
        icon={<IconPipelines />}
        label="Pipeline"
        active={workspaceView !== "artifacts"}
        onClick={onGoToPipeline}
      />
      <NavItem
        collapsed={collapsed}
        icon={<IconArtifacts />}
        label="Artifacts"
        active={workspaceView === "artifacts"}
        onClick={onGoToArtifacts}
      />
    </SidebarSection>
  );
}

function ContentPipelineNav({
  collapsed,
  workspaceView,
  activePipeline,
  onGoToPipeline,
  onGoToEditorial,
  onGoToMatrix,
  onGoToArtifacts,
}) {
  const inContent = activePipeline === "content";

  return (
    <SidebarSection collapsed={collapsed} title="Content pipeline">
      <NavItem
        collapsed={collapsed}
        icon={<IconPipelines />}
        label="Pipeline"
        active={activePipeline === null && workspaceView !== "artifacts"}
        onClick={onGoToPipeline}
      />
      <NavItem
        collapsed={collapsed}
        icon={<IconEditorial />}
        label="New article"
        active={inContent && workspaceView === "overview"}
        onClick={onGoToEditorial}
      />
      <NavItem
        collapsed={collapsed}
        icon={<IconMatrix />}
        label="Step matrix"
        active={inContent && workspaceView === "matrix"}
        onClick={onGoToMatrix}
      />
      <NavItem
        collapsed={collapsed}
        icon={<IconArtifacts />}
        label="Artifacts"
        active={inContent && workspaceView === "artifacts"}
        onClick={onGoToArtifacts}
      />
    </SidebarSection>
  );
}

function SocialPipelineNav({
  collapsed,
  workspaceView,
  activePipeline,
  onGoToPipeline,
  onGoToSocialBoard,
  onGoToSocialMatrix,
  onGoToArtifacts,
}) {
  const inSocial = activePipeline === "social";
  return (
    <SidebarSection collapsed={collapsed} title="Social pipeline">
      <NavItem
        collapsed={collapsed}
        icon={<IconPipelines />}
        label="Pipeline"
        active={activePipeline === null && workspaceView !== "artifacts"}
        onClick={onGoToPipeline}
      />
      <NavItem
        collapsed={collapsed}
        icon={<IconEditorial />}
        label="New post"
        active={inSocial && workspaceView === "overview"}
        onClick={onGoToSocialBoard}
      />
      <NavItem
        collapsed={collapsed}
        icon={<IconMatrix />}
        label="Step matrix"
        active={inSocial && workspaceView === "matrix"}
        onClick={onGoToSocialMatrix}
      />
      <NavItem
        collapsed={collapsed}
        icon={<IconArtifacts />}
        label="Artifacts"
        active={inSocial && workspaceView === "artifacts"}
        onClick={onGoToArtifacts}
      />
    </SidebarSection>
  );
}

function statusLabel(s) {
  if (s === "done") return "Done";
  if (s === "running") return "Running";
  if (s === "error") return "Error";
  if (s === "skipped") return "Skipped";
  return "Pending";
}

/** Numbered node for the collapsed pipeline rail. */
function CollapsedStepNode({ step, status, active, isRunningThis }) {
  const showDoneMark = status === "done" && !isRunningThis && !active;
  return (
    <span
      className={[
        "sb-collapsed-node",
        active ? "is-active" : "",
        status === "done" ? "is-done" : "",
        isRunningThis ? "is-running" : "",
        status === "error" ? "is-error" : "",
        status === "skipped" ? "is-skipped" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      aria-hidden
    >
      {showDoneMark ? (
        <svg viewBox="0 0 12 12" className="sb-collapsed-node-check" aria-hidden>
          <path
            d="M2.5 6.2 4.8 8.5 9.5 3.5"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      ) : (
        <span className="sb-collapsed-node-num">{step.index}</span>
      )}
    </span>
  );
}

function CollapsedRunProgress({ steps, statuses, activeStepKey }) {
  const total = steps.length;
  const doneCount = steps.filter(
    (s) => (statuses[s.key] || "pending") === "done"
  ).length;
  const idx = steps.findIndex((s) => s.key === activeStepKey);
  const pos = idx >= 0 ? idx + 1 : 1;
  const pct = total > 0 ? Math.round((doneCount / total) * 100) : 0;
  const circumference = 2 * Math.PI * 14;
  const offset = circumference - (pct / 100) * circumference;

  return (
    <div
      className="sb-collapsed-progress"
      title={`${doneCount} of ${total} steps complete`}
      aria-label={`${doneCount} of ${total} steps complete, on step ${pos}`}
    >
      <svg className="sb-collapsed-progress-ring" viewBox="0 0 36 36" aria-hidden>
        <circle className="sb-collapsed-progress-track" cx="18" cy="18" r="14" />
        <circle
          className="sb-collapsed-progress-fill"
          cx="18"
          cy="18"
          r="14"
          style={{
            strokeDasharray: circumference,
            strokeDashoffset: offset,
          }}
        />
      </svg>
      <span className="sb-collapsed-progress-text">{pos}</span>
    </div>
  );
}

function StepRailDot({ status, active, isRunningThis }) {
  const showDoneTick = status === "done" && !isRunningThis;
  return (
    <span
      className={[
        "sb-step-dot",
        showDoneTick ? "sb-step-dot--done" : "",
        active && !showDoneTick ? "sb-step-dot--active" : "",
        isRunningThis ? "sb-step-dot--running" : "",
        status === "error" ? "sb-step-dot--error" : "",
        status === "skipped" ? "sb-step-dot--skipped" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {showDoneTick ? (
        <svg viewBox="0 0 12 12" className="sb-step-dot-icon" aria-hidden>
          <path
            d="M2.8 6.2 5.1 8.5 9.2 3.8"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.75"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      ) : null}
    </span>
  );
}

function splitStepStatus(statusText) {
  const parts = String(statusText || "").split(" · ");
  return {
    label: parts[0] || statusText,
    detail: parts.length > 1 ? parts.slice(1).join(" · ") : null,
  };
}

function IconRerun(props) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      aria-hidden
      {...props}
    >
      <path
        d="M13.2 3.2v3.6H9.6M2.8 12.8V9.2h3.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M12.2 5.8a4.6 4.6 0 0 0-7.2-1.2M3.8 10.2a4.6 4.6 0 0 0 7.2 1.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function IconPlayStep(props) {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden {...props}>
      <path d="M5 3.2 12.2 8 5 12.8V3.2z" />
    </svg>
  );
}

function IconPauseStep(props) {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden {...props}>
      <rect x="4" y="3.5" width="3" height="9" rx="0.5" />
      <rect x="9" y="3.5" width="3" height="9" rx="0.5" />
    </svg>
  );
}

export default function AppSidebar({
  client,
  runId,
  collapsed = false,
  sidebarWidth = 380,
  onSidebarWidthChange,
  onToggleCollapse,
  activeStepKey,
  onSelectStep,
  onGoHome,
  onClearRun,
  workspaceView = "overview",
  onWorkspaceViewChange,
  onGoToEditorial,
  onGoToMatrix,
  onGoToSocialBoard,
  onGoToSocialMatrix,
  onGoToArtifacts,
  onGoToPipeline,
  activePipeline = null,
  lockedPipeline = null,
  logoVersion = 0,
  onPatchStepStatus,
  stepStatusOverrides = {},
}) {
  const handleWidthChange = useCallback(
    (w) => onSidebarWidthChange?.(w),
    [onSidebarWidthChange]
  );
  const onResizePointerDown = useSidebarResize({
    enabled: !collapsed && Boolean(onSidebarWidthChange),
    width: sidebarWidth,
    onWidthChange: handleWidthChange,
    min: SIDEBAR_WIDTH_MIN,
    max: SIDEBAR_WIDTH_MAX,
  });

  if (!client) return null;

  const workspaceTitle = formatWorkspaceLabel(client);

  return (
    <aside
      className={`sb${collapsed ? " sb--collapsed" : ""}`}
      aria-expanded={!collapsed}
    >
      <div className="sb-brand">
        <div className="sb-brand-main">
          <div className="sb-brand-logo-wrap" aria-hidden>
            <WorkspaceLogo
              clientId={client}
              size={40}
              className="sb-brand-logo"
              cacheKey={logoVersion}
            />
          </div>
          {!collapsed ? (
            <div className="sb-brand-text">
              <span className="sb-brand-kicker">Workspace</span>
              <button
                type="button"
                className="sb-brand-name sb-brand-name--workspace sb-brand-name-btn"
                onClick={onGoHome}
                title="All workspaces"
              >
                {workspaceTitle}
              </button>
            </div>
          ) : null}
        </div>
        <button
          type="button"
          className="sb-collapse-btn"
          onClick={onToggleCollapse}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-expanded={!collapsed}
        >
          {collapsed ? <IconChevronRight /> : <IconChevronLeft />}
        </button>
      </div>

      <div className="sb-scroll">
        {!runId ? (
          <ClientNavSection
            client={client}
            collapsed={collapsed}
            workspaceView={workspaceView}
            activePipeline={activePipeline}
            lockedPipeline={lockedPipeline}
            onGoToEditorial={onGoToEditorial}
            onGoToMatrix={onGoToMatrix}
            onGoToSocialBoard={onGoToSocialBoard}
            onGoToSocialMatrix={onGoToSocialMatrix}
            onGoToArtifacts={onGoToArtifacts}
            onGoToPipeline={onGoToPipeline}
          />
        ) : (
          <RunNavSection
            client={client}
            runId={runId}
            collapsed={collapsed}
            activeStepKey={activeStepKey}
            onSelectStep={onSelectStep}
            onClearRun={onClearRun}
            onGoToMatrix={onGoToMatrix}
            onGoToSocialMatrix={onGoToSocialMatrix}
            onPatchStepStatus={onPatchStepStatus}
            statusOverrides={stepStatusOverrides}
          />
        )}
      </div>

      <div className="sb-foot">
        {!collapsed ? (
          <span>ContentFlow • 8 steps</span>
        ) : runId ? null : (
          <span className="sb-foot-expand-hint" title="Expand sidebar" aria-hidden>
            ···
          </span>
        )}
      </div>

      {!collapsed && onSidebarWidthChange ? (
        <div
          className="sb-resize-handle"
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize sidebar"
          title="Drag to resize sidebar"
          onPointerDown={onResizePointerDown}
        />
      ) : null}
    </aside>
  );
}

function ClientNavSection({
  collapsed,
  workspaceView,
  activePipeline,
  lockedPipeline = null,
  onGoToEditorial,
  onGoToMatrix,
  onGoToSocialBoard,
  onGoToSocialMatrix,
  onGoToArtifacts,
  onGoToPipeline,
}) {
  const navPipeline = activePipeline ?? lockedPipeline;

  if (navPipeline === null) {
    return (
      <WorkspaceHomeNav
        collapsed={collapsed}
        workspaceView={workspaceView}
        onGoToPipeline={onGoToPipeline}
        onGoToArtifacts={onGoToArtifacts}
      />
    );
  }
  if (navPipeline === "social") {
    return (
      <SocialPipelineNav
        collapsed={collapsed}
        workspaceView={workspaceView}
        activePipeline={activePipeline}
        onGoToPipeline={onGoToPipeline}
        onGoToSocialBoard={onGoToSocialBoard}
        onGoToSocialMatrix={onGoToSocialMatrix}
        onGoToArtifacts={onGoToArtifacts}
      />
    );
  }
  return (
    <ContentPipelineNav
      collapsed={collapsed}
      workspaceView={workspaceView}
      activePipeline={activePipeline}
      onGoToPipeline={onGoToPipeline}
      onGoToEditorial={onGoToEditorial}
      onGoToMatrix={onGoToMatrix}
      onGoToArtifacts={onGoToArtifacts}
    />
  );
}

function RunNavSection({
  client,
  runId,
  collapsed,
  activeStepKey,
  onSelectStep,
  onClearRun,
  onGoToMatrix,
  onGoToSocialMatrix,
  onPatchStepStatus,
  statusOverrides = {},
}) {
  const { toast } = useToast();
  const [run, setRun] = useState(null);
  const [runningStepKey, setRunningStepKey] = useState(null);
  const [hoveredStepKey, setHoveredStepKey] = useState(null);
  const [clockTick, setClockTick] = useState(0);
  const [clientStepDurations, setClientStepDurations] = useState({});
  const runAbortRef = useRef(null);
  const stepRunStartRef = useRef({});

  function reconcileStatusOverrides(serverStatuses) {
    for (const stepKey of Object.keys(statusOverrides)) {
      const server = serverStatuses[stepKey] ?? "pending";
      const override = statusOverrides[stepKey];
      if (server === override) {
        onPatchStepStatus?.(stepKey, null);
        continue;
      }
      if (override === "pending" && server === "running") {
        continue;
      }
      onPatchStepStatus?.(stepKey, null);
    }
  }

  async function loadRun() {
    try {
      const r = await api.getRun(client, runId);
      setRun(r);
      reconcileStatusOverrides(r.statuses || {});
    } catch {
      /* ignore */
    }
  }

  function markStepPending(stepKey) {
    onPatchStepStatus?.(stepKey, "pending");
    setRunningStepKey(null);
    runAbortRef.current = null;
  }

  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (cancelled) return;
      await loadRun();
    }
    load();
    const id = setInterval(load, 2000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [client, runId]);

  const serverStatuses = run?.statuses || {};
  const statuses = { ...serverStatuses, ...statusOverrides };
  const storedTopic = run?.topic || "";
  const pipelineId = run?.pipeline_id || "article";
  const isSocial = isSocialPipeline(pipelineId);
  const topic = isSocial
    ? socialRunTitle(run?.manual_inputs, storedTopic)
    : storedTopic;
  const topicTooltip = isSocial
    ? [socialPostParagraph(run?.manual_inputs), socialAdditionalDetails(run?.manual_inputs)]
        .filter(Boolean)
        .join("\n\n") || topic
    : storedTopic;
  const STEPS = stepsForPipeline(pipelineId);
  const stepTimings = run?.step_timings || {};

  const hasRunningStep =
    Boolean(runningStepKey) ||
    Object.values(statuses).some((s) => s === "running");

  useEffect(() => {
    if (!hasRunningStep) return undefined;
    const id = window.setInterval(() => setClockTick((t) => t + 1), 1000);
    return () => window.clearInterval(id);
  }, [hasRunningStep]);

  async function handleRunStep(stepKey, e) {
    e?.stopPropagation?.();
    if (runningStepKey) return;
    const st = statuses[stepKey] || "pending";
    if (st === "running") return;
    if (!canRunStep(stepKey, statuses, topic, pipelineId) && st !== "done") return;

    onSelectStep(stepKey);
    const ac = new AbortController();
    runAbortRef.current = ac;
    setRunningStepKey(stepKey);
    const runStartedAt = Date.now();
    stepRunStartRef.current[stepKey] = runStartedAt;
    try {
      const ran = await executeRunStep(
        api,
        client,
        runId,
        stepKey,
        topic,
        statuses,
        ac.signal,
        pipelineId
      );
      const elapsedMs = Date.now() - runStartedAt;
      setClientStepDurations((prev) => ({
        ...prev,
        [stepKey]: elapsedMs,
      }));
      await loadRun();
      onSelectStep(stepKey);
      window.dispatchEvent(
        new CustomEvent("cf:run-step-complete", {
          detail: { clientId: client, runId, stepKey },
        })
      );
      toast(
        st === "done" ? `Re-ran ${ran?.label || "step"}.` : `Ran ${ran?.label || "step"}.`,
        { variant: "success", duration: 3500 }
      );
    } catch (err) {
      const msg = err?.message || String(err);
      if (msg === "Stopped by user.") {
        markStepPending(stepKey);
        const cancelled = await tryCancelOnServer(stepKey);
        await loadRun();
        toast(
          cancelled
            ? "Step paused."
            : "Step paused in the UI. Restart python main.py, then pause again if it still shows Running.",
          { variant: "success", duration: cancelled ? 3500 : 6000 }
        );
      } else {
        toast(msg, { variant: "error", duration: 12000 });
      }
    } finally {
      runAbortRef.current = null;
      setRunningStepKey(null);
    }
  }

  async function tryCancelOnServer(stepKey) {
    try {
      await api.cancelStep(client, runId, stepKey);
      return true;
    } catch {
      return false;
    }
  }

  async function handlePauseStep(stepKey, e) {
    e?.stopPropagation?.();
    if (runningStepKey === stepKey && runAbortRef.current) {
      const ac = runAbortRef.current;
      ac.abort();
      markStepPending(stepKey);
      const cancelled = await tryCancelOnServer(stepKey);
      await loadRun();
      toast(
        cancelled
          ? "Step paused."
          : "Step paused in the UI. Restart python main.py, then pause again to reset the server.",
        { variant: "success", duration: cancelled ? 3500 : 6000 }
      );
      return;
    }
    if ((serverStatuses[stepKey] || "pending") !== "running") return;
    markStepPending(stepKey);
    const cancelled = await tryCancelOnServer(stepKey);
    await loadRun();
    toast(
      cancelled
        ? "Step reset to pending."
        : "Shown as pending here. Restart python main.py so the server can clear Running.",
      { variant: "success", duration: cancelled ? 3500 : 6000 }
    );
  }

  function handleBack() {
    onClearRun?.();
    if ((run?.pipeline_id || "article") === "social_media") onGoToSocialMatrix?.();
    else onGoToMatrix?.();
  }

  return (
    <>
      {!collapsed ? (
        <div className="sb-run-nav-top">
          <button
            type="button"
            className="sb-item active sb-run-back"
            onClick={handleBack}
            aria-label="Back to step matrix"
          >
            <IconMatrix />
            <span className="sb-item-label">Step matrix</span>
          </button>
          {topic ? (
            <p className="sb-run-topic" title={topicTooltip}>
              {topic}
            </p>
          ) : null}
        </div>
      ) : (
        <button
          type="button"
          className="sb-collapsed-back sb-collapsed-back--matrix"
          onClick={handleBack}
          title="Back to step matrix"
          aria-label="Back to step matrix"
        >
          <IconMatrix />
        </button>
      )}

      <SidebarSection
        collapsed={collapsed}
        title="Pipeline steps"
        className={[
          "sb-section--pipeline",
          collapsed ? "sb-section--collapsed-rail" : "",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        <div
          className={
            collapsed
              ? "sb-collapsed-steps"
              : `sb-steps-stack sb-steps-timeline`
          }
          data-clock-tick={hasRunningStep ? clockTick : undefined}
        >
          {STEPS.map((step, stepIdx) => {
            const s = statuses[step.key] || "pending";
            const active = step.key === activeStepKey;
            const isLast = stepIdx === STEPS.length - 1;
            const runnable =
              s !== "running" &&
              (s === "done" ||
                s === "skipped" ||
                canRunStep(step.key, statuses, topic, pipelineId));
            const isRunningThis =
              (s === "running" || runningStepKey === step.key) &&
              s !== "pending";
            const pausable =
              isRunningThis &&
              (runningStepKey === step.key || s === "running");
            let resolvedTiming = resolveStepTiming(
              step.key,
              stepTimings,
              clientStepDurations
            );
            const localStart = stepRunStartRef.current[step.key];
            if (
              (isRunningThis || runningStepKey === step.key) &&
              localStart &&
              !resolvedTiming?.duration_ms
            ) {
              resolvedTiming = {
                ...resolvedTiming,
                started_at: new Date(localStart).toISOString(),
              };
            }
            const statusText = formatStepStatusWithDuration(
              s,
              resolvedTiming,
              Date.now()
            );
            const timingTitle = resolvedTiming?.client
              ? "Duration measured in this browser session"
              : resolvedTiming?.inferred && resolvedTiming?.duration_ms
                ? "Estimated from when each step file was saved"
                : undefined;
            const cls = [
              "sb-step",
              collapsed ? "sb-step--collapsed" : "",
              active ? "active" : "",
              s === "done" ? "is-done" : "",
              isRunningThis ? "is-running" : "",
              s === "error" ? "is-error" : "",
              s === "skipped" ? "is-skipped" : "",
            ]
              .filter(Boolean)
              .join(" ");
            const { label: stepStatusText, detail: statusDetail } =
              splitStepStatus(statusText);
            const rowCls = [
              "sb-step-row",
              isLast ? "sb-step-row--last" : "",
              active ? "active" : "",
              s === "done" ? "is-done" : "",
              isRunningThis ? "is-running" : "",
              s === "error" ? "is-error" : "",
              s === "skipped" ? "is-skipped" : "",
            ]
              .filter(Boolean)
              .join(" ");
            const showRailAction =
              !collapsed &&
              (active || hoveredStepKey === step.key) &&
              Boolean(pausable || runnable);

            return (
              <div
                key={step.key}
                className={rowCls}
                onMouseEnter={() => setHoveredStepKey(step.key)}
                onMouseLeave={() => setHoveredStepKey(null)}
              >
                <div className="sb-step-card">
                {!collapsed ? (
                  <div className="sb-step-rail">
                    <div className="sb-step-rail-slot">
                      {pausable ? (
                        <button
                          type="button"
                          className="sb-step-rail-btn sb-step-rail-btn--pause"
                          aria-label={`Pause ${step.label}`}
                          title={`Pause ${step.label}`}
                          onClick={(e) => handlePauseStep(step.key, e)}
                        >
                          <IconPauseStep />
                        </button>
                      ) : showRailAction && runnable ? (
                        <button
                          type="button"
                          className={`sb-step-rail-btn${
                            s === "done"
                              ? " sb-step-rail-btn--rerun"
                              : " sb-step-rail-btn--play"
                          }`}
                          disabled={Boolean(runningStepKey)}
                          aria-label={
                            s === "done"
                              ? `Re-run ${step.label}`
                              : `Run ${step.label}`
                          }
                          title={
                            s === "done"
                              ? `Re-run ${step.label}`
                              : `Run ${step.label}`
                          }
                          onClick={(e) => handleRunStep(step.key, e)}
                        >
                          {runningStepKey === step.key ? (
                            <span className="spinner spinner--sm" aria-hidden />
                          ) : s === "done" ? (
                            <IconRerun />
                          ) : (
                            <IconPlayStep />
                          )}
                        </button>
                      ) : (
                        <div className="sb-step-rail-indicator" aria-hidden>
                          <StepRailDot
                            status={s}
                            active={active}
                            isRunningThis={isRunningThis}
                          />
                        </div>
                      )}
                    </div>
                  </div>
                ) : null}
                <button
                  type="button"
                  onClick={() => onSelectStep(step.key)}
                  className={cls}
                  aria-label={
                    collapsed
                      ? `${step.index}. ${step.label} — ${statusText}`
                      : `${step.label} — ${statusText}`
                  }
                  title={
                    collapsed
                      ? `${step.index}. ${step.label} — ${statusText}`
                      : timingTitle
                  }
                  data-tip={
                    collapsed
                      ? `${step.label} · ${statusLabel(s)}`
                      : undefined
                  }
                >
                  {collapsed ? (
                    <CollapsedStepNode
                      step={step}
                      status={s}
                      active={active}
                      isRunningThis={isRunningThis}
                    />
                  ) : null}
                  {!collapsed ? (
                    <span className="sb-step-text">
                      <div className="sb-step-label">
                        <span className="sb-step-name">{step.label}</span>
                      </div>
                      <div className="sb-step-meta" title={timingTitle}>
                        <span className={`sb-step-badge sb-step-badge--${s}`}>
                          {stepStatusText}
                        </span>
                        {statusDetail ? (
                          <span className="sb-step-duration">{statusDetail}</span>
                        ) : null}
                      </div>
                    </span>
                  ) : null}
                  {!collapsed && isRunningThis ? (
                    <span className="spinner sb-step-spinner" />
                  ) : !collapsed ? (
                    <span className="sb-step-trail" aria-hidden />
                  ) : null}
                </button>
                </div>
              </div>
            );
          })}
        </div>
        {collapsed ? (
          <CollapsedRunProgress
            steps={STEPS}
            statuses={statuses}
            activeStepKey={activeStepKey}
          />
        ) : null}
      </SidebarSection>
    </>
  );
}
