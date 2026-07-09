/** HTTP client for the ArticleGen Flask API.
 *
 * In production, the React build is served by Flask, so API calls use the same origin.
 * Override with `REACT_APP_API_URL` (no trailing slash) for local dev or split deployments.
 */

const DEFAULT_BASE = "";

const envUrlRaw =
  typeof process !== "undefined"
    ? (process.env.REACT_APP_API_URL || "").trim()
    : "";

function resolveApiBase() {
  if (envUrlRaw) return envUrlRaw.replace(/\/$/, "");
  if (process.env.NODE_ENV === "development") {
    return "http://127.0.0.1:8000";
  }
  return DEFAULT_BASE;
}

const BASE = resolveApiBase();

function isLocalBrowser() {
  if (typeof window === "undefined") return false;
  return ["localhost", "127.0.0.1", "::1"].includes(window.location.hostname);
}

function apiUnavailableMessage() {
  if (isLocalBrowser()) {
    return `Could not reach API at ${BASE || "same origin"}. From the repo root run: python main.py — then use the UI at http://localhost:3000`;
  }
  return `The deployed API at ${BASE || "the same origin"} could not be reached. The service may be restarting or temporarily unavailable; check the Koyeb service logs and health status.`;
}

const REQUEST_TIMEOUT_MS = 30000;
/** Pipeline LLM steps can take several minutes. */
const STEP_REQUEST_TIMEOUT_MS = 900000;
const STEP_POLL_INTERVAL_MS = 2000;

function delay(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new Error("Stopped by user."));
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    function onAbort() {
      clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
      reject(new Error("Stopped by user."));
    }
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

export const DEV_FLASK_ORIGIN = BASE;

/** URL for a run's optional logo image (404 if none). */
export function runLogoUrl(clientId, runId) {
  return `${BASE}/clients/${encodeURIComponent(clientId)}/runs/${encodeURIComponent(
    runId
  )}/logo`;
}

/** Human-readable target (for UI error banners). */
export function describeApiTargetForHumans() {
  return BASE || "same origin";
}

/** Flask-style `detail` (string | object | ValidationError-ish list). */
function formatDetail(detail) {
  if (detail == null) return null;
  if (typeof detail === "string") return detail.trim() || null;
  if (Array.isArray(detail)) {
    const parts = [];
    for (const item of detail) {
      if (item == null) continue;
      if (typeof item === "string") parts.push(item);
      else if (typeof item?.msg === "string") parts.push(item.msg);
      else parts.push(JSON.stringify(item));
    }
    const joined = parts.filter(Boolean).join("; ").trim();
    return joined || null;
  }
  if (typeof detail === "object" && typeof detail.msg === "string")
    return detail.msg.trim() || null;
  try {
    const s = JSON.stringify(detail);
    return s && s !== "{}" ? s : null;
  } catch {
    return String(detail);
  }
}

async function request(path, options = {}) {
  const userSignal = options.signal;
  const timeoutMs =
    options.timeoutMs === 0
      ? null
      : options.timeoutMs ?? REQUEST_TIMEOUT_MS;
  const { signal: _omitSignal, timeoutMs: _omitTimeout, ...fetchOptions } =
    options;
  const controller = new AbortController();
  const timer =
    timeoutMs == null ? null : setTimeout(() => controller.abort(), timeoutMs);

  function onUserAbort() {
    controller.abort();
  }
  if (userSignal) {
    if (userSignal.aborted) {
      clearTimeout(timer);
      throw new Error("Stopped by user.");
    }
    userSignal.addEventListener("abort", onUserAbort);
  }

  try {
    const res = await fetch(`${BASE}${path}`, {
      ...fetchOptions,
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(fetchOptions.headers || {}),
      },
    });
    const bodyText = await res.text().catch(() => "");

    if (!res.ok) {
      const verb = fetchOptions.method || "GET";
      const prefix = `${verb} ${path} failed (${res.status})`;
      let message = `${prefix}`;
      try {
        const t = bodyText.trimStart();
        if (t.startsWith("{")) {
          const parsed = JSON.parse(bodyText);
          const d = formatDetail(parsed.detail);
          if (d) message = d;
          else message = `${prefix}. ${bodyText.slice(0, 400)}`;
        } else message = `${prefix}. ${bodyText.slice(0, 400)}`;
      } catch {
        message = `${prefix}. ${bodyText.slice(0, 400)}`;
      }
      throw new Error(message.trim());
    }
    if (res.status === 204 || bodyText.trim() === "") return null;

    const trimmed = bodyText.trimStart();
    if (trimmed.startsWith("<")) {
      throw new Error(
        `API returned HTML instead of JSON (${path}). Start Flask: python main.py (repo root). ` +
          `Then open ${DEFAULT_BASE}${path} in a tab — you should see JSON. ` +
          `Use the UI at http://localhost:3000 (npm start in atlas-ui), not port 8000.`
      );
    }

    try {
      return JSON.parse(bodyText);
    } catch (_) {
      throw new Error(
        `Invalid JSON from ${path} (starts: ${bodyText.slice(0, 96).replace(/\s+/g, " ")}…)`
      );
    }
  } catch (e) {
    if (e?.name === "AbortError") {
      if (userSignal?.aborted) {
        throw new Error("Stopped by user.");
      }
      const secs = (timeoutMs ?? REQUEST_TIMEOUT_MS) / 1000;
      throw new Error(
        `Request timed out (${secs}s). Is Flask listening at ${BASE}? Run from repo root: python main.py`
      );
    }
    const raw = e?.message || String(e);
    if (raw === "Failed to fetch" || e?.name === "TypeError") {
      throw new Error(apiUnavailableMessage());
    }
    throw e;
  } finally {
    if (timer != null) clearTimeout(timer);
    if (userSignal) userSignal.removeEventListener("abort", onUserAbort);
  }
}

