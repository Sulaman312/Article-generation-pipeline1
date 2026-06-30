/** Shared markdown preview class for all article pipeline step artifacts. */
export const PIPELINE_MARKDOWN_CLASS = "md md--artifact md--pipeline-step";

/** Normalize pipeline artifact text before markdown parsing. */
export function normalizePipelineMarkdown(text) {
  return String(text || "")
    .replace(/^\uFEFF/, "")
    .replace(/\r\n/g, "\n")
    .replace(/[：﹕]/g, ":")
    .replace(/^(---[^\n]+---)\n(?!\n)/gm, "$1\n\n")
    .replace(/^(H\s*[1-6]\s*:.*)\n(?!\n)/gim, "$1\n\n");
}
