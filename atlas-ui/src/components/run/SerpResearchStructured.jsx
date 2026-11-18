import { useMemo } from "react";
import { parseSerpResearch } from "../../utils/parseResearch";
import FormattedFieldText from "../shared/FormattedFieldText";
import SectionCards from "./SectionCards";
import "./SectionCards.css";

const PIN_RE =
  /^(citable sources|related questions|sources|citations)(?:\s|\(|$)/i;

function splitPinned(sections) {
  const pinned = [];
  const rest = [];
  for (const sec of sections) {
    if (sec.heading && PIN_RE.test(sec.heading.trim())) pinned.push(sec);
    else rest.push(sec);
  }
  return { pinned, rest };
}

export default function SerpResearchStructured({ text }) {
  const data = useMemo(() => parseSerpResearch(text), [text]);
  if (!data?.sections?.length) return null;

  const { pinned, rest } = splitPinned(data.sections);

  return (
    <div className="serp-research-structured">
      {pinned.length ? (
        <div className="serp-pinned" aria-label="Pinned research links">
          {pinned.map((sec, i) => (
            <section key={`pin-${sec.heading}-${i}`} className="serp-pinned-card">
              <h3 className="serp-pinned-title">{sec.heading}</h3>
              <div className="serp-pinned-body">
                <FormattedFieldText text={sec.body} />
              </div>
            </section>
          ))}
        </div>
      ) : null}
      {rest.length ? <SectionCards sections={rest} /> : null}
      {!pinned.length && !rest.length ? (
        <SectionCards sections={data.sections} />
      ) : null}
    </div>
  );
}
