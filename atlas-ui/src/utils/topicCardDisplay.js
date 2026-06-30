/** Which topic-card rows to show in the structured UI. */

const HIDE_WHEN_EMPTY_SEMRUSH = new Set([
  "SEMRUSH LOCALE DEVICE",
  "SEMRUSH METRICS VERBATIM",
  "SEMRUSH SERP FEATURES VERBATIM",
  "SEMRUSH RELATED VARIANTS VERBATIM",
]);

const EMPTY_SEMRUSH_VALUES = new Set([
  "not provided",
  "not stated",
  "n/a",
  "—",
  "-",
  "",
]);

function normalizeValue(value) {
  return String(value || "")
    .trim()
    .replace(/^\[|\]$/g, "")
    .toLowerCase();
}

function isEmptySemrushValue(value) {
  const v = normalizeValue(value);
  return EMPTY_SEMRUSH_VALUES.has(v) || v.includes("not provided");
}

/** Form keywords without a tool paste (legacy cards used NOT PROVIDED on Semrush rows). */
export function isManualKeywordTopicCard(fields) {
  if (!fields?.length) return false;

  const keywordSource = fields.find((r) => r.key === "KEYWORD SOURCE");
  if (keywordSource && normalizeValue(keywordSource.value).includes("manual")) {
    return true;
  }

  const toolStatus = fields.find((r) => r.key === "SEMRUSH TOOL STATUS");
  if (toolStatus) {
    const v = normalizeValue(toolStatus.value);
    if (v.includes("manual keywords")) return true;
    if (v.includes("not provided")) {
      const semrushRows = fields.filter((r) =>
        HIDE_WHEN_EMPTY_SEMRUSH.has(r.key)
      );
      if (
        semrushRows.length > 0 &&
        semrushRows.every((r) => isEmptySemrushValue(r.value))
      ) {
        return true;
      }
    }
  }

  return false;
}

export function hasFormKeywords(manualInputs) {
  if (!manualInputs || typeof manualInputs !== "object") return false;
  const seed =
    manualInputs["Seed Keyword"] ||
    manualInputs.seed_keyword ||
    "";
  const sec =
    manualInputs["Secondary Keywords"] ||
    manualInputs.secondary_keywords ||
    "";
  return Boolean(String(seed).trim() || String(sec).trim());
}

export function filterTopicCardFieldsForDisplay(fields, manualInputs = null) {
  if (!fields?.length) return fields;

  const manualKeywords =
    isManualKeywordTopicCard(fields) || hasFormKeywords(manualInputs);

  const filtered = fields.filter((row) => {
    if (manualKeywords && HIDE_WHEN_EMPTY_SEMRUSH.has(row.key)) {
      if (isEmptySemrushValue(row.value)) return false;
    }
    if (
      manualKeywords &&
      row.key === "SEMRUSH TOOL STATUS" &&
      isEmptySemrushValue(row.value)
    ) {
      return false;
    }
    if (
      manualKeywords &&
      row.key === "SEMRUSH TOOL STATUS" &&
      normalizeValue(row.value).includes("manual keywords")
    ) {
      return false;
    }
    return true;
  });

  if (manualKeywords && !filtered.some((r) => r.key === "KEYWORD SOURCE")) {
    return [
      {
        key: "KEYWORD SOURCE",
        label: "Keyword Source",
        value: "Article form (Seed + Secondary Keywords)",
      },
      ...filtered,
    ];
  }

  return filtered;
}

export function displayTopicCardFieldValue(row) {
  if (row.key === "KEYWORD SOURCE") {
    const v = normalizeValue(row.value);
    if (v.includes("manual")) {
      return "Article form (Seed + Secondary Keywords)";
    }
  }
  return row.value;
}
