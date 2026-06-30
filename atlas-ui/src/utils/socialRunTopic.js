/** Stubs — article-only service has no social runs. */
export function isSocialPipeline() {
  return false;
}

export function socialAdditionalDetails() {
  return "";
}

export function socialPostParagraph() {
  return "";
}

export function socialRunTitle(_manual, topic) {
  return topic || "";
}

export function socialRunChromeLabel(_manual, topic) {
  return topic || "";
}
