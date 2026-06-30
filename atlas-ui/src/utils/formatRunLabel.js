/** Human-friendly run label for breadcrumbs (replaces raw folder ids). */

export function formatRunLabel(runId, isoTimestamp, runNumber) {
  let d = null;
  if (isoTimestamp) {
    const parsed = new Date(isoTimestamp);
    if (!Number.isNaN(parsed.getTime())) d = parsed;
  }
  if (!d) {
    const m = runId.match(
      /^(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})$/
    );
    if (m) {
      d = new Date(
        Number(m[1]),
        Number(m[2]) - 1,
        Number(m[3]),
        Number(m[4]),
        Number(m[5]),
        Number(m[6])
      );
    }
  }

  const parts = [];
  if (d && !Number.isNaN(d.getTime())) {
    parts.push(
      new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(d)
    );
  }
  if (runNumber != null) parts.push(`Run #${runNumber}`);
  if (parts.length) return parts.join(" · ");
  return runId;
}
