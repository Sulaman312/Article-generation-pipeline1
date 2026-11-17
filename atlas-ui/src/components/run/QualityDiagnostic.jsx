import { useEffect, useState } from "react";
import { getQualityDiagnostic } from "../../services/api";

export default function QualityDiagnostic({ client, runId, stepName, showEmpty = false }) {
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    setReport(null);
    setError("");
    getQualityDiagnostic(client, runId, stepName)
      .then(value => { if (!cancelled) setReport(value); })
      .catch(e => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [client, runId, stepName]);
  if (error) return <p role="alert">Could not load quality diagnostics: {error}</p>;
  if (!report) return <p>Loading quality diagnostics…</p>;
  if (!showEmpty && !report.content && !(report.issues || []).length) return null;
  const terms = [...new Set((report.issues || []).map(i => i.term).filter(Boolean))];
  // React renders strings as text; rejected model output is never injected as HTML.
  const escaped = terms.sort((a, b) => b.length - a.length)
    .map(term => term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const pattern = escaped.length ? new RegExp(`(${escaped.join("|")})`, "gi") : null;
  const text = report.content || "";
  const pieces = pattern ? text.split(pattern) : [text];
  return (
    <section className="run-artifact-card" aria-label="Quality diagnostics">
      <div className="run-artifact-body">
        <p>{report.kind === "rejected"
          ? "This output failed the French check and is saved for review. Re-run this step after correcting the reported terms."
          : "French preflight findings (templates and inputs)."}</p>
        {report.message && <p role="alert" style={{ whiteSpace: "pre-wrap" }}>{report.message}</p>}
        {(report.issues || []).length > 0 && <ul>{report.issues.map((issue, index) => (
          <li key={index}>{issue.source ? `${issue.source}: ` : ""}{issue.term}
            {issue.suggestion ? ` → ${issue.suggestion}` : ""} ({issue.severity})</li>
        ))}</ul>}
        {text && <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
          {pieces.map((piece, i) => i % 2 ? <mark key={i}>{piece}</mark> : piece)}
        </pre>}
        {!text && !(report.issues || []).length && <p>No saved quality findings for this step.</p>}
      </div>
    </section>
  );
}
