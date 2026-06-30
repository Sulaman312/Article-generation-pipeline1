import { useState } from "react";

export default function FaqJsonLdPanel({ schemaScript }) {
  const [copied, setCopied] = useState(false);

  if (!schemaScript?.trim()) {
    return (
      <div className="jsonld-panel">
        <p className="jsonld-panel__lead">
          FAQPage JSON-LD is generated when the <strong>Article</strong> tab includes a{" "}
          <strong>Frequently Asked Questions</strong> section. Re-run <strong>Final output</strong>{" "}
          or refresh this step after the article is complete.
        </p>
      </div>
    );
  }

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(schemaScript);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2500);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="jsonld-panel">
      <p className="jsonld-panel__lead">
        Paste this into WordPress (Custom HTML block, Rank Math schema, or Insert Headers and
        Footers). It must match the FAQ questions shown in the <strong>Article</strong> tab.
      </p>
      <div className="jsonld-panel__code-wrap">
        <button type="button" className="jsonld-panel__copy" onClick={handleCopy}>
          {copied ? "Copied" : "Copy JSON-LD"}
        </button>
        <pre className="jsonld-panel__code">
          <code>{schemaScript}</code>
        </pre>
      </div>
    </div>
  );
}
