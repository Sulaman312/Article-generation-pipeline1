const KEY_LINE = /^([A-Z][A-Z0-9 \-]+):\s*(.*)$/;
const SUB_KEY_LINE = /^\s{2,}([^:]+):\s*(.*)$/;

function titleCaseFieldLabel(key) {
  return key
    .split(/\s+/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ");
}

function stripBracketWrappers(value) {
  let v = value.trim();
  if (v.startsWith("[") && v.endsWith("]") && v.length > 2) {
    v = v.slice(1, -1).trim();
  }
  return v;
}

/**
 * Parse a delimited block (e.g. topic card, publishing metadata) into field rows.
 */
export function parseDelimitedFields(text, startMarker, endMarker) {
  if (typeof text !== "string" || !text.trim()) return null;
  const s = text.indexOf(startMarker);
  const e = text.indexOf(endMarker);
  if (s === -1 || e === -1 || e <= s) return null;

  const body = text.slice(s + startMarker.length, e).trim();
  const lines = body.split(/\r?\n/);
  const rawFields = [];
  let cur = null;

  for (const line of lines) {
    const sub = line.match(SUB_KEY_LINE);
    if (sub && cur) {
      if (!cur.children) cur.children = [];
      cur.children.push({
        key: sub[1].trim(),
        value: sub[2].trim(),
      });
      continue;
    }
    const m = line.match(KEY_LINE);
    if (m) {
      if (cur) rawFields.push(cur);
      cur = { key: m[1], value: m[2].trim(), children: null };
    } else if (cur && line.trim()) {
      cur.value = cur.value
        ? `${cur.value}\n${line.trim()}`
        : line.trim();
    }
  }
  if (cur) rawFields.push(cur);

  if (!rawFields.length) return null;

  return rawFields.map(({ key, value, children }) => ({
    key,
    label: titleCaseFieldLabel(key),
    value: stripBracketWrappers(value),
    children: children?.map((c) => ({
      key: c.key,
      label: titleCaseFieldLabel(c.key),
      value: stripBracketWrappers(c.value),
    })),
  }));
}
