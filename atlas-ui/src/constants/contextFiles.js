/**
 * Fallback when `/context-files/catalog` is unreachable. Prefer catalog from the API
 * (`getContextFilesCatalog`) so filenames stay aligned with Flask `CONTEXT_FILES_CATALOG`.
 */
export const PIPELINE_CONTEXT_FILES_ORDERED = [
  "context.md",
  "personas.md",
  "brand_voice.md",
  "writing_guidelines.md",
  "cta_guidelines.md",
  "internal_links.md",
];

export const CONTEXT_FILE_LABELS = {
  "context.md": "Company / product context",
  "personas.md": "Audience personas",
  "brand_voice.md": "Brand voice",
  "writing_guidelines.md": "Writing guidelines",
  "cta_guidelines.md": "CTA guidelines",
  "internal_links.md": "Internal linking & clusters",
};
