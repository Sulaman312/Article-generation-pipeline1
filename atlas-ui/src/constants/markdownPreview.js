/** Shared markdown preview class for all article pipeline step artifacts. */
export const PIPELINE_MARKDOWN_CLASS = "md md--artifact md--pipeline-step";

export const EDITOR_FACT_CHECK_MARKER =
  "---EDITOR FACT-CHECK (Claude — publishable block follows)---";
const FACT_CHECK_START = "---FACT CHECK START---";
const FACT_CHECK_END = "---FACT CHECK END---";

/** Mirror of ``backend/step_markers.STEP_MARKER_LABELS`` for preview wrapping. */
export const STEP_MARKER_LABELS = {
  topic_card: "TOPIC CARD",
  serp_research: "SERP RESEARCH",
  research: "SERP ANALYSIS",
  assignment_brief: "BRIEF",
  outline: "OUTLINE",
  draft: "DRAFT",
  fact_check: "FACT CHECK",
  meta_seo: "META SEO",
  final_output: "FINAL OUTPUT",
};

const LEGACY_MARKER_ALIASES = {
  final_output: [["---FINAL ARTICLE START---", "---FINAL ARTICLE END---"]],
  research: [["---RESEARCH START---", "---RESEARCH END---"]],
};

/** Visible step boundary labels shown at the top/bottom of each pipeline artifact. */
export const STEP_BOUNDARY_LABEL =
  /^(?:TOPIC CARD|SERP RESEARCH|SERP ANALYSIS|RESEARCH|BRIEF|OUTLINE|DRAFT|FACT CHECK|META SEO|FINAL OUTPUT|FINAL ARTICLE)\s+(?:START|END)$/i;

export function isStepBoundaryMarker(label) {
  return STEP_BOUNDARY_LABEL.test(String(label || "").trim());
}

/**
 * Display label for step delimiters — title case with preserved acronyms,
 * matching major artifact headings (e.g. ``SERP Analysis Start``).
 */
export function formatStepBoundaryLabel(label) {
  const raw = String(label || "").trim().replace(/^-+|-+$/g, "").trim();
  const m = raw.match(/^(.+?)\s+(START|END)\s*$/i);
  if (!m) return titleCaseStepWords(raw);
  const edge = m[2].toUpperCase() === "START" ? "Start" : "End";
  return `${titleCaseStepWords(m[1])} ${edge}`;
}

const STEP_ACRONYMS = new Set(["SERP", "SEO", "FAQ", "API", "JSON", "META"]);

function titleCaseStepWords(text) {
  return String(text || "")
    .replace(/\s+/g, " ")
    .trim()
    .split(" ")
    .filter(Boolean)
    .map((word) => {
      const upper = word.toUpperCase();
      if (STEP_ACRONYMS.has(upper)) return upper;
      return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
    })
    .join(" ");
}

function stepMarkerPair(stepKey) {
  const label = STEP_MARKER_LABELS[stepKey];
  if (!label) return null;
  return [`---${label} START---`, `---${label} END---`];
}

function markerPairsForStep(stepKey) {
  const primary = stepMarkerPair(stepKey);
  if (!primary) return [];
  const pairs = [primary];
  for (const legacy of LEGACY_MARKER_ALIASES[stepKey] || []) {
    pairs.push(legacy);
  }
  return pairs;
}

export function hasStepBoundaryMarkers(text, stepKey) {
  const raw = String(text || "");
  for (const [start, end] of markerPairsForStep(stepKey)) {
    const s = raw.indexOf(start);
    const e = raw.indexOf(end);
    if (s !== -1 && e !== -1 && e > s) return true;
  }
  return false;
}

/** Preview-only: guarantee every step artifact shows START + END headings. */
export function ensureStepBoundaryMarkers(text, stepKey) {
  const pair = stepMarkerPair(stepKey);
  if (!pair) return String(text || "");
  const [start, end] = pair;
  const stripped = String(text || "").trim();
  if (!stripped) return "";
  if (hasStepBoundaryMarkers(stripped, stepKey)) {
    for (const [legacyStart, legacyEnd] of LEGACY_MARKER_ALIASES[stepKey] || []) {
      if (stripped.includes(legacyStart) && stripped.includes(legacyEnd)) {
        const s = stripped.indexOf(legacyStart);
        const e = stripped.indexOf(legacyEnd);
        const inner = stripped.slice(s + legacyStart.length, e).trim();
        return `${start}\n${inner}\n${end}`;
      }
    }
    return stripped;
  }
  return `${start}\n${stripped}\n${end}`;
}

/** Internal sub-section delimiters stripped from preview (not step boundaries). */
const INTERNAL_BOILERPLATE_DELIMITER =
  /^---(?:SERP RESEARCH(?:\s*\([^)]+\))?|SERP ANALYSIS(?:\s*&\s*(?:GAPS|RESEARCH))?(?:\s*\(STEP[^)]+\))?|FACT CHECK REPORT START|FACT CHECK REPORT END|CORRECTED ARTICLE START|CORRECTED ARTICLE END|PUBLISHING METADATA START|PUBLISHING METADATA END|PERPLEXITY WEB FACT-CHECK[^-]*|DRAFT FACT-CHECK SCAN[^-]*|EDITOR FACT-CHECK[^-]*|MAIN RESPONSE|RESPONSE|CITATION URLS[^-]*|RELATED QUESTIONS[^-]*|PASTE PERPLEXITY[^-]*|SERP RESEARCH LAYER)---\s*$/gim;

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
    // Keep the STEP START/END markers so every step shows the same chrome.
    return raw.slice(fcStart, fcEnd + FACT_CHECK_END.length).trim();
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
    .replace(INTERNAL_BOILERPLATE_DELIMITER, "")
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
  if (stepKey) {
    out = ensureStepBoundaryMarkers(out, stepKey);
  }
  return normalizePipelineMarkdown(out);
}