export async function getClients() {
  const data = await request("/clients");
  const rows = data.clients ?? [];
  return rows.map((c) => {
    if (typeof c === "string") {
      return { id: c, display_name: c };
    }
    return {
      id: c.id,
      display_name: c.display_name || c.id,
    };
  });
}

export async function createClient(clientId, options = null) {
  const body =
    options && typeof options === "object"
      ? {
          ...(options.display_name
            ? { display_name: options.display_name }
            : {}),
          ...(options.logo_base64 ? { logo_base64: options.logo_base64 } : {}),
          ...(options.logo_filename
            ? { logo_filename: options.logo_filename }
            : {}),
        }
      : {};
  return request(`/clients/${encodeURIComponent(clientId)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** URL for a workspace logo (404 if none). */
export function clientLogoUrl(clientId) {
  return `${BASE}/clients/${encodeURIComponent(clientId)}/logo`;
}

export async function uploadClientLogo(clientId, logoBase64, logoFilename) {
  return request(`/clients/${encodeURIComponent(clientId)}/logo`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      logo_base64: logoBase64,
      logo_filename: logoFilename,
    }),
  });
}

export async function getRuns(clientId) {
  const data = await request(`/clients/${encodeURIComponent(clientId)}/runs`);
  return data.runs ?? [];
}

/** Create a run from manual editorial fields and/or a topic string. */
export async function createRun(clientId, topic, options = null) {
  const body = {};
  if (topic && String(topic).trim()) body.topic = String(topic).trim();
  if (options && typeof options === "object") {
    if (options.pipeline_id) body.pipeline_id = options.pipeline_id;
    if (options.manual_inputs) body.manual_inputs = options.manual_inputs;
    if (options.semrush_notes) body.semrush_notes = options.semrush_notes;
    if (options.logo_base64) body.logo_base64 = options.logo_base64;
    if (options.logo_filename) body.logo_filename = options.logo_filename;
  }
  return request(`/clients/${encodeURIComponent(clientId)}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** archive | unarchive | delete (POST/DELETE — avoids PATCH CORS issues in dev). */
export async function runArticleAction(clientId, runId, action) {
  const path = `/clients/${encodeURIComponent(clientId)}/runs/${encodeURIComponent(
    runId
  )}`;
  if (action === "archive") {
    return request(`${path}/archive`, { method: "POST" });
  }
  if (action === "unarchive") {
    return request(`${path}/unarchive`, { method: "POST" });
  }
  if (action === "delete") {
    return request(path, { method: "DELETE" });
  }
  throw new Error(`Unknown action: ${action}`);
}

export async function archiveRun(clientId, runId) {
  return runArticleAction(clientId, runId, "archive");
}

export async function unarchiveRun(clientId, runId) {
  return runArticleAction(clientId, runId, "unarchive");
}

export async function deleteRun(clientId, runId) {
  return runArticleAction(clientId, runId, "delete");
}

export async function getRun(clientId, runId, signal = null) {
  return request(
    `/clients/${encodeURIComponent(clientId)}/runs/${encodeURIComponent(runId)}`,
    { signal }
  );
}

async function waitForStep(clientId, runId, stepName, signal) {
  const deadline = Date.now() + STEP_REQUEST_TIMEOUT_MS;
  let consecutiveFailures = 0;
  while (Date.now() < deadline) {
    await delay(STEP_POLL_INTERVAL_MS, signal);
    let run;
    try {
      run = await getRun(clientId, runId, signal);
      consecutiveFailures = 0;
    } catch (error) {
      const message = error?.message || String(error);
      if (message === "Stopped by user.") throw error;
      consecutiveFailures += 1;
      if (consecutiveFailures >= 3) throw error;
      continue;
    }
    const status = run?.statuses?.[stepName] || "pending";
    if (status === "done") return run;
    if (status === "error") {
      throw new Error(
        run?.step_errors?.[stepName] || `Step ${stepName} failed.`
      );
    }
    if (status === "pending" || status === "skipped") {
      throw new Error(`Step ${stepName} was cancelled.`);
    }
  }
  throw new Error(`Step ${stepName} did not finish within 15 minutes.`);
}

export async function getArtifact(clientId, runId, stepName) {
  const data = await request(
    `/clients/${encodeURIComponent(clientId)}/runs/${encodeURIComponent(
      runId
    )}/artifacts/${encodeURIComponent(stepName)}`
  );
  return data.content ?? "";
}

/** FAQ + external links (fast). Pass full=true for word-count trim (~1–3 min). */
export async function repairFinalOutput(clientId, runId, { full = false } = {}) {
  const q = full ? "?full=1" : "";
  const paths = [
    `/clients/${encodeURIComponent(clientId)}/runs/${encodeURIComponent(
      runId
    )}/final-output/repair${q}`,
    `/clients/${encodeURIComponent(clientId)}/runs/${encodeURIComponent(
      runId
    )}/artifacts/final_output/repair${q}`,
  ];
  let lastErr;
  for (const path of paths) {
    try {
      const data = await request(path, {
        method: "POST",
        timeoutMs: STEP_REQUEST_TIMEOUT_MS,
      });
      const content = (data?.content ?? "").trim();
      if (content.length < 200) {
        throw new Error(
          "Repair returned empty content — restart python main.py and try again."
        );
      }
      return content;
    } catch (e) {
      lastErr = e;
      if (!String(e?.message || "").includes("404")) throw e;
    }
  }
  throw lastErr || new Error("Repair endpoint not found — restart python main.py");
}

export async function saveArtifact(clientId, runId, stepName, content) {
  return request(
    `/clients/${encodeURIComponent(clientId)}/runs/${encodeURIComponent(
      runId
    )}/artifacts/${encodeURIComponent(stepName)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    }
  );
}

export async function runStep(
  clientId,
  runId,
  stepName,
  previousArtifact,
  signal
) {
  const result = await request(
    `/clients/${encodeURIComponent(clientId)}/runs/${encodeURIComponent(
      runId
    )}/steps/${encodeURIComponent(stepName)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ previous_artifact: previousArtifact }),
      signal,
      timeoutMs: STEP_REQUEST_TIMEOUT_MS,
    }
  );
  if (result?.accepted) {
    await waitForStep(clientId, runId, stepName, signal);
  }
  return result;
}

