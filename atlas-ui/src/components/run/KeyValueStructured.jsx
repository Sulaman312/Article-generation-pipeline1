import FormattedFieldText from "../shared/FormattedFieldText";

/** Generic KEY: value grid — reuses topic-card field chrome. */
export default function KeyValueStructured({ fields, className = "" }) {
  if (!fields?.length) return null;

  return (
    <div className={`topic-card-structured ${className}`.trim()}>
      <div className="topic-card-structured-grid">
        {fields.map((row) => (
          <div className="topic-card-field" key={row.key}>
            <div className="topic-card-field-label">{row.label}</div>
            <div className="topic-card-field-value">
              <FormattedFieldText text={row.value} />
              {row.children?.length ? (
                <dl className="topic-card-subfields">
                  {row.children.map((child) => (
                    <div
                      className="topic-card-subfield"
                      key={`${row.key}-${child.key}`}
                    >
                      <dt className="topic-card-subfield-label">
                        {child.label}
                      </dt>
                      <dd className="topic-card-subfield-value">
                        <FormattedFieldText text={child.value} />
                      </dd>
                    </div>
                  ))}
                </dl>
              ) : null}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
