import { stepKeysForPipeline } from "../constants/pipelines";

/** @typedef {{ kind: 'artifact', stepKey: string } | { kind: 'topic' } | { kind: 'blocked' }} InputSource */

/**
 * Publishing-only steps that must not become LLM / Input-tab fodder for later
 * content steps. Meta SEO sits beside the article (Final Output → Metadata).
 */
const PUBLISHING_SIDECAR_STEPS = new Set(["meta_seo"]);

/**
 * Whether `candidate` is a valid article input for `stepKey`.
 * Meta title & description feed the Metadata panel, not final_output's body.
 */
function isArticleInputForStep(stepKey, candidate) {
  if (stepKey === "final_output" && PUBLISHING_SIDECAR_STEPS.has(candidate)) {
    return false;
  }
  return true;
}

/** @param {string} stepKey @param {Record<string, string>} statuses @returns {InputSource} */
export function inputSourceForStep(stepKey, statuses, pipelineId = null) {
  const keys = stepKeysForPipeline(pipelineId);
  const idx = keys.indexOf(stepKey);
  if (idx < 0) return { kind: "blocked" };

  for (let i = idx - 1; i >= 0; i -= 1) {
    const prev = keys[i];
    if (!isArticleInputForStep(stepKey, prev)) continue;
    const st = statuses[prev] || "pending";
    if (st === "done") return { kind: "artifact", stepKey: prev };
    if (st === "skipped") continue;
    return { kind: "blocked" };
  }
  return { kind: "topic" };
}

export function canRunStep(stepKey, statuses, topic, pipelineId = null) {
  const src = inputSourceForStep(stepKey, statuses, pipelineId);
  if (src.kind === "blocked") return false;
  if (src.kind === "topic") return Boolean(String(topic || "").trim());
  return true;
}
