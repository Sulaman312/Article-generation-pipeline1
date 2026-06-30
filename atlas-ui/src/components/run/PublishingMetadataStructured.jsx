import { useMemo } from "react";
import FormattedFieldText from "../shared/FormattedFieldText";
import { parsePublishingMetadata } from "../../utils/parseFinalOutput";
import "./PublishingMetadataStructured.css";

function seoStatusClass(value) {
  const v = String(value || "").toUpperCase();
  if (v.startsWith("PASS")) return "meta-pill--pass";
  if (v.startsWith("FIXED")) return "meta-pill--fixed";
  if (v.startsWith("NOTE")) return "meta-pill--note";
  return "meta-pill--neutral";
}

function SeoStatusPill({ value, compact = false }) {
  const raw = String(value || "").trim();
  if (!raw) return <span className="meta-pill meta-pill--neutral">—</span>;
  const head = raw.split(/\s/)[0].toUpperCase();
  const label =
    head === "PASS"
      ? "Pass"
      : head === "FIXED"
        ? "Fixed"
        : head === "NOTE"
          ? "Note"
          : head;
  return (
    <span
      className={`meta-pill ${seoStatusClass(raw)}${compact ? " meta-pill--compact" : ""}`}
      title={raw}
    >
      {label}
    </span>
  );
}

function getField(fields, key) {
  return fields.find((f) => f.key === key);
}

export default function PublishingMetadataStructured({ text, fields: fieldsProp }) {
  const fields = fieldsProp ?? parsePublishingMetadata(text);
  const grouped = useMemo(() => {
    if (!fields?.length) return null;
    const seo = getField(fields, "SEO CHECK RESULTS");
    const status = getField(fields, "STATUS");
    const cms = fields.filter(
      (f) => f.key !== "SEO CHECK RESULTS" && f.key !== "STATUS"
    );
    return { cms, seo, status };
  }, [fields]);

  if (!grouped) return null;

  return (
    <div className="meta-panel" aria-label="Publishing metadata">
      {grouped.status ? (
        <div className="meta-panel-status-row">
          <span className="meta-status-ready">{grouped.status.value}</span>
        </div>
      ) : null}

      {grouped.cms.length > 0 ? (
        <section className="meta-panel-section">
          <h3 className="meta-panel-section-title">CMS fields</h3>
          <dl className="meta-cms-grid">
            {grouped.cms.map((field) => (
              <div className="meta-cms-item" key={field.key}>
                <dt>{field.label}</dt>
                <dd>
                  <FormattedFieldText text={field.value} />
                </dd>
              </div>
            ))}
          </dl>
        </section>
      ) : null}

      {grouped.seo?.children?.length ? (
        <section className="meta-panel-section">
          <h3 className="meta-panel-section-title">SEO checklist</h3>
          <ul className="meta-seo-compact-list">
            {grouped.seo.children.map((row) => (
              <li className="meta-seo-compact-item" key={row.key}>
                <span className="meta-seo-compact-label">{row.label}</span>
                <SeoStatusPill value={row.value} compact />
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
