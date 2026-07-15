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
  // Bold before italic so **…** wins over *…*
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

const HEADING_STYLES = {
  1: "font-size:20pt;font-weight:700;margin:18pt 0 10pt;line-height:1.25;color:#111;",
  2: "font-size:16pt;font-weight:700;margin:16pt 0 8pt;line-height:1.3;color:#111;",
  3: "font-size:14pt;font-weight:700;margin:14pt 0 6pt;line-height:1.35;color:#111;",
  4: "font-size:12pt;font-weight:700;margin:12pt 0 6pt;line-height:1.4;color:#111;",
  5: "font-size:11pt;font-weight:700;margin:10pt 0 4pt;line-height:1.4;color:#111;",
  6: "font-size:11pt;font-weight:700;margin:10pt 0 4pt;line-height:1.4;color:#111;",
};

/** Article markdown → readable plain text (format markers stripped). */
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

/**
 * Article markdown → HTML for rich paste (Word / Google Docs / CMS).
 * Inline styles help Word preserve heading hierarchy and lists.
 */
export function markdownToHtml(markdown) {
  const blocks = parseBlocks(markdown || "");
  const parts = [
    '<div style="font-family:Georgia,\'Times New Roman\',serif;font-size:12pt;line-height:1.65;color:#111;">',
  ];

  for (const block of blocks) {
    switch (block.type) {
      case "heading": {
        const level = Math.min(6, Math.max(1, block.level));
        const style = HEADING_STYLES[level] || HEADING_STYLES[2];
        parts.push(
          `<h${level} style="${style}">${inlineToHtml(block.text)}</h${level}>`
        );
        break;
      }
      case "p":
        parts.push(
          `<p style="margin:0 0 12pt;">${inlineToHtml(block.text)}</p>`
        );
        break;
      case "ul":
        parts.push('<ul style="margin:0 0 12pt;padding-left:24pt;">');
        for (const it of block.items) {
          parts.push(
            `<li style="margin:0 0 6pt;">${inlineToHtml(it)}</li>`
          );
        }
        parts.push("</ul>");
        break;
      case "ol":
        parts.push('<ol style="margin:0 0 12pt;padding-left:24pt;">');
        for (const it of block.items) {
          parts.push(
            `<li style="margin:0 0 6pt;">${inlineToHtml(it)}</li>`
          );
        }
        parts.push("</ol>");
        break;
      case "quote":
        parts.push(
          `<blockquote style="margin:0 0 12pt;padding-left:12pt;border-left:3pt solid #ccc;color:#333;">${inlineToHtml(block.text)}</blockquote>`
        );
        break;
      case "code":
        parts.push(
          `<pre style="font-family:Consolas,monospace;font-size:10pt;background:#f5f5f5;padding:8pt;margin:0 0 12pt;white-space:pre-wrap;"><code>${escapeHtml(block.text)}</code></pre>`
        );
        break;
      case "hr":
        parts.push('<hr style="border:none;border-top:1pt solid #ccc;margin:16pt 0;" />');
        break;
      case "table":
        parts.push(
          '<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;margin:0 0 12pt;width:100%;">'
        );
        parts.push("<thead><tr>");
        for (const h of block.header) {
          parts.push(
            `<th style="background:#f3f4f6;text-align:left;">${inlineToHtml(h)}</th>`
          );
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
 * Legacy but reliable: set text/html + text/plain on the copy event so Word /
 * Docs / Notion receive rich paste instead of stripped plain text.
 */
function copyViaCopyEvent(html, plain, markdownSource) {
  if (typeof document === "undefined") return false;
  let ok = false;
  const onCopy = (e) => {
    try {
      e.clipboardData.setData("text/html", html);
      // Keep markdown in text/plain so MD-aware editors preserve structure;
      // Word/Docs still take text/html when both are present.
      e.clipboardData.setData("text/plain", markdownSource || plain);
      e.preventDefault();
      ok = true;
    } catch {
      ok = false;
    }
  };
  document.addEventListener("copy", onCopy);
  try {
    // Need a selectable node in some browsers for execCommand('copy') to fire.
    const probe = document.createElement("span");
    probe.textContent = "\u00a0";
    probe.style.cssText =
      "position:fixed;left:-9999px;top:0;opacity:0;pointer-events:none;";
    document.body.appendChild(probe);
    const range = document.createRange();
    range.selectNodeContents(probe);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    const ran = document.execCommand("copy");
    sel.removeAllRanges();
    document.body.removeChild(probe);
    return Boolean(ran && ok);
  } catch {
    return false;
  } finally {
    document.removeEventListener("copy", onCopy);
  }
}

/**
 * Copy formatted article: HTML (rich paste) + markdown source (plain).
 * Falls back through copy-event HTML, then plain clipboard write.
 */
export async function copyFormattedMarkdown(markdown) {
  const source = String(markdown || "").replace(/\r\n/g, "\n").trim();
  if (!source) return false;

  const plain = markdownToPlainText(source);
  const html = markdownToHtml(source);
  if (!html.includes("</") && !plain.trim()) return false;

  try {
    if (navigator.clipboard?.write && typeof ClipboardItem !== "undefined") {
      await navigator.clipboard.write([
        new ClipboardItem({
          "text/plain": new Blob([source], { type: "text/plain" }),
          "text/html": new Blob([html], { type: "text/html" }),
        }),
      ]);
      return true;
    }
  } catch {
    /* fall through to copy-event / plain */
  }

  if (copyViaCopyEvent(html, plain, source)) return true;

  return copyTextToClipboard(source);
}
