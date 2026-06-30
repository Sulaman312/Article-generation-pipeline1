/** Textarea helpers for markdown formatting (toolbar actions). */

export function getSelection(textarea) {
  const start = textarea.selectionStart ?? 0;
  const end = textarea.selectionEnd ?? 0;
  const value = textarea.value ?? "";
  return {
    start,
    end,
    value,
    selected: value.slice(start, end),
    before: value.slice(0, start),
    after: value.slice(end),
  };
}

export function applyEdit(textarea, newValue, selectionStart, selectionEnd, onChange) {
  onChange?.(newValue);
  requestAnimationFrame(() => {
    textarea.focus();
    textarea.setSelectionRange(selectionStart, selectionEnd);
  });
}

/** Wrap selection or placeholder with markers, e.g. **bold**. */
export function wrapSelection(textarea, before, after, placeholder, onChange) {
  const { start, end, value, selected, before: pre, after: post } =
    getSelection(textarea);
  const inner = selected || placeholder;
  const wrapped = `${before}${inner}${after}`;
  const newValue = pre + wrapped + post;
  const selStart = start + before.length;
  const selEnd = selStart + inner.length;
  applyEdit(textarea, newValue, selStart, selEnd, onChange);
}

/** Toggle markdown prefix on each line in selection (or current line). */
export function toggleLinePrefix(textarea, prefix, onChange) {
  const { start, end, value } = getSelection(textarea);
  const lineStart = value.lastIndexOf("\n", start - 1) + 1;
  const lineEndIdx = value.indexOf("\n", end);
  const lineEnd = lineEndIdx === -1 ? value.length : lineEndIdx;
  const block = value.slice(lineStart, lineEnd);
  const lines = block.split("\n");
  const allHave = lines.every((l) => l.startsWith(prefix));
  const newLines = lines.map((l) =>
    allHave ? l.slice(prefix.length) : prefix + l
  );
  const newBlock = newLines.join("\n");
  const newValue =
    value.slice(0, lineStart) + newBlock + value.slice(lineEnd);
  const delta = newBlock.length - block.length;
  applyEdit(
    textarea,
    newValue,
    start + (allHave ? -prefix.length : prefix.length),
    end + delta,
    onChange
  );
}

/** Set heading level (1–3) on selected line(s); 0 = paragraph (strip heading). */
export function setHeadingLevel(textarea, level, onChange) {
  const { start, end, value } = getSelection(textarea);
  const lineStart = value.lastIndexOf("\n", start - 1) + 1;
  const lineEndIdx = value.indexOf("\n", end);
  const lineEnd = lineEndIdx === -1 ? value.length : lineEndIdx;
  const block = value.slice(lineStart, lineEnd);
  const lines = block.split("\n");
  const newLines = lines.map((line) => {
    const stripped = line.replace(/^#{1,6}\s+/, "");
    if (level === 0) return stripped;
    return `${"#".repeat(level)} ${stripped}`;
  });
  const newBlock = newLines.join("\n");
  const newValue =
    value.slice(0, lineStart) + newBlock + value.slice(lineEnd);
  applyEdit(textarea, newValue, lineStart, lineStart + newBlock.length, onChange);
}

export function insertLink(textarea, onChange) {
  const { start, end, value, selected, before, after } = getSelection(textarea);
  const label = selected || "link text";
  const url = "https://";
  const md = `[${label}](${url})`;
  const newValue = before + md + after;
  const urlStart = start + label.length + 3;
  const urlEnd = urlStart + url.length;
  applyEdit(textarea, newValue, urlStart, urlEnd, onChange);
}

export function insertHorizontalRule(textarea, onChange) {
  const { start, end, value, before, after } = getSelection(textarea);
  const insert = (before.endsWith("\n") || before === "" ? "" : "\n\n") + "---\n\n";
  const newValue = before + insert + after;
  applyEdit(textarea, newValue, start + insert.length, start + insert.length, onChange);
}
