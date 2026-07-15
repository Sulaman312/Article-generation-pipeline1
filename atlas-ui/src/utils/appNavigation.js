/**
 * Hash-free path state for deep links.
 * Examples:
 *   /
 *   /w/Acme
 *   /w/Acme/matrix|overview|artifacts
 *   /w/Acme/runs/run_123
 */

const VIEWS = new Set(["matrix", "overview", "artifacts"]);

export function parseAppPath(pathname = window.location.pathname) {
  const parts = String(pathname || "/")
    .replace(/^\/+|\/+$/g, "")
    .split("/")
    .filter(Boolean);

  if (parts[0] !== "w" || !parts[1]) {
    return { clientId: null, runId: null, view: "matrix" };
  }

  const clientId = decodeURIComponent(parts[1]);
  if (parts[2] === "runs" && parts[3]) {
    return {
      clientId,
      runId: decodeURIComponent(parts[3]),
      view: "matrix",
    };
  }

  const view = VIEWS.has(parts[2]) ? parts[2] : "matrix";
  return { clientId, runId: null, view };
}

export function buildAppPath({ clientId, runId, view = "matrix" } = {}) {
  if (!clientId) return "/";
  const base = `/w/${encodeURIComponent(clientId)}`;
  if (runId) return `${base}/runs/${encodeURIComponent(runId)}`;
  if (view && view !== "matrix") return `${base}/${view}`;
  return base;
}

export function replaceAppPath(state) {
  const next = buildAppPath(state);
  const current = `${window.location.pathname}${window.location.search}`;
  if (current !== next) {
    window.history.replaceState(null, "", next);
  }
}

export function pushAppPath(state) {
  const next = buildAppPath(state);
  const current = `${window.location.pathname}${window.location.search}`;
  if (current !== next) {
    window.history.pushState(null, "", next);
  }
}
