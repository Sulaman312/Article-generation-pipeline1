/** Shared markdown block parser (used by preview + export). */

/** If the whole artifact is one ```markdown fence, return inner source. */
export function unwrapMarkdownFences(text) {
  if (typeof text !== "string") return "";
  const trimmed = text.trim();
  const wrapped = trimmed.match(/^```(?:markdown|md|text)?\s*\n([\s\S]*?)\n```\s*$/i);
  if (wrapped) return wrapped[1].trim();
  return text;
}

export function isBlockStart(line) {
  return (
    /^#{1,6}\s+/.test(line) ||
    /^```/.test(line) ||
    /^[-*+]\s+/.test(line) ||
    /^\d+\.\s+/.test(line) ||
    /^>\s?/.test(line) ||
    /^---+\s*$/.test(line) ||
    /^\|.*\|/.test(line)
  );
}

function parseRow(line) {
  const trimmed = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  return trimmed.split("|").map((s) => s.trim());
}

export function parseBlocks(text) {
  if (typeof text !== "string") return [];
  const normalized = unwrapMarkdownFences(text).replace(/\r\n/g, "\n");
  const lines = normalized.split("\n");
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];

    if (/^```/.test(line)) {
      const lang = line.replace(/^```/, "").trim().toLowerCase();
      const buf = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) {
        buf.push(lines[i]);
        i++;
      }
      i++;
      const inner = buf.join("\n");
      const isMarkdownLang = !lang || lang === "markdown" || lang === "md" || lang === "text";
      if (isMarkdownLang && /^#{1,6}\s+/m.test(inner)) {
        blocks.push(...parseBlocks(inner));
        continue;
      }
      blocks.push({ type: "code", lang, text: inner });
      continue;
    }

    const headingMatch = line.match(/^(#{1,6})\s+(.*?)\s*#*\s*$/);
    if (headingMatch) {
      blocks.push({
        type: "heading",
        level: headingMatch[1].length,
        text: headingMatch[2],
      });
      i++;
      continue;
    }

    if (/^---+\s*$/.test(line)) {
      blocks.push({ type: "hr" });
      i++;
      continue;
    }

    if (/^>\s?/.test(line)) {
      const buf = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) {
        buf.push(lines[i].replace(/^>\s?/, ""));
        i++;
      }
      blocks.push({ type: "quote", text: buf.join(" ") });
      continue;
    }

    if (/^[-*+]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^[-*+]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^[-*+]\s+/, ""));
        i++;
      }
      blocks.push({ type: "ul", items });
      continue;
    }

    if (/^\d+\.\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\d+\.\s+/, ""));
        i++;
      }
      blocks.push({ type: "ol", items });
      continue;
    }

    if (
      /^\|.*\|/.test(line) &&
      i + 1 < lines.length &&
      /^\|?[\s:|-]+\|?\s*$/.test(lines[i + 1])
    ) {
      const headerCells = parseRow(line);
      const rows = [];
      i += 2;
      while (i < lines.length && /^\|.*\|/.test(lines[i])) {
        rows.push(parseRow(lines[i]));
        i++;
      }
      blocks.push({ type: "table", header: headerCells, rows });
      continue;
    }

    if (/^\s*$/.test(line)) {
      i++;
      continue;
    }

    const buf = [line];
    i++;
    while (
      i < lines.length &&
      !/^\s*$/.test(lines[i]) &&
      !isBlockStart(lines[i])
    ) {
      buf.push(lines[i]);
      i++;
    }
    blocks.push({ type: "p", text: buf.join("\n") });
  }
  return blocks;
}
