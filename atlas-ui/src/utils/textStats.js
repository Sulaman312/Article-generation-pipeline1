/** Count words, characters, paragraphs, and estimated reading time for plain / markdown text. */

const FAQ_HEADING = /^##\s+.*\b(faq|frequently\s+asked\s+questions)\b/i;

/** Body prose only — excludes FAQ block and JSON-LD (matches backend word-count rules). */
export function markdownForWordCount(text) {
  let raw = text ?? "";
  raw = raw.replace(
    /---FAQ SCHEMA \(JSON-LD\) START---[\s\S]*?---FAQ SCHEMA \(JSON-LD\) END---/gi,
    " "
  );
  raw = raw.replace(
    /<script\s+type=["']application\/ld\+json["'][^>]*>[\s\S]*?<\/script>/gi,
    " "
  );
  const lines = raw.split("\n");
  const out = [];
  let inFaq = false;
  for (const line of lines) {
    const stripped = line.trim();
    if (FAQ_HEADING.test(stripped)) {
      inFaq = true;
      continue;
    }
    if (inFaq && stripped.startsWith("## ") && !FAQ_HEADING.test(stripped)) {
      inFaq = false;
    }
    if (!inFaq) out.push(line);
  }
  return out.join("\n");
}

export const WORD_COUNT_TOLERANCE = 100;

export function wordCountBounds(target) {
  const n = Math.max(100, Number(target) || 0);
  const margin = WORD_COUNT_TOLERANCE;
  return [Math.max(100, n - margin), n + margin];
}

export function computeTextStats(text) {
  const raw = markdownForWordCount(text ?? "");
  const trimmed = raw.trim();
  const words = trimmed
    ? trimmed.match(/\b[\w''’-]+\b/gu)?.length ?? 0
    : 0;
  const chars = raw.length;
  const paras = trimmed
    ? raw.split(/\n\s*\n/).filter((p) => p.trim().length > 0).length
    : 0;
  const lines = trimmed ? raw.split("\n").length : 0;
  const paragraphCount = paras > 0 ? paras : trimmed ? 1 : 0;
  const wpm = 225;
  const readingMinutes = words > 0 ? Math.max(1, Math.round(words / wpm)) : 0;
  return {
    words,
    chars,
    paragraphs: paragraphCount,
    lines,
    readingMinutes,
  };
}
