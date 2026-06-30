import DeleteWorkspaceButton from "../shared/DeleteWorkspaceButton";
import PageHeader from "../shared/PageHeader";
import { APP_PROJECT_MODE } from "../../constants/appProject";
import "./WorkspaceDashboard.css";

function IconContent(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" aria-hidden {...props}>
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M14 2v6h6M16 13H8M16 17H8M10 9H8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

const PIPELINES = [
  {
    id: "content",
    title: "Content generation",
    description: "Long-form articles from topic to publish-ready draft.",
    icon: IconContent,
  },
  {
    id: "social",
    title: "Social media content",
    description: "IG, LinkedIn & Facebook post package — 4 style previews, compose, captions.",
    icon: IconContent,
  },
];

function visiblePipelines() {
  if (APP_PROJECT_MODE === "article") {
    return PIPELINES.filter((p) => p.id === "content");
  }
  if (APP_PROJECT_MODE === "social") {
    return PIPELINES.filter((p) => p.id === "social");
  }
  return PIPELINES;
}

function dashboardSubtitle() {
  if (APP_PROJECT_MODE === "social") {
    return "Open the social pipeline to start generating posts.";
  }
  return "Open the content pipeline to start generating articles.";
}

export default function WorkspaceDashboard({
  client,
  onSelectContent,
  onSelectSocial,
  onClientDeleted,
}) {
  const pipelines = visiblePipelines();

  return (
    <div className="ws-dash page">
      <header className="ws-dash-head">
        <PageHeader
          title="Pipelines"
          subtitle={dashboardSubtitle()}
        />
        {onClientDeleted ? (
          <DeleteWorkspaceButton client={client} onDeleted={onClientDeleted} />
        ) : null}
      </header>

      <section className="ws-dash-section" aria-label="Available pipelines">
        <div className="ws-dash-grid">
          {pipelines.map((pipe) => {
            const Icon = pipe.icon;
            return (
              <button
                key={pipe.id}
                type="button"
                className="ws-pipeline-card ws-pipeline-card--primary"
                onClick={() => {
                  if (pipe.id === "social") onSelectSocial?.();
                  else onSelectContent?.();
                }}
              >
                <PipelineCardInner pipe={pipe} Icon={Icon} />
                <span className="ws-pipeline-card-cta" aria-hidden>
                  Open →
                </span>
              </button>
            );
          })}
        </div>
      </section>
    </div>
  );
}

function PipelineCardInner({ pipe, Icon }) {
  return (
    <>
      <div className="ws-pipeline-card-top">
        <span className="ws-pipeline-card-icon" aria-hidden>
          <Icon />
        </span>
        <span className="ws-pipeline-card-badge ws-pipeline-card-badge--active">
          Active
        </span>
      </div>
      <h3 className="ws-pipeline-card-title">{pipe.title}</h3>
      <p className="ws-pipeline-card-body">{pipe.description}</p>
    </>
  );
}
