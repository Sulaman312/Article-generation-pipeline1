import { useEffect, useState } from "react";
import "./App.css";
import AppSidebar from "./components/shared/AppSidebar";
import ClientsGrid from "./components/workspace/ClientsGrid";
import ClientHome from "./components/workspace/ClientHome";
import RunView from "./components/run/RunView";
import StepMatrixScreen from "./components/run/StepMatrixScreen";
import ContentPipelineBoard from "./components/workspace/ContentPipelineBoard";
import { ToastProvider } from "./context/ToastContext";
import { CONTENTFLOW_LOGO } from "./constants/brand";
import { appProductMeta } from "./constants/appProject";
import { hydratePipelineSteps } from "./constants/pipelineRegistry";
import { readStoredSidebarWidth } from "./hooks/useSidebarResize";
import * as api from "./services/api";

const PRODUCT = appProductMeta();

function App() {
  const [client, setClient] = useState(null);
  const [runId, setRunId] = useState(null);
  const [activeStepKey, setActiveStepKey] = useState("topic_card");
  const [clientsRefresh, setClientsRefresh] = useState(0);
  const [workspaceView, setWorkspaceView] = useState("matrix");
  const [artifactFilename, setArtifactFilename] = useState(null);
  const [logoVersions, setLogoVersions] = useState({});
  const [stepStatusOverrides, setStepStatusOverrides] = useState({});
  const [pipelineReady, setPipelineReady] = useState(false);

  useEffect(() => {
    if (process.env.NODE_ENV === "test") {
      setPipelineReady(true);
      return undefined;
    }
    let cancelled = false;
    hydratePipelineSteps(api).finally(() => {
      if (!cancelled) setPipelineReady(true);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try {
      return localStorage.getItem("cf-sidebar-collapsed") === "1";
    } catch {
      return false;
    }
  });

  const [sidebarWidth, setSidebarWidth] = useState(readStoredSidebarWidth);

  useEffect(() => {
    try {
      localStorage.setItem(
        "cf-sidebar-collapsed",
        sidebarCollapsed ? "1" : "0"
      );
    } catch {
      /* ignore */
    }
  }, [sidebarCollapsed]);

  useEffect(() => {
    if (sidebarCollapsed) return;
    try {
      localStorage.setItem("cf-sidebar-width", String(sidebarWidth));
    } catch {
      /* ignore */
    }
  }, [sidebarWidth, sidebarCollapsed]);

  function goHome() {
    setClient(null);
    setRunId(null);
    setWorkspaceView("matrix");
    setArtifactFilename(null);
  }

  function handleClientDeleted() {
    goHome();
    setClientsRefresh((n) => n + 1);
  }

  function bumpClientLogo(clientId) {
    setLogoVersions((v) => ({ ...v, [clientId]: Date.now() }));
  }

  function openClient(c) {
    setClient(c);
    setRunId(null);
    setWorkspaceView("matrix");
    setArtifactFilename(null);
  }

  function openRun(id) {
    setRunId(id);
    setActiveStepKey("topic_card");
    setStepStatusOverrides({});
  }

  function patchStepStatus(stepKey, status) {
    if (stepKey == null && status == null) {
      setStepStatusOverrides({});
      return;
    }
    setStepStatusOverrides((prev) => {
      if (status == null) {
        if (!(stepKey in prev)) return prev;
        const next = { ...prev };
        delete next[stepKey];
        return next;
      }
      return { ...prev, [stepKey]: status };
    });
  }

  function closeRun() {
    setRunId(null);
    setStepStatusOverrides({});
    setWorkspaceView("matrix");
  }

  function handleWorkspaceViewChange(view) {
    setWorkspaceView(view);
    setArtifactFilename(null);
  }

  function goToEditorial() {
    setRunId(null);
    setWorkspaceView("overview");
    setArtifactFilename(null);
  }

  function goToMatrix() {
    setRunId(null);
    setWorkspaceView("matrix");
    setArtifactFilename(null);
  }

  function goToArtifacts() {
    setRunId(null);
    setWorkspaceView("artifacts");
    setArtifactFilename(null);
  }

  if (!pipelineReady) {
    return (
      <div className="layout-flat">
        <main className="layout-main">
          <p style={{ textAlign: "center", padding: "2rem", color: "#64748b" }}>
            Loading pipeline…
          </p>
        </main>
      </div>
    );
  }

  if (!client) {
    return (
      <div className="layout-flat">
        <header className="topbar">
          <div className="topbar-brand" onClick={goHome}>
            <img
              className="topbar-mark-img"
              src={CONTENTFLOW_LOGO}
              alt="ContentFlow"
              width={36}
              height={36}
            />
            <div className="topbar-name">
              {PRODUCT.name}
              <span className="topbar-meta">{PRODUCT.workspaceTagline}</span>
            </div>
          </div>
        </header>
        <main className="layout-main">
          <ClientsGrid
            key={clientsRefresh}
            onOpenClient={openClient}
            logoVersions={logoVersions}
            onClientLogoSaved={bumpClientLogo}
          />
        </main>
      </div>
    );
  }

  return (
    <div
      className={`layout${sidebarCollapsed ? " layout--sb-collapsed" : ""}`}
      style={
        sidebarCollapsed
          ? undefined
          : { "--sidebar-w": `${sidebarWidth}px` }
      }
    >
      <AppSidebar
        client={client}
        runId={runId}
        collapsed={sidebarCollapsed}
        sidebarWidth={sidebarWidth}
        onSidebarWidthChange={setSidebarWidth}
        onToggleCollapse={() => setSidebarCollapsed((v) => !v)}
        activeStepKey={activeStepKey}
        onSelectStep={setActiveStepKey}
        onGoHome={goHome}
        onClearRun={closeRun}
        workspaceView={workspaceView}
        onWorkspaceViewChange={handleWorkspaceViewChange}
        onGoToEditorial={goToEditorial}
        onGoToMatrix={goToMatrix}
        onGoToArtifacts={goToArtifacts}
        activePipeline="content"
        lockedPipeline="content"
        logoVersion={logoVersions[client] || 0}
        onPatchStepStatus={patchStepStatus}
        stepStatusOverrides={stepStatusOverrides}
      />
      <main className="layout-main">
        {!runId && workspaceView === "artifacts" ? (
          <ClientHome
            client={client}
            onOpenRun={openRun}
            onClientDeleted={handleClientDeleted}
            workspaceView={workspaceView}
            artifactFilename={artifactFilename}
            onArtifactFilenameChange={setArtifactFilename}
          />
        ) : !runId && workspaceView === "matrix" ? (
          <StepMatrixScreen
            client={client}
            onOpenRun={openRun}
            onClientDeleted={handleClientDeleted}
            onBackToBoard={() => setWorkspaceView("overview")}
          />
        ) : !runId && workspaceView === "overview" ? (
          <ContentPipelineBoard
            client={client}
            onOpenRun={openRun}
            onClientDeleted={handleClientDeleted}
          />
        ) : !runId ? (
          <ClientHome
            client={client}
            onOpenRun={openRun}
            onClientDeleted={handleClientDeleted}
            workspaceView={workspaceView}
            artifactFilename={artifactFilename}
            onArtifactFilenameChange={setArtifactFilename}
          />
        ) : (
          <RunView
            client={client}
            runId={runId}
            activeStepKey={activeStepKey}
            statusOverrides={stepStatusOverrides}
            onSelectStep={setActiveStepKey}
            onBack={() => {
              closeRun();
              setWorkspaceView("matrix");
            }}
          />
        )}
      </main>
    </div>
  );
}

export default function AppWithToast() {
  return (
    <ToastProvider>
      <App />
    </ToastProvider>
  );
}
