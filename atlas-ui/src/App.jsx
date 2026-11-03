import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import "./App.css";
import LoginPage from "./components/auth/LoginPage";
import { IconLogout } from "./components/shared/icons";
import AppSidebar from "./components/shared/AppSidebar";
import ClientsGrid from "./components/workspace/ClientsGrid";
import WorkspaceSyncBanner from "./components/shared/WorkspaceSyncBanner";
import { MatrixSkeleton } from "./components/shared/Skeletons";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { ToastProvider } from "./context/ToastContext";
import { CONTENTFLOW_LOGO } from "./constants/brand";
import { appProductMeta } from "./constants/appProject";
import { hydratePipelineSteps } from "./constants/pipelineRegistry";
import { readStoredSidebarWidth } from "./hooks/useSidebarResize";
import { useRun } from "./hooks/useRun";
import {
  parseAppPath,
  pushAppPath,
  replaceAppPath,
} from "./utils/appNavigation";
import { preloadRunChunks } from "./utils/preloadRunChunks";
import * as api from "./services/api";

const RunView = lazy(() => import("./components/run/RunView"));
const StepMatrixScreen = lazy(() => import("./components/run/StepMatrixScreen"));
const ContentPipelineBoard = lazy(() =>
  import("./components/workspace/ContentPipelineBoard")
);
const ClientHome = lazy(() => import("./components/workspace/ClientHome"));

function ViewFallback() {
  return (
    <div className="layout-main" style={{ padding: "1.5rem" }}>
      <MatrixSkeleton rows={4} />
    </div>
  );
}

const PRODUCT = appProductMeta();

function clientIdOf(c) {
  if (!c) return null;
  return typeof c === "string" ? c : c.id || null;
}

