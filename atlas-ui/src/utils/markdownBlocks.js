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
    /^\|.*\|/.test(line) ||
    /^\s*<(?:div|section|style)\b/i.test(line)
  );
}

/** Collect a top-level HTML block starting at line i (div/section/style). */
function consumeHtmlBlock(lines, startIdx) {
  const first = lines[startIdx] || "";
  const open = first.match(/^\s*<(div|section|style)\b/i);
  if (!open) return null;
  const tag = open[1].toLowerCase();
  const buf = [first];
  let i = startIdx + 1;
  if (tag === "style") {
    while (i < lines.length) {
      buf.push(lines[i]);
      if (/<\/style>/i.test(lines[i])) {
        i += 1;
        break;
      }
      i += 1;
    }
    return { end: i, html: buf.join("\n") };
  }
  // Nested div/section: track depth on open/close tags.
  let depth = (first.match(new RegExp(`<${tag}\\b`, "gi")) || []).length;
  depth -= (first.match(new RegExp(`</${tag}>`, "gi")) || []).length;
  if (depth <= 0 && /<\/(?:div|section)>/i.test(first)) {
    return { end: i, html: buf.join("\n") };
  }
  while (i < lines.length && depth > 0) {
    const line = lines[i];
    buf.push(line);
    depth += (line.match(new RegExp(`<${tag}\\b`, "gi")) || []).length;
    depth -= (line.match(new RegExp(`</${tag}>`, "gi")) || []).length;
    i += 1;
  }
  // Pull a trailing <style>…</style> that often follows the CTA card.
  if (i < lines.length && /^\s*<style\b/i.test(lines[i])) {
    const stylePart = consumeHtmlBlock(lines, i);
    if (stylePart) {
      buf.push(stylePart.html);
      i = stylePart.end;
    }
  }
  return { end: i, html: buf.join("\n") };
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

    if (/^\s*<(?:div|section|style)\b/i.test(line)) {
      const htmlBlock = consumeHtmlBlock(lines, i);
      if (htmlBlock) {
        blocks.push({ type: "html", html: htmlBlock.html });
        i = htmlBlock.end;
        continue;
      }
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