export async function cancelStep(clientId, runId, stepName) {
  const path = `/clients/${encodeURIComponent(clientId)}/runs/${encodeURIComponent(
    runId
  )}/steps/${encodeURIComponent(stepName)}/cancel`;
  try {
    return await request(path, { method: "POST" });
  } catch (e) {
    const msg = e?.message || "";
    if (!msg.includes("(404)")) throw e;
    return request(
      `/clients/${encodeURIComponent(clientId)}/runs/${encodeURIComponent(runId)}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "cancel_step", step_name: stepName }),
      }
    );
  }
}

export async function runFullPipeline(clientId, topic) {
  return request(`/clients/${encodeURIComponent(clientId)}/pipeline`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic }),
  });
}

export async function getContextSummary(clientId) {
  const data = await request(
    `/clients/${encodeURIComponent(clientId)}/context-summary`
  );
  return data.summary ?? "";
}

export async function updateClient(clientId, { display_name }) {
  return request(`/clients/${encodeURIComponent(clientId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ display_name }),
  });
}

export async function deleteClient(clientId) {
  return request(`/clients/${encodeURIComponent(clientId)}`, {
    method: "DELETE",
  });
}

export async function listContextFiles(clientId) {
  const data = await request(
    `/clients/${encodeURIComponent(clientId)}/context-files`
  );
  return data.files ?? [];
}

export async function getContextFile(clientId, filename) {
  return request(
    `/clients/${encodeURIComponent(clientId)}/context-files/${encodeURIComponent(
      filename
    )}`
  );
}

export async function saveContextFile(clientId, filename, content) {
  return request(
    `/clients/${encodeURIComponent(clientId)}/context-files/${encodeURIComponent(
      filename
    )}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    }
  );
}

export async function listWorkspaceArtifacts(clientId) {
  const data = await request(
    `/clients/${encodeURIComponent(clientId)}/workspace-artifacts`
  );
  return data.artifacts ?? [];
}

export async function createWorkspaceArtifact(clientId, payload) {
  const data = await request(
    `/clients/${encodeURIComponent(clientId)}/workspace-artifacts`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
  return data.artifact;
}

export async function deleteWorkspaceArtifact(clientId, filename) {
  return request(
    `/clients/${encodeURIComponent(clientId)}/workspace-artifacts/${encodeURIComponent(
      filename
    )}`,
    { method: "DELETE" }
  );
}

/** Pipeline-ordered filenames + labels; single source aligned with Flask `CONTEXT_FILES_CATALOG`. */
export async function getContextFilesCatalog() {
  const data = await request("/context-files/catalog");
  return Array.isArray(data.files) ? data.files : [];
}

/** Canonical article pipeline steps (order + labels). */
export async function getPipelineSteps() {
  return request("/pipeline/steps");
}
