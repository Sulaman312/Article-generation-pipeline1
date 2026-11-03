import { extractFaqPairs } from "./faqSchema";
import { parseMetaSeoStructured } from "./parseMetaSeo";
import { computeTextStats, markdownForWordCount } from "./textStats";

const MD_LINK = /\[([^\]]*)\]\(([^)\s]+)\)/g;

function classifyHref(href) {
  const h = String(href || "").trim();
  if (!h || h.startsWith("#") || h.startsWith("mailto:") || h.startsWith("tel:")) {
    return "other";
  }
  if (/^https?:\/\//i.test(h)) return "external";
  if (h.startsWith("/") || h.startsWith("./") || h.startsWith("../")) {
    return "internal";
  }
  // bare paths / relative slugs
  if (!/^[a-z][a-z0-9+.-]*:/i.test(h)) return "internal";
  return "other";
}

export function countMarkdownLinks(markdown) {
  const text = String(markdown || "");
  let internal = 0;
  let external = 0;
  let other = 0;
  MD_LINK.lastIndex = 0;
  let m;
  while ((m = MD_LINK.exec(text)) !== null) {
    const kind = classifyHref(m[2]);
    if (kind === "internal") internal += 1;
    else if (kind === "external") external += 1;
    else other += 1;
  }
  return { internal, external, other, total: internal + external + other };
}

export function countH2Sections(markdown) {
  return (String(markdown || "").match(/^##\s+\S+/gm) || []).length;
}

/**
 * Build the Metadata tab summary for Final Output.
 * @param {string} articleMarkdown - article body (no publishing-meta / schema wrappers required)
 * @param {string|null} metaSeoText - meta_seo step artifact
 * @param {{ targetWordCount?: number|null }} [opts]
 */
export function buildFinalOutputMetadata(
  articleMarkdown,
  metaSeoText = "",
  { targetWordCount = null } = {}
) {
  const article = String(articleMarkdown || "");
  const bodyStats = computeTextStats(article);
  const faqPairs = extractFaqPairs(article);
  const links = countMarkdownLinks(markdownForWordCount(article));
  const h2Count = countH2Sections(article);
  const meta = parseMetaSeoStructured(metaSeoText || "") || null;

  const titleOptions = meta?.titleOptions || [];
  const descriptionOptions = meta?.descriptionOptions || [];
  const recommendedTitle = titleOptions[0] || null;
  const recommendedDescription = descriptionOptions[0] || null;

  return {
    bodyStats,
    targetWordCount:
      Number(targetWordCount) > 0 ? Number(targetWordCount) : null,
    faqCount: faqPairs.length,
    links,
    h2Count,
    pageType: meta?.pageType || "",
    keyword: meta?.keyword || "",
    titleOptions,
    descriptionOptions,
    recommendedTitle,
    recommendedDescription,
    hasMetaSeo: Boolean(titleOptions.length || descriptionOptions.length),
  };
}
