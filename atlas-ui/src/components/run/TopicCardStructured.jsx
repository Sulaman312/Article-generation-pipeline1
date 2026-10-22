import FormattedFieldText from "../shared/FormattedFieldText";
import { parseTopicCard } from "../../utils/parseTopicCard";
import {
  displayTopicCardFieldValue,
  filterTopicCardFieldsForDisplay,
} from "../../utils/topicCardDisplay";

function TopicCardFieldValue({ row }) {
  const value = displayTopicCardFieldValue(row);
  return (
    <>
      <FormattedFieldText text={value} />
      {row.children?.length ? (
        <dl className="topic-card-subfields">
          {row.children.map((child) => (
            <div className="topic-card-subfield" key={`${row.key}-${child.key}`}>
              <dt className="topic-card-subfield-label">{child.label}</dt>
              <dd className="topic-card-subfield-value">
                <FormattedFieldText text={child.value} />
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
    </>
  );
}

export default function TopicCardStructured({ text, manualInputs = null }) {
  const parsed = parseTopicCard(text);
  const fields = filterTopicCardFieldsForDisplay(parsed, manualInputs);
  if (!fields?.length) return null;

  return (
    <div className="topic-card-structured">
      <div className="topic-card-structured-grid">
        {fields.map((row) => (
          <div className="topic-card-field" key={row.key}>
            <div className="topic-card-field-label">{row.label}</div>
            <div className="topic-card-field-value">
              <TopicCardFieldValue row={row} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
