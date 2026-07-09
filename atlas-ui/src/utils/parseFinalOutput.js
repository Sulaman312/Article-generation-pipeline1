import { parseDelimitedFields } from "./parseDelimitedFields";

export const PUBLISHING_METADATA_START = "---PUBLISHING METADATA START---";
export const PUBLISHING_METADATA_END = "---PUBLISHING METADATA END---";
export const FINAL_OUTPUT_START = "---FINAL OUTPUT START---";
export const FINAL_OUTPUT_END = "---FINAL OUTPUT END---";
export const FINAL_ARTICLE_START = FINAL_OUTPUT_START;
export const FINAL_ARTICLE_END = FINAL_OUTPUT_END;
export const FAQ_SCHEMA_START = "---FAQ SCHEMA (JSON-LD) START---";
export const FAQ_SCHEMA_END = "---FAQ SCHEMA (JSON-LD) END---";

export function parsePublishingMetadata(text) {
  return parseDelimitedFields(
    text,
    PUBLISHING_METADATA_START,
    PUBLISHING_METADATA_END
  );
}

export function extractFaqSchemaScript(text) {
  if (typeof text !== "string") return "";
  const s = text.indexOf(FAQ_SCHEMA_START);
  const e = text.indexOf(FAQ_SCHEMA_END);
  if (s === -1 || e === -1 || e <= s) return "";
  return text.slice(s + FAQ_SCHEMA_START.length, e).trim();
}

export function stripPublishingMetadataBlock(text) {
  if (typeof text !== "string") return "";
  const start = text.indexOf(PUBLISHING_METADATA_START);
  const end = text.indexOf(PUBLISHING_METADATA_END);
  if (start === -1 || end === -1 || end <= start) return text;
  const before = text.slice(0, start).trimEnd();
  const after = text.slice(end + PUBLISHING_METADATA_END.length).trimStart();
  if (before && after) return `${before}\n\n${after}`.trim();
  return (before || after).trim();
}

export function extractFinalArticle(text) {
  if (typeof text !== "string") return "";
  const cleaned = stripPublishingMetadataBlock(text);
  const s = cleaned.indexOf(FINAL_ARTICLE_START);
  const e = cleaned.indexOf(FINAL_ARTICLE_END);
  if (s === -1 || e === -1 || e <= s) return cleaned.trim();
  let body = cleaned.slice(s + FINAL_ARTICLE_START.length, e);
  const schemaAt = body.indexOf(FAQ_SCHEMA_START);
  if (schemaAt !== -1) body = body.slice(0, schemaAt);
  return body.trim();
}

/** Split final-output artifact into article markdown (+ optional FAQ JSON-LD). */
export function splitFinalOutput(text) {
  const cleaned = stripPublishingMetadataBlock(text || "");
  const articleText = extractFinalArticle(cleaned);
  const faqSchemaScript = extractFaqSchemaScript(cleaned);
  const hasArticle = Boolean(articleText);
  const hasFaqSchema = Boolean(faqSchemaScript?.trim());

  return {
    metadataFields: [],
    articleText,
    faqSchemaScript,
    hasStructuredMeta: false,
    hasArticle,
    hasFaqSchema,
    displayMarkdown: hasArticle ? articleText : cleaned.trim(),
  };
}

export function isFinalOutputFormat(text) {
  return (
    typeof text === "string" &&
    (text.includes(FINAL_OUTPUT_START) ||
      text.includes(FINAL_ARTICLE_START) ||
      text.includes(PUBLISHING_METADATA_START))
  );
}
