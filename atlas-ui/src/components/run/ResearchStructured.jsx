import { useMemo } from "react";
import { parseResearch } from "../../utils/parseResearch";
import SectionCards from "./SectionCards";
import "./SectionCards.css";

function GapCards({ gaps }) {
  if (!gaps?.length) return null;
  return (
    <div className="gap-card-list">
      {gaps.map((g, i) => (
        <article key={i} className="gap-card">
          <h4 className="gap-card-name">{g.gap || `Gap ${i + 1}`}</h4>
          {g.why ? (
            <div className="gap-card-row">
              <span className="gap-card-label">Why it matters</span>
              <span className="gap-card-value">{g.why}</span>
            </div>
          ) : null}
          {g.how ? (
            <div className="gap-card-row">
              <span className="gap-card-label">How we win</span>
              <span className="gap-card-value">{g.how}</span>
            </div>
          ) : null}
        </article>
      ))}
    </div>
  );
}

export default function ResearchStructured({ text }) {
  const data = useMemo(() => parseResearch(text), [text]);
  if (!data?.sections?.length) return null;

  const sections = data.sections.map((sec) => ({
    heading: sec.heading,
    body: sec.gaps?.length ? sec.bodyWithoutGaps : sec.body,
    gaps: sec.gaps,
  }));

  return (
    <div className="research-structured">
      <SectionCards
        sections={sections}
        renderExtra={(sec) =>
          sec.gaps?.length ? <GapCards gaps={sec.gaps} /> : null
        }
      />
    </div>
  );
}
