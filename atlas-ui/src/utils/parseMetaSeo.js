export const META_SEO_START = "---META SEO START---";
export const META_SEO_END = "---META SEO END---";

const OPTION_LINE =
  /^\s*(\d+)\.\s+(.+)\s*\((\d+)\s*characters?\)\s*$/i;

/** @returns {{ index: number, text: string, charCount: number }[]} */
export function parseMetaSeoOptionLines(blockText) {
  const options = [];
  for (const line of String(blockText || "").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const m = trimmed.match(OPTION_LINE);
    if (!m) continue;
    const optionText = m[2].trim();
    options.push({
      index: Number(m[1]),
      text: optionText,
      charCount: Number(m[3]) || optionText.length,
    });
  }
  return options;
}

function sectionBody(raw, headerPattern, endPattern) {
  const match = raw.match(headerPattern);
  if (!match || match.index === undefined) return "";
  const start = match.index + match[0].length;
  const rest = raw.slice(start);
  const endMatch = rest.search(endPattern);
  const body = endMatch === -1 ? rest : rest.slice(0, endMatch);
  return body.trim();
}

/** Parse meta SEO artifact (markerless or delimited). */
export function parseMetaSeoStructured(text) {
  const rawInput = String(text || "").trim();
  if (!rawInput) return null;

  const start = rawInput.indexOf(META_SEO_START);
  const end = rawInput.indexOf(META_SEO_END);
  const raw =
    start !== -1 && end !== -1 && end > start
      ? rawInput.slice(start + META_SEO_START.length, end).trim()
      : rawInput;

  const pageType = raw.match(/^PAGE TYPE:\s*(.+)$/im)?.[1]?.trim() || "";
  const keyword = raw.match(/^TARGET KEYWORD:\s*(.+)$/im)?.[1]?.trim() || "";

  const titleBlock = sectionBody(
    raw,
    /^META TITLE OPTIONS[^\n]*\n/im,
    /^META DESCRIPTION OPTIONS/im
  );
  const descMatch = raw.match(/^META DESCRIPTION OPTIONS[^\n]*\n/im);
  const descBlock = descMatch
    ? raw.slice(descMatch.index + descMatch[0].length).trim()
    : "";

  const titleOptions = parseMetaSeoOptionLines(titleBlock);
  const descriptionOptions = parseMetaSeoOptionLines(descBlock);

  if (!titleOptions.length && !descriptionOptions.length && !pageType && !keyword) {
    return null;
  }

  return {
    pageType,
    keyword,
    titleOptions,
    descriptionOptions,
  };
}

export function isMetaSeoFormat(text) {
  if (typeof text !== "string" || !text.trim()) return false;
  if (/META TITLE OPTIONS/i.test(text) || /META DESCRIPTION OPTIONS/i.test(text)) {
    const parsed = parseMetaSeoStructured(text);
    return Boolean(
      parsed?.titleOptions?.length || parsed?.descriptionOptions?.length
    );
  }
  return false;
}

export function charCountStatus(count, min, max) {
  if (count < min) return "short";
  if (count > max) return "long";
  return "ok";
}

/** @deprecated Use parseMetaSeoStructured */
export function parseMetaSeo(text) {
  return parseMetaSeoStructured(text);
}
