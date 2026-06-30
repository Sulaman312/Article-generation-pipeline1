import DeleteWorkspaceButton from "../shared/DeleteWorkspaceButton";
import ManualArticleForm from "./ManualArticleForm";
import PageHeader from "../shared/PageHeader";
import "./ContentPipelineBoard.css";

export default function ContentPipelineBoard({
  client,
  onOpenRun,
  onClientDeleted,
}) {
  return (
    <div className="page cpb-page">
      <PageHeader
        title="New article"
        subtitle="Fill in the brief below to start a content pipeline run."
        actions={
          onClientDeleted ? (
            <DeleteWorkspaceButton
              client={client}
              onDeleted={onClientDeleted}
            />
          ) : null
        }
      />

      <section className="cpb-section" aria-label="New article">
        <ManualArticleForm client={client} onOpenRun={onOpenRun} />
      </section>
    </div>
  );
}
