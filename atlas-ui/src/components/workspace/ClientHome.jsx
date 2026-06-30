import { useEffect, useState } from "react";
import * as api from "../../services/api";
import { useToast } from "../../context/ToastContext";
import { PIPELINE_STEP_KEYS as STEP_ORDER } from "../../constants/pipeline";
import ContextDrawer from "./ContextDrawer";
import ContextEditorDrawer from "./ContextEditorDrawer";
import {
  WorkspaceArtifactEditorPage,
  WorkspaceArtifactPicker,
} from "./WorkspaceArtifacts";
import DeleteWorkspaceButton from "../shared/DeleteWorkspaceButton";
import ManualArticleForm from "./ManualArticleForm";
import PageHeader from "../shared/PageHeader";

export default function ClientHome({
  client,
  onOpenRun,
  onClientDeleted,
  workspaceView = "overview",
  artifactFilename = null,
  onArtifactFilenameChange,
}) {
  const { toast } = useToast();
  const [runs, setRuns] = useState([]);
  const [loadingRuns, setLoadingRuns] = useState(true);
  const [error, setError] = useState(null);
  const [contextOpen, setContextOpen] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [artifactSpecs, setArtifactSpecs] = useState([]);

  async function loadRuns() {
    setLoadingRuns(true);
    try {
      const list = await api.getRuns(client);
      setRuns(list);
    } catch (e) {
      setError(e?.message || String(e));
    } finally {
      setLoadingRuns(false);
    }
  }

  useEffect(() => {
    loadRuns();
  }, [client]);

  const isOverview = workspaceView === "overview";
  const isArtifacts = workspaceView === "artifacts";
  const artifactSpec = artifactFilename
    ? artifactSpecs.find((s) => s.filename === artifactFilename)
    : null;

  return (
    <div className="page">
      <PageHeader
        title={
          isOverview ? client : artifactSpec ? artifactSpec.title : "Artifacts"
        }
        actions={
          <>
            {onClientDeleted ? (
              <DeleteWorkspaceButton
                client={client}
                onDeleted={onClientDeleted}
              />
            ) : null}
            {isOverview ? (
            <>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setContextOpen(true)}
              >
                Context
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setEditorOpen(true)}
              >
                Edit files
              </button>
            </>
            ) : null}
          </>
        }
      />

      {isArtifacts && artifactSpec ? (
        <WorkspaceArtifactEditorPage
          client={client}
          filename={artifactFilename}
          spec={artifactSpec}
          toast={toast}
          onBack={() => onArtifactFilenameChange?.(null)}
        />
      ) : null}

      {isArtifacts && !artifactSpec ? (
        <section
          className="artifacts-picker-section"
          aria-label="Workspace artifacts"
        >
          <WorkspaceArtifactPicker
            client={client}
            onSelect={(fn) => onArtifactFilenameChange?.(fn)}
            onSpecsChange={setArtifactSpecs}
          />
        </section>
      ) : null}

      {isOverview ? (
        <section style={{ marginBottom: 32 }} aria-label="New article">
          <ManualArticleForm
            client={client}
            onOpenRun={onOpenRun}
            onCreated={loadRuns}
          />
        </section>
      ) : null}

      {isOverview ? (
        <>
          <div
            style={{
              display: "flex",
              alignItems: "baseline",
              justifyContent: "space-between",
              marginBottom: 14,
            }}
          >
            <h2 className="h2">Recent runs</h2>
            <span style={{ fontSize: 13, color: "var(--text-muted)" }}>
              {runs.length} total
            </span>
          </div>

          {loadingRuns ? (
            <div className="empty-state">
              <span className="spinner" /> &nbsp; loading runs…
            </div>
          ) : runs.length === 0 ? (
            <div
              className="empty-state"
              style={{
                background: "var(--panel)",
                borderRadius: 12,
                border: "1px dashed var(--border-strong)",
              }}
            >
              No runs yet. Create one above to get started.
            </div>
          ) : (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))",
                gap: 14,
              }}
            >
              {runs.map((r) => (
                <RunCard
                  key={r.run_id}
                  run={r}
                  onOpen={() => onOpenRun(r.run_id)}
                />
              ))}
            </div>
          )}
        </>
      ) : null}

      <ContextDrawer
        client={client}
        open={contextOpen}
        onClose={() => setContextOpen(false)}
      />
      <ContextEditorDrawer
        client={client}
        open={editorOpen}
        onClose={() => setEditorOpen(false)}
      />
    </div>
  );
}

function RunCard({ run, onOpen }) {
  return (
    <div className="card run-card" onClick={onOpen}>
      <div className="run-card-title">{run.topic || "(untitled)"}</div>
    </div>
  );
}
