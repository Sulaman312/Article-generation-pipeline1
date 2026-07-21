import { useMemo } from "react";
import {
  parseOutlineStructured,
  summarizeOutlineWordBudgets,
} from "../../utils/parseOutlineStructured";
import FormattedFieldText from "../shared/FormattedFieldText";
import "./SectionCards.css";

const FIELD_ORDER = [
  "PURPOSE",
  "KEY POINTS",
  "PROOF POINT SLOT",
  "EXTERNAL CITE SLOT",
  "IMAGE SLOT",
  "FORMAT",
  "WORD COUNT",
  "QUESTIONS TO ANSWER",
];

const FIELD_LABELS = {
  PURPOSE: "Purpose",
  "KEY POINTS": "Key points",
  "PROOF POINT SLOT": "Proof point",
  "EXTERNAL CITE SLOT": "External cite",
  "IMAGE SLOT": "Image slot",
  FORMAT: "Format",
  "WORD COUNT": "Word count",
  "QUESTIONS TO ANSWER": "Questions",
};

function NoteBlock({ label, text }) {
  if (!text) return null;
  return (
    <div className="outline-note">
      <div className="outline-note-label">{label}</div>
      <FormattedFieldText text={text} />
    </div>
  );
}

function budgetMessage(budget) {
  if (!budget) return null;
  if (budget.missingTitles.length) {
    const names = budget.missingTitles.slice(0, 3).join(", ");
    const more =
      budget.missingTitles.length > 3
        ? ` (+${budget.missingTitles.length - 3} more)`
        : "";
    return {
      ok: false,
      text: `Missing WORD COUNT on: ${names}${more}.`,
    };
  }
  if (budget.targetMid != null && budget.sumMid > 0) {
    const abs = Math.abs(budget.delta);
    if (abs <= 150) {
      return {
        ok: true,
        text: `Section budgets ≈ ${budget.sumMid.toLocaleString()} words (target ${budget.targetMid.toLocaleString()}).`,
      };
    }
    const dir = budget.delta > 0 ? "over" : "under";
    return {
      ok: false,
      text: `Section budgets ≈ ${budget.sumMid.toLocaleString()} words — about ${abs.toLocaleString()} ${dir} the ${budget.targetMid.toLocaleString()}-word target.`,
    };
  }
  if (budget.sumMid > 0) {
    return {
      ok: true,
      text: `Section budgets ≈ ${budget.sumMid.toLocaleString()} words.`,
    };
  }
  return null;
}

export default function OutlineStructured({ text }) {
  const data = useMemo(() => parseOutlineStructured(text), [text]);
  const budget = useMemo(
    () => (data ? summarizeOutlineWordBudgets(data) : null),
    [data]
  );
  const warning = budgetMessage(budget);

  if (!data) return null;

  const missingSet = new Set(budget?.missingTitles || []);

  return (
    <div className="outline-structured">
      {data.h1 ? (
        <header className="outline-hero">
          <div className="outline-hero-label">Title (H1)</div>
          <h2 className="outline-hero-title">{data.h1}</h2>
          <div className="outline-meta-row">
            {data.totalWords ? (
              <span className="outline-chip">Target: {data.totalWords}</span>
            ) : null}
            <span className="outline-chip">
              {data.sections.length} sections
            </span>
            {budget?.sumMid ? (
              <span className="outline-chip">
                Σ ~{budget.sumMid.toLocaleString()} words
              </span>
            ) : null}
          </div>
          {warning ? (
            <p
              className={`outline-warn${warning.ok ? " outline-warn--ok" : ""}`}
            >
              {warning.text}
            </p>
          ) : null}
        </header>
      ) : null}

      <NoteBlock label="Post-H1 lede" text={data.ledeNote} />
      <NoteBlock label="Intro note" text={data.introNote} />

      <div className="section-cards">
        {data.sections.map((sec, i) => (
          <section
            key={`${sec.title}-${i}`}
            className={`section-card${
              missingSet.has(sec.title) ? " section-card--missing-wc" : ""
            }`}
          >
            <h3 className="section-card-title">{sec.title}</h3>
            <div className="outline-section-fields">
              {FIELD_ORDER.map((key) => {
                const val = sec.fields[key];
                if (!val) return null;
                return (
                  <div className="outline-field" key={key}>
                    <span className="outline-field-label">
                      {FIELD_LABELS[key] || key}
                    </span>
                    <div className="outline-field-value">
                      <FormattedFieldText text={val} />
                    </div>
                  </div>
                );
              })}
            </div>
            {missingSet.has(sec.title) ? (
              <p className="section-card-missing">Missing WORD COUNT</p>
            ) : null}
          </section>
        ))}
      </div>

      <NoteBlock label="Conclusion note" text={data.conclusionNote} />
      <NoteBlock label="CTA note" text={data.ctaNote} />
      <NoteBlock label="Image plan" text={data.imagePlan} />
    </div>
  );
}
