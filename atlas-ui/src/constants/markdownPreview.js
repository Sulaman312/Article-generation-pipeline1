/** Shared markdown preview class for all article pipeline step artifacts. */
export const PIPELINE_MARKDOWN_CLASS = "md md--artifact md--pipeline-step";

export const EDITOR_FACT_CHECK_MARKER =
  "---EDITOR FACT-CHECK (Claude — publishable block follows)---";
const FACT_CHECK_START = "---FACT CHECK START---";
const FACT_CHECK_END = "---FACT CHECK END---";

const PIPELINE_BOILERPLATE_DELIMITER =
  /^---(?:SERP RESEARCH(?:\s*\([^)]+\))?|SERP ANALYSIS(?:\s*&\s*(?:GAPS|RESEARCH))?(?:\s*\(STEP[^)]+\))?|SERP ANALYSIS START|SERP ANALYSIS END|FACT CHECK REPORT START|FACT CHECK REPORT END|CORRECTED ARTICLE START|CORRECTED ARTICLE END|PUBLISHING METADATA START|PUBLISHING METADATA END|PERPLEXITY WEB FACT-CHECK[^-]*|DRAFT FACT-CHECK SCAN[^-]*|EDITOR FACT-CHECK[^-]*|MAIN RESPONSE|RESPONSE|CITATION URLS[^-]*|RELATED QUESTIONS[^-]*|PASTE PERPLEXITY[^-]*|SERP RESEARCH LAYER)---\s*$/gim;

const SERP_PREAMBLE_TITLE =
  /^(?:#{1,3}\s+|\*\*)?SERP[- ]Oriented Research Summary\s*:[^\n]*\n+/im;

const FACTCHECK_PREAMBLE_TITLE =
  /^(?:#{1,3}\s+|\*\*)?Web[- ]Grounded Fact[- ]Check Scan\s*:[^\n]*\n+/im;

const REDUNDANT_FIELD_LABEL = /^SERP SNAPSHOT:\s*\n?/gim;

/** Fact-check artifacts store Perplexity raw + editor output; preview shows editor only. */
export function extractFactCheckEditorBlock(text) {
  const raw = String(text || "");
  const fcStart = raw.indexOf(FACT_CHECK_START);
  const fcEnd = raw.indexOf(FACT_CHECK_END);
  if (fcStart !== -1 && fcEnd !== -1 && fcEnd > fcStart) {
    return raw.slice(fcStart + FACT_CHECK_START.length, fcEnd).trim();
  }
  const idx = raw.indexOf(EDITOR_FACT_CHECK_MARKER);
  if (idx === -1) return raw;
  return raw.slice(idx + EDITOR_FACT_CHECK_MARKER.length).trim();
}

/** Normalize pipeline artifact text before markdown parsing. */
export function normalizePipelineMarkdown(text) {
  return String(text || "")
    .replace(/^\uFEFF/, "")
    .replace(/\r\n/g, "\n")
    .replace(/[：﹕]/g, ":")
    .replace(/^(MODEL|VERSION|STATUS):\s*[^\n]*\n?/gim, "")
    .replace(PIPELINE_BOILERPLATE_DELIMITER, "")
    .replace(SERP_PREAMBLE_TITLE, "")
    .replace(FACTCHECK_PREAMBLE_TITLE, "")
    .replace(REDUNDANT_FIELD_LABEL, "")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/^(---[^\n]+---)\n(?!\n)/gm, "$1\n\n")
    .replace(/^(H\s*[1-6]\s*:.*)\n(?!\n)/gim, "$1\n\n")
    .trim();
}

/** Step-aware display normalization (preview only; raw artifact unchanged). */
export function normalizeStepArtifactMarkdown(text, stepKey) {
  let out = String(text || "");
  if (stepKey === "fact_check") {
    out = extractFactCheckEditorBlock(out);
  }
  return normalizePipelineMarkdown(out);
}