function App() {
  const { ready: authReady, signedIn, user, signOut } = useAuth();
  const initialRoute =
    typeof window !== "undefined" ? parseAppPath() : { clientId: null, runId: null, view: "matrix" };
  const [client, setClient] = useState(initialRoute.clientId);
  const [runId, setRunId] = useState(initialRoute.runId);
  const [activeStepKey, setActiveStepKey] = useState("topic_card");
  const [clientsRefresh, setClientsRefresh] = useState(0);
  const [workspaceView, setWorkspaceView] = useState(initialRoute.view || "matrix");
  const [artifactFilename, setArtifactFilename] = useState(null);
  const [logoVersions, setLogoVersions] = useState({});
  const [stepStatusOverrides, setStepStatusOverrides] = useState({});
  const [pipelineEpoch, setPipelineEpoch] = useState(0);

  useEffect(() => {
    if (!signedIn) return undefined;
    if (import.meta.env.MODE === "test") return undefined;
    let cancelled = false;
    hydratePipelineSteps(api)
      .then(() => {
        if (!cancelled) setPipelineEpoch((n) => n + 1);
      })
      .catch(() => {
        /* fallback steps already loaded */
      });
    return () => {
      cancelled = true;
    };
  }, [signedIn]);

  useEffect(() => {
    function onPopState() {
      const route = parseAppPath();
      setClient(route.clientId);
      setRunId(route.runId);
      setWorkspaceView(route.view || "matrix");
      setArtifactFilename(null);
      setStepStatusOverrides({});
      if (route.runId) setActiveStepKey("topic_card");
    }
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    if (!signedIn) {
      replaceAppPath({});
      return;
    }
    replaceAppPath({
      clientId: clientIdOf(client),
      runId,
      view: workspaceView,
    });
  }, [signedIn, client, runId, workspaceView]);

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
    pushAppPath({});
  }

  async function handleSignOut() {
    goHome();
    await signOut();
  }

  function handleClientDeleted() {
    goHome();
    setClientsRefresh((n) => n + 1);
  }

  function bumpClientLogo(clientId) {
    setLogoVersions((v) => ({ ...v, [clientId]: Date.now() }));
  }

  function openClient(c) {
    const id = clientIdOf(c);
    setClient(id);
    setRunId(null);
    setWorkspaceView("matrix");
    setArtifactFilename(null);
    pushAppPath({ clientId: id, view: "matrix" });
  }

  function openRun(id) {
    preloadRunChunks();
    setRunId(id);
    setActiveStepKey("topic_card");
    setStepStatusOverrides({});
    pushAppPath({
      clientId: clientIdOf(client),
      runId: id,
      view: "matrix",
    });
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

  const reconcileStatusOverrides = useCallback(
    (serverStatuses) => {
      for (const stepKey of Object.keys(stepStatusOverrides)) {
        const server = serverStatuses[stepKey] ?? "pending";
        const override = stepStatusOverrides[stepKey];
        if (server === override) {
          patchStepStatus(stepKey, null);
          continue;
        }
        if (override === "pending" && server === "running") {
          continue;
        }
        if (override === "running" && (server === "pending" || server === "running")) {
          continue;
        }
        patchStepStatus(stepKey, null);
      }
    },
    [stepStatusOverrides]
  );

  const { run, refreshRun } = useRun(client, runId, {
    onSuccess: (r) => reconcileStatusOverrides(r.statuses || {}),
  });

  function closeRun() {
    setRunId(null);
    setStepStatusOverrides({});
    setWorkspaceView("matrix");
    pushAppPath({
      clientId: clientIdOf(client),
      view: "matrix",
    });
  }

  function handleWorkspaceViewChange(view) {
    setWorkspaceView(view);
    setArtifactFilename(null);
    pushAppPath({
      clientId: clientIdOf(client),
      view,
    });
  }

  function goToEditorial() {
    setRunId(null);
    setWorkspaceView("overview");
    setArtifactFilename(null);
    pushAppPath({
      clientId: clientIdOf(client),
      view: "overview",
    });
  }

  function goToMatrix() {
    setRunId(null);
    setWorkspaceView("matrix");
    setArtifactFilename(null);
    pushAppPath({
      clientId: clientIdOf(client),
      view: "matrix",
    });
  }

  function goToArtifacts() {
    setRunId(null);
    setWorkspaceView("artifacts");
    setArtifactFilename(null);
    pushAppPath({
      clientId: clientIdOf(client),
      view: "artifacts",
    });
  }

  if (!authReady && !signedIn) {
    return (
      <div className="layout-flat">
        <main className="layout-main">
          <p style={{ textAlign: "center", padding: "2rem", color: "#64748b" }}>
            Checking session…
          </p>
        </main>
      </div>
    );
  }

  if (!signedIn) {
    return <LoginPage />;
  }

  if (!client) {
    return (
      <div className="layout-flat">
        <WorkspaceSyncBanner />
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
          <div className="topbar-actions">
            <span className="topbar-user" title="Signed in">
              <span className="topbar-user-avatar" aria-hidden>
                {(user?.username || "?").slice(0, 1).toUpperCase()}
              </span>
              {user?.username}
            </span>
            <button
              type="button"
              className="btn-logout"
              onClick={handleSignOut}
            >
              <IconLogout />
              <span>Log out</span>
            </button>
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
      data-pipeline-epoch={pipelineEpoch}
      style={
        sidebarCollapsed
          ? undefined
          : { "--sidebar-w": `${sidebarWidth}px` }
      }
    >
      <WorkspaceSyncBanner />
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
        logoVersion={logoVersions[client] || 0}
        onPatchStepStatus={patchStepStatus}
        stepStatusOverrides={stepStatusOverrides}
        run={run}
        refreshRun={refreshRun}
        onSignOut={handleSignOut}
        authUsername={user?.username}
      />
      <main className="layout-main">
        <Suspense fallback={<ViewFallback />}>
        {!runId && workspaceView === "artifacts" ? (
          <ClientHome
            client={client}
            onClientDeleted={handleClientDeleted}
            artifactFilename={artifactFilename}
            onArtifactFilenameChange={setArtifactFilename}
          />
        ) : !runId && workspaceView === "matrix" ? (
          <StepMatrixScreen
            client={client}
            onOpenRun={openRun}
            onClientDeleted={handleClientDeleted}
            onBackToBoard={() => {
              setWorkspaceView("overview");
              pushAppPath({
                clientId: clientIdOf(client),
                view: "overview",
              });
            }}
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
            onClientDeleted={handleClientDeleted}
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
            run={run}
            refreshRun={refreshRun}
            onBack={() => {
              closeRun();
            }}
          />
        )}
        </Suspense>
      </main>
    </div>
  );
}

export default function AppWithToast() {
  return (
    <ToastProvider>
      <AuthProvider>
        <App />
      </AuthProvider>
    </ToastProvider>
  );
}
