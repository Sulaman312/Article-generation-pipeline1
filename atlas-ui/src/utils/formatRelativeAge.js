/** Parse run created time from ISO timestamp or `YYYY-MM-DD_HH-MM-SS` run_id. */
export function parseRunDate(timestamp, runId) {
  if (timestamp) {
    const d = new Date(timestamp);
    if (!Number.isNaN(d.getTime())) return d;
  }
  if (runId) {
    const m = String(runId).match(
      /^(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})$/
    );
    if (m) {
      return new Date(
        Number(m[1]),
        Number(m[2]) - 1,
        Number(m[3]),
        Number(m[4]),
        Number(m[5]),
        Number(m[6])
      );
    }
  }
  return null;
}

/** Calendar date for matrix and lists (e.g. `May 12, 2026`). */
export function formatRunDate(date) {
  if (!date || Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/** Full timestamp for tooltips. */
export function formatRunDateTime(date) {
  if (!date || Number.isNaN(date.getTime())) return null;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Compact age label: `4d`, `58m`, `2h`, `just now`. */
export function formatRelativeAge(date) {
  if (!date || Number.isNaN(date.getTime())) return null;
  const sec = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (sec < 60) return "just now";
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h`;
  const day = Math.floor(hr / 24);
  if (day < 14) return `${day}d`;
  const wk = Math.floor(day / 7);
  if (wk < 8) return `${wk}w`;
  const mo = Math.floor(day / 30);
  return `${mo}mo`;
}

export function countDoneSteps(statuses, stepKeys) {
  if (!statuses) return 0;
  return stepKeys.filter((k) => statuses[k] === "done").length;
}
