import { parseBlocks } from "./markdownBlocks";
import { copyTextToClipboard } from "./copyText";

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Strip inline markdown to readable plain text. */
export function inlineToPlain(text) {
  if (!text) return "";
  return String(text)
    .replace(/`([^`\n]+)`/g, "$1")
    .replace(/\*\*([^*\n]+)\*\*/g, "$1")
    .replace(/__([^_\n]+)__/g, "$1")
    .replace(/\*([^*\n]+)\*/g, "$1")
    .replace(/_([^_\n]+)_/g, "$1")
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, "$1 ($2)")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, "$1 ($2)");
}

function inlineToHtml(text) {
  if (!text) return "";
  let s = escapeHtml(text);
  s = s.replace(/`([^`\n]+)`/g, "<code>$1</code>");
  s = s.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/__([^_\n]+)__/g, "<strong>$1</strong>");
  s = s.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
  s = s.replace(/_([^_\n]+)_/g, "<em>$1</em>");
  s = s.replace(
    /\[([^\]]+)\]\(([^)\s]+)\)/g,
    '<a href="$2">$1</a>'
  );
  return s.replace(/\n/g, "<br />");
}

/** Article markdown → plain text suitable for Word / Google Docs / CMS. */
export function markdownToPlainText(markdown) {
  const blocks = parseBlocks(markdown || "");
  const parts = [];

  for (const block of blocks) {
    switch (block.type) {
      case "heading": {
        const t = inlineToPlain(block.text);
        if (t) parts.push(t, "");
        break;
      }
      case "p": {
        const t = inlineToPlain(block.text);
        if (t) parts.push(t, "");
        break;
      }
      case "ul":
        for (const it of block.items) {
          parts.push(`• ${inlineToPlain(it)}`);
        }
        parts.push("");
        break;
      case "ol":
        block.items.forEach((it, idx) => {
          parts.push(`${idx + 1}. ${inlineToPlain(it)}`);
        });
        parts.push("");
        break;
      case "quote":
        parts.push(inlineToPlain(block.text), "");
        break;
      case "code":
        if (block.text?.trim()) parts.push(block.text.trim(), "");
        break;
      case "hr":
        parts.push("—", "");
        break;
      case "table": {
        parts.push(block.header.map(inlineToPlain).join("\t"));
        for (const row of block.rows) {
          parts.push(row.map(inlineToPlain).join("\t"));
        }
        parts.push("");
        break;
      }
      default:
        break;
    }
  }

  return parts.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

/** Article markdown → simple HTML for rich paste (keeps headings, lists, bold). */
export function markdownToHtml(markdown) {
  const blocks = parseBlocks(markdown || "");
  const parts = ['<div style="font-family: Georgia, serif; font-size: 12pt; line-height: 1.6; color: #111;">'];

  for (const block of blocks) {
    switch (block.type) {
      case "heading": {
        const level = Math.min(6, Math.max(1, block.level));
        parts.push(
          `<h${level}>${inlineToHtml(block.text)}</h${level}>`
        );
        break;
      }
      case "p":
        parts.push(`<p>${inlineToHtml(block.text)}</p>`);
        break;
      case "ul":
        parts.push("<ul>");
        for (const it of block.items) {
          parts.push(`<li>${inlineToHtml(it)}</li>`);
        }
        parts.push("</ul>");
        break;
      case "ol":
        parts.push("<ol>");
        for (const it of block.items) {
          parts.push(`<li>${inlineToHtml(it)}</li>`);
        }
        parts.push("</ol>");
        break;
      case "quote":
        parts.push(`<blockquote>${inlineToHtml(block.text)}</blockquote>`);
        break;
      case "code":
        parts.push(`<pre><code>${escapeHtml(block.text)}</code></pre>`);
        break;
      case "hr":
        parts.push("<hr />");
        break;
      case "table":
        parts.push("<table border=\"1\" cellpadding=\"6\" cellspacing=\"0\">");
        parts.push("<thead><tr>");
        for (const h of block.header) {
          parts.push(`<th>${inlineToHtml(h)}</th>`);
        }
        parts.push("</tr></thead><tbody>");
        for (const row of block.rows) {
          parts.push("<tr>");
          for (const cell of row) {
            parts.push(`<td>${inlineToHtml(cell)}</td>`);
          }
          parts.push("</tr>");
        }
        parts.push("</tbody></table>");
        break;
      default:
        break;
    }
  }

  parts.push("</div>");
  return parts.join("");
}

/**
 * Copy formatted article (HTML + plain text). Falls back to plain text only.
 */
export async function copyFormattedMarkdown(markdown) {
  const plain = markdownToPlainText(markdown);
  if (!plain.trim()) return false;

  const html = markdownToHtml(markdown);

  try {
    if (navigator.clipboard?.write && typeof ClipboardItem !== "undefined") {
      await navigator.clipboard.write([
        new ClipboardItem({
          "text/plain": new Blob([plain], { type: "text/plain" }),
          "text/html": new Blob([html], { type: "text/html" }),
        }),
      ]);
      return true;
    }
  } catch {
    /* fall through */
  }

  return copyTextToClipboard(plain);
}
