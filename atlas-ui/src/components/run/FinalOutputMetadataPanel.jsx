import { useMemo } from "react";
import { buildFinalOutputMetadata } from "../../utils/articleMetadata";
import { charCountStatus } from "../../utils/parseMetaSeo";
import { wordCountBounds } from "../../utils/textStats";
import "./FinalOutputMetadataPanel.css";

const TITLE_RANGE = [50, 60];
const DESC_RANGE = [120, 155];

function StatCard({ label, value, hint }) {
  return (
    <div className="fod-meta-stat">
      <dt className="fod-meta-stat-label">{label}</dt>
      <dd className="fod-meta-stat-value">{value}</dd>
      {hint ? <p className="fod-meta-stat-hint">{hint}</p> : null}
    </div>
  );
}

function MetaOptionBlock({ label, option, range, recommended }) {
  if (!option) {
    return (
      <div className="fod-meta-option fod-meta-option--empty">
        <div className="fod-meta-option-label">{label}</div>
        <p className="fod-meta-option-empty">
          Run the <strong>Meta title &amp; description</strong> step to populate
          this.
        </p>
      </div>
    );
  }
  const status = charCountStatus(option.charCount, range[0], range[1]);
  return (
    <div
      className={`fod-meta-option${recommended ? " fod-meta-option--rec" : ""}`}
    >
      <div className="fod-meta-option-head">
        <span className="fod-meta-option-label">{label}</span>
        {recommended ? (
          <span className="fod-meta-option-tag">Recommended</span>
        ) : (
          <span className="fod-meta-option-tag fod-meta-option-tag--muted">
            Option {option.index}
          </span>
        )}
        <span className={`fod-meta-char fod-meta-char--${status}`}>
          {option.charCount} chars
        </span>
      </div>
      <p className="fod-meta-option-text">{option.text}</p>
    </div>
  );
}

export default function FinalOutputMetadataPanel({
  articleMarkdown = "",
  metaSeoText = "",
  targetWordCount = null,
}) {
  const data = useMemo(
    () =>
      buildFinalOutputMetadata(articleMarkdown, metaSeoText, {
        targetWordCount,
      }),
    [articleMarkdown, metaSeoText, targetWordCount]
  );

  const wordBounds = data.targetWordCount
    ? wordCountBounds(data.targetWordCount)
    : null;
  const wordHint = wordBounds
    ? `${wordBounds[0].toLocaleString()} to ${wordBounds[1].toLocaleString()} · entered ${data.targetWordCount.toLocaleString()} · body only, FAQ excluded`
    : "Body only — FAQ section excluded";

  return (
    <div className="fod-meta-panel" aria-label="Article metadata summary">
      <section className="fod-meta-section">
        <h3 className="fod-meta-section-title">Content stats</h3>
        <dl className="fod-meta-stats-grid">
          <StatCard
            label="Word count"
            value={
              wordBounds
                ? `${data.bodyStats.words.toLocaleString()} / ${wordBounds[0].toLocaleString()}–${wordBounds[1].toLocaleString()}`
                : data.bodyStats.words.toLocaleString()
            }
            hint={wordHint}
          />
          <StatCard
            label="Reading time"
            value={
              data.bodyStats.readingMinutes
                ? `~${data.bodyStats.readingMinutes} min`
                : "—"
            }
            hint="≈225 words/min"
          />
          <StatCard
            label="Characters"
            value={data.bodyStats.chars.toLocaleString()}
          />
          <StatCard label="H2 sections" value={String(data.h2Count)} />
          <StatCard
            label="FAQ questions"
            value={String(data.faqCount)}
            hint={data.faqCount < 2 ? "Need 2+ for JSON-LD" : "Used for FAQPage JSON-LD"}
          />
          <StatCard
            label="Internal links"
            value={String(data.links.internal)}
          />
          <StatCard
            label="External links"
            value={String(data.links.external)}
          />
          <StatCard
            label="Paragraphs"
            value={String(data.bodyStats.paragraphs)}
          />
        </dl>
      </section>

      <section className="fod-meta-section">
        <h3 className="fod-meta-section-title">Meta SEO</h3>
        {(data.pageType || data.keyword) && (
          <div className="fod-meta-context">
            {data.pageType ? (
              <div>
                <span className="fod-meta-context-label">Page type</span>
                <span className="fod-meta-context-value">{data.pageType}</span>
              </div>
            ) : null}
            {data.keyword ? (
              <div>
                <span className="fod-meta-context-label">Target keyword</span>
                <span className="fod-meta-context-value">{data.keyword}</span>
              </div>
            ) : null}
          </div>
        )}

        <div className="fod-meta-seo-stack">
          <MetaOptionBlock
            label="Meta title"
            option={data.recommendedTitle}
            range={TITLE_RANGE}
            recommended
          />
          {data.titleOptions.slice(1, 3).map((opt) => (
            <MetaOptionBlock
              key={`t-${opt.index}`}
              label="Meta title"
              option={opt}
              range={TITLE_RANGE}
              recommended={false}
            />
          ))}
          <MetaOptionBlock
            label="Meta description"
            option={data.recommendedDescription}
            range={DESC_RANGE}
            recommended
          />
          {data.descriptionOptions.slice(1, 3).map((opt) => (
            <MetaOptionBlock
              key={`d-${opt.index}`}
              label="Meta description"
              option={opt}
              range={DESC_RANGE}
              recommended={false}
            />
          ))}
        </div>
      </section>
    </div>
  );
}
