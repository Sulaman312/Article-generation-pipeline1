/** Format milliseconds as a short human duration (e.g. `2m 15s`). */

export function formatStepDurationMs(ms) {
  if (ms == null || Number.isNaN(ms) || ms < 0) return null;
  const totalSec = Math.round(ms / 1000);
  if (totalSec < 1) return "<1s";
  if (totalSec < 60) return `${totalSec}s`;
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  if (min < 60) return sec > 0 ? `${min}m ${sec}s` : `${min}m`;
  const hr = Math.floor(min / 60);
  const remMin = min % 60;
  return remMin > 0 ? `${hr}h ${remMin}m` : `${hr}h`;
}

/** Parse ISO timestamps as UTC epoch ms (timezone-agnostic elapsed math). */
export function parseIsoTimestamp(iso) {
  if (!iso) return null;
  let s = String(iso).trim();
  // Naive ISO strings from the API are UTC — never browser-local wall clock.
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?$/.test(s)) {
    s = `${s}Z`;
  } else if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})\+00:00$/.test(s)) {
    s = s.replace("+00:00", "Z");
  }
  const t = Date.parse(s);
  return Number.isNaN(t) ? null : t;
}

function elapsedMsFromStartedAt(startedAt, nowMs = Date.now()) {
  const t = parseIsoTimestamp(startedAt);
  if (t == null) return null;
  return Math.max(0, nowMs - t);
}

function isActiveRunTiming(timing) {
  if (!timing?.started_at) return false;
  if (timing.finished_at) return false;
  if (timing.duration_ms != null && timing.duration_ms > 0) return false;
  return timing.status == null || timing.status === "running";
}

/** Short status label for pills and matrix titles. */
export function stepStatusBaseLabel(status) {
  if (status === "done") return "Done";
  if (status === "running") return "Running";
  if (status === "error") return "Failed";
  if (status === "skipped") return "Skipped";
  return "Pending";
}

/**
 * Status label plus duration (e.g. `Running · 2m 15s`, `Done · 45s`).
 */
export function formatStepStatusWithDuration(status, timing, nowMs = Date.now()) {
  const base = stepStatusBaseLabel(status);

  if (!timing) return base;

  if (status === "running") {
    const elapsed = formatStepDurationMs(
      elapsedMsFromStartedAt(timing.started_at, nowMs)
    );
    return elapsed ? `${base} · ${elapsed}` : base;
  }

  const duration = formatStepDurationMs(timing.duration_ms);
  if (!duration) return base;

  const prefix = timing.inferred && !timing.client ? "~" : "";
  return `${base} · ${prefix}${duration}`;
}

/**
 * Resolve timing for a step. Running steps only use an in-flight record so a
 * prior completion does not leak an old `started_at` into the live clock.
 */
export function resolveStepTiming(
  stepKey,
  serverTimings,
  clientDurations,
  stepStatus
) {
  const server = serverTimings?.[stepKey];

  if (stepStatus === "running") {
    if (isActiveRunTiming(server)) {
      return {
        started_at: server.started_at,
        finished_at: null,
        duration_ms: null,
        status: "running",
      };
    }
    return null;
  }

  if (server?.duration_ms != null && server.duration_ms > 0) {
    return server;
  }
  const clientMs = clientDurations?.[stepKey];
  if (clientMs != null && clientMs > 0) {
    return { duration_ms: clientMs, client: true };
  }
  return server || null;
}
