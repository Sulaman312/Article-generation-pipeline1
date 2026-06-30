/** Manual article fields (aligned with backend/editorial_input.py). */

export const EDITORIAL_FIELD_SPECS = [
  {
    key: "topic",
    label: "Topic",
    required: true,
    wide: true,
    hint: "Main subject or working title for this article run.",
  },
  {
    key: "seed_keyword",
    label: "Seed Keyword",
    hint: "Primary keyword to target in search and the topic card.",
  },
  {
    key: "secondary_keywords",
    label: "Secondary Keywords",
    wide: true,
    hint: "Supporting phrases or long-tail terms, comma-separated.",
  },
  {
    key: "search_intent",
    label: "Search Intent",
    hint: "What the searcher wants, e.g. informational or commercial.",
  },
  {
    key: "target_persona",
    label: "Target Persona",
    hint: "Who you are writing for — role, industry, or segment.",
  },
  {
    key: "word_count",
    label: "Word Count",
    hint: "Target length, e.g. 1500 or 2000–2500 words.",
  },
  {
    key: "angle_hook",
    label: "Angle / Hook",
    wide: true,
    hint: "The unique angle or hook that sets this piece apart.",
  },
  {
    key: "internal_links",
    label: "Internal Links",
    wide: true,
    hint: "Site pages or URLs to reference or link from the article.",
  },
  {
    key: "include_faq",
    label: "Include FAQ",
    hint: "Yes = H2 FAQ with 5–7 Q&As (recommended for SEO / featured snippets). Set No only if you must skip.",
  },
  {
    key: "include_external_links",
    label: "Include External Links",
    hint: "Yes = 3–5 outbound links to authoritative sources (gov, research, industry) for trust. Uses URLs from SERP research.",
  },
  {
    key: "notes",
    label: "Notes",
    wide: true,
    hint: "Pipeline constraints such as language, tone, title rules, CTA, links, images, or keyword usage.",
  },
];

export const SEMRUSH_FIELD_HINT =
  "Optional. Leave blank if you already filled Seed + Secondary Keywords above — no Semrush API needed.";

export const EMPTY_EDITORIAL_FIELDS = () =>
  Object.fromEntries(
    EDITORIAL_FIELD_SPECS.map((f) => [
      f.key,
      f.key === "include_faq" || f.key === "include_external_links" ? "Yes" : "",
    ])
  );

export function buildManualInputsPayload(fields, semrushNotes = "") {
  const manual_inputs = {};
  for (const spec of EDITORIAL_FIELD_SPECS) {
    const v = (fields[spec.key] || "").trim();
    if (v) manual_inputs[spec.key] = v;
  }
  const semrush = (semrushNotes || fields.semrush_notes || "").trim();
  return { manual_inputs, semrush_notes: semrush };
}

export function hasRequiredTopic(fields) {
  return Boolean((fields.topic || "").trim());
}
