import { parseDelimitedFields } from "./parseDelimitedFields";

export const PUBLISHING_METADATA_START = "---PUBLISHING METADATA START---";
export const PUBLISHING_METADATA_END = "---PUBLISHING METADATA END---";
export const FINAL_ARTICLE_START = "---FINAL ARTICLE START---";
export const FINAL_ARTICLE_END = "---FINAL ARTICLE END---";
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

export function extractFinalArticle(text) {
  if (typeof text !== "string") return "";
  const s = text.indexOf(FINAL_ARTICLE_START);
  const e = text.indexOf(FINAL_ARTICLE_END);
  if (s === -1 || e === -1 || e <= s) return "";
  let body = text.slice(s + FINAL_ARTICLE_START.length, e);
  const schemaAt = body.indexOf(FAQ_SCHEMA_START);
  if (schemaAt !== -1) body = body.slice(0, schemaAt);
  return body.trim();
}

/** Split final-output artifact into structured metadata + article markdown. */
export function splitFinalOutput(text) {
  const metadataFields = parsePublishingMetadata(text);
  const articleText = extractFinalArticle(text);
  const faqSchemaScript = extractFaqSchemaScript(text);
  const hasStructuredMeta = Boolean(metadataFields?.length);
  const hasArticle = Boolean(articleText);
  const hasFaqSchema = Boolean(faqSchemaScript?.trim());

  let displayMarkdown = text || "";
  if (hasArticle) {
    displayMarkdown = articleText;
  } else if (hasStructuredMeta) {
    const metaEnd = text.indexOf(PUBLISHING_METADATA_END);
    if (metaEnd !== -1) {
      displayMarkdown = text.slice(metaEnd + PUBLISHING_METADATA_END.length).trim();
    }
  }

  return {
    metadataFields,
    articleText,
    faqSchemaScript,
    hasStructuredMeta,
    hasArticle,
    hasFaqSchema,
    displayMarkdown,
  };
}

export function isFinalOutputFormat(text) {
  return (
    typeof text === "string" &&
    text.includes(PUBLISHING_METADATA_START) &&
    text.includes(FINAL_ARTICLE_START)
  );
}
