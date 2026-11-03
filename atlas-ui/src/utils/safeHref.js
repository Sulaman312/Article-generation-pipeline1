/** Allow only http(s) and mailto hrefs in rendered markdown. */

const SAFE_HREF = /^(https?:\/\/[^\s]+|mailto:[^\s]+)$/i;

export function sanitizeHref(raw) {
  const href = String(raw || "").trim();
  if (!href) return null;
  return SAFE_HREF.test(href) ? href : null;
}
