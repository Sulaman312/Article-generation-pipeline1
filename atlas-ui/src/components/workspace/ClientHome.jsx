import { lazy, Suspense, useState } from "react";
import { useToast } from "../../context/ToastContext";
import {
  WorkspaceArtifactEditorPage,
  WorkspaceArtifactPicker,
} from "./WorkspaceArtifacts";
import DeleteWorkspaceButton from "../shared/DeleteWorkspaceButton";
import PageHeader from "../shared/PageHeader";

const ContextDrawer = lazy(() => import("./ContextDrawer"));
const ContextEditorDrawer = lazy(() => import("./ContextEditorDrawer"));

/** Artifacts workspace view (+ optional context drawers). */
export default function ClientHome({
  client,
  onClientDeleted,
  artifactFilename = null,
  onArtifactFilenameChange,
}) {
  const { toast } = useToast();
  const [contextOpen, setContextOpen] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [artifactSpecs, setArtifactSpecs] = useState([]);

  const artifactSpec = artifactFilename
    ? artifactSpecs.find((s) => s.filename === artifactFilename)
    : null;

  return (
    <div className="page">
      <PageHeader
        title={artifactSpec ? artifactSpec.title : "Artifacts"}
        actions={
          <>
            {onClientDeleted ? (
              <DeleteWorkspaceButton
                client={client}
                onDeleted={onClientDeleted}
              />
            ) : null}
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
        }
      />

      {artifactSpec ? (
        <WorkspaceArtifactEditorPage
          client={client}
          filename={artifactFilename}
          spec={artifactSpec}
          toast={toast}
          onBack={() => onArtifactFilenameChange?.(null)}
        />
      ) : (
        <section
          className="artifacts-picker-section"
          aria-label="Workspace artifacts"
        >
          <WorkspaceArtifactPicker
            client={client}
            onSelect={(filename) => onArtifactFilenameChange?.(filename)}
            onSpecsChange={setArtifactSpecs}
          />
        </section>
      )}

      <Suspense fallback={null}>
        {contextOpen ? (
          <ContextDrawer
            client={client}
            open={contextOpen}
            onClose={() => setContextOpen(false)}
          />
        ) : null}
        {editorOpen ? (
          <ContextEditorDrawer
            client={client}
            open={editorOpen}
            onClose={() => setEditorOpen(false)}
          />
        ) : null}
      </Suspense>
    </div>
  );
}
