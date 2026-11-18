import FormattedFieldText from "../shared/FormattedFieldText";
import "./SectionCards.css";

export default function SectionCards({
  sections = [],
  renderExtra = null,
  emptyLabel = "No sections",
}) {
  if (!sections.length) {
    return <p className="section-cards-empty">{emptyLabel}</p>;
  }

  return (
    <div className="section-cards">
      {sections.map((sec, i) => (
        <section
          key={`${sec.heading || "preamble"}-${i}`}
          className="section-card"
        >
          {sec.heading ? (
            <h3 className="section-card-title">{sec.heading}</h3>
          ) : null}
          {sec.body ? (
            <div className="section-card-body">
              <FormattedFieldText text={sec.body} />
            </div>
          ) : null}
          {typeof renderExtra === "function" ? renderExtra(sec, i) : null}
        </section>
      ))}
    </div>
  );
}
