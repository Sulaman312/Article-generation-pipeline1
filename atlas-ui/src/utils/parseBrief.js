import { parseDelimitedFields } from "./parseDelimitedFields";

const START = "---BRIEF START---";
const END = "---BRIEF END---";

export function parseBrief(text) {
  return parseDelimitedFields(text, START, END);
}

export function isBriefFormat(text) {
  return Boolean(parseBrief(text)?.length);
}
