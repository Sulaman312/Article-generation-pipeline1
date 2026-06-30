import { parseDelimitedFields } from "./parseDelimitedFields";

const START = "---TOPIC CARD START---";
const END = "---TOPIC CARD END---";

/**
 * Parse topic card body into { key, label, value } rows.
 * Returns null if delimiters or fields are missing.
 */
export function parseTopicCard(text) {
  return parseDelimitedFields(text, START, END);
}

export function isTopicCardFormat(text) {
  return (
    typeof text === "string" &&
    text.includes(START) &&
    text.includes(END)
  );
}
