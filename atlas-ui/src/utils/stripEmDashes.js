/** Unicode long-dashes that must not appear in published copy. */
const DASH_CHARS = "\u2012\u2013\u2014\u2015\u2212\u2e3a\u2e3b";
const DASH_RE = new RegExp(`[${DASH_CHARS}]`);
const SPACED_DASH_RE = new RegExp(` [${DASH_CHARS}] `, "g");
const TRAILING_DASH_RE = new RegExp(` [${DASH_CHARS}]`, "g");
const LEADING_DASH_RE = new RegExp(`[${DASH_CHARS}] `, "g");
const RANGE_DASH_RE = new RegExp(`(\\d)[${DASH_CHARS}](\\d)`, "g");
const EM_REMAINING_RE = /[\u2014\u2015\u2e3a\u2e3b]/g;
const EN_REMAINING_RE = /[\u2012\u2013\u2212]/g;

export function stripEmDashes(text) {
  if (text == null || text === "") return text;
  let out = String(text);
  out = out.replace(/&mdash;|&#8212;|&#x2014;/gi, ": ");
  out = out.replace(/&ndash;|&#8211;|&#x2013;/gi, "-");
  out = out.replace(/ -- /g, ": ");
  if (!DASH_RE.test(out)) return out;
  out = out.replace(SPACED_DASH_RE, ": ");
  out = out.replace(TRAILING_DASH_RE, ":");
  out = out.replace(LEADING_DASH_RE, ": ");
  out = out.replace(RANGE_DASH_RE, "$1-$2");
  out = out.replace(EM_REMAINING_RE, ", ");
  out = out.replace(EN_REMAINING_RE, "-");
  return out;
}
