import { useState } from "react";
import { useToast } from "../../context/ToastContext";
import {
  WorkspaceArtifactEditorPage,
  WorkspaceArtifactPicker,
} from "./WorkspaceArtifacts";
import DeleteWorkspaceButton from "../shared/DeleteWorkspaceButton";
import PageHeader from "../shared/PageHeader";

/** Artifacts workspace view. */
export default function ClientHome({
  client,
  onClientDeleted,
  artifactFilename = null,
  onArtifactFilenameChange,
}) {
  const { toast } = useToast();
  const [artifactSpecs, setArtifactSpecs] = useState([]);

  const artifactSpec = artifactFilename
    ? artifactSpecs.find((s) => s.filename === artifactFilename)
    : null;

  return (
    <div className="page">
      <PageHeader
        title={artifactSpec ? artifactSpec.title : "Artifacts"}
        actions={
          onClientDeleted ? (
            <DeleteWorkspaceButton
              client={client}
              onDeleted={onClientDeleted}
            />
          ) : null
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
    </div>
  );
}
