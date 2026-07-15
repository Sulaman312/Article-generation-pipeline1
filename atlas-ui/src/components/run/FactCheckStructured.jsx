import { useMemo, useState } from "react";
import {
  extractFactCheckEditorBlock,
  PIPELINE_MARKDOWN_CLASS,
} from "../../constants/markdownPreview";
import { parseFactCheckReport } from "../../utils/parseFactCheck";
import Markdown from "../shared/Markdown";
import "./FactCheckStructured.css";

function assessmentTone(value) {
  const v = String(value || "").toUpperCase();
  if (v.includes("CLEAN")) return "clean";
  if (v.includes("SIGNIFICANT")) return "significant";
  if (v.includes("MINOR")) return "minor";
  return "neutral";
}

function actionTone(value) {
  const v = String(value || "").toLowerCase();
  if (v.includes("flagged")) return "flagged";
  if (v.includes("removed")) return "removed";
  if (v.includes("corrected")) return "corrected";
  return "neutral";
}

function IssueCard({ issue }) {
  return (
    <article className="fact-check-issue">
      <header className="fact-check-issue-head">
        <span className="fact-check-issue-num">Issue {issue.number}</span>
        {issue.issueType ? (
          <span className="fact-check-issue-type">{issue.issueType}</span>
        ) : null}
        {issue.actionTaken ? (
          <span
            className={`fact-check-issue-action fact-check-issue-action--${actionTone(
              issue.actionTaken
            )}`}
          >
            {issue.actionTaken}
          </span>
        ) : null}
      </header>

      {issue.location ? (
        <blockquote className="fact-check-quote">{issue.location}</blockquote>
      ) : null}

      {issue.correctionOrFlag ? (
        <div className="fact-check-issue-note">
          <div className="fact-check-issue-note-label">Correction / note</div>
          <p className="fact-check-issue-note-body">{issue.correctionOrFlag}</p>
        </div>
      ) : null}
    </article>
  );
}

function ReportPanel({ data, totalLabel, tone }) {
  return (
    <>
      {data.hasReport ? (
        <section className="fact-check-summary" aria-label="Fact check summary">
          <div className={`fact-check-badge fact-check-badge--${tone}`}>
            {data.overallAssessment || "Fact check"}
          </div>
          <div className="fact-check-summary-meta">
            <span className="fact-check-summary-count">
              {totalLabel} issue{totalLabel === "1" ? "" : "s"}
            </span>
          </div>
        </section>
      ) : null}

      {data.hasReport ? (
        <section className="fact-check-issues" aria-label="Issues">
          <h3 className="fact-check-section-title">Issues found</h3>
          {data.noIssues && !data.issues.length ? (
            <p className="fact-check-empty">No factual issues identified.</p>
          ) : (
            <div className="fact-check-issue-list">
              {data.issues.map((issue) => (
                <IssueCard key={issue.number} issue={issue} />
              ))}
            </div>
          )}
        </section>
      ) : null}

      {data.humanReview ? (
        <section className="fact-check-aside">
          <h3 className="fact-check-section-title">Flagged for human review</h3>
          <pre className="fact-check-aside-body">{data.humanReview}</pre>
        </section>
      ) : null}

      {data.companyClaimReview ? (
        <section className="fact-check-aside">
          <h3 className="fact-check-section-title">Company claim review</h3>
          <pre className="fact-check-aside-body">{data.companyClaimReview}</pre>
        </section>
      ) : null}
    </>
  );
}

export default function FactCheckStructured({ text }) {
  const data = useMemo(() => {
    const editor = extractFactCheckEditorBlock(text);
    return parseFactCheckReport(editor || text);
  }, [text]);

  const hasReport = Boolean(data?.hasReport);
  const hasArticle = Boolean(data?.correctedArticle);
  const [tab, setTab] = useState(() =>
    hasReport ? "report" : "article"
  );

  if (!data) return null;

  const tone = assessmentTone(data.overallAssessment);
  const totalLabel =
    data.totalIssues !== ""
      ? data.totalIssues
      : String(data.issues.length);

  const showTabs = hasReport && hasArticle;
  const active = showTabs
    ? tab
    : hasReport
      ? "report"
      : "article";

  return (
    <div className="fact-check-structured">
      {showTabs ? (
        <div className="fact-check-tabs" role="tablist" aria-label="Fact check">
          <button
            type="button"
            role="tab"
            aria-selected={active === "report"}
            className={`fact-check-tab${active === "report" ? " is-active" : ""}`}
            onClick={() => setTab("report")}
          >
            Report
            <span className="fact-check-tab-count">{totalLabel}</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={active === "article"}
            className={`fact-check-tab${active === "article" ? " is-active" : ""}`}
            onClick={() => setTab("article")}
          >
            Corrected article
          </button>
        </div>
      ) : null}

      {active === "report" ? (
        <ReportPanel data={data} totalLabel={totalLabel} tone={tone} />
      ) : null}

      {active === "article" && hasArticle ? (
        <section className="fact-check-article" aria-label="Corrected article">
          {!showTabs ? (
            <h3 className="fact-check-section-title">Corrected article</h3>
          ) : null}
          <Markdown
            text={data.correctedArticle}
            className={PIPELINE_MARKDOWN_CLASS}
          />
        </section>
      ) : null}
    </div>
  );
}
