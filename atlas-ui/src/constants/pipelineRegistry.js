import { PIPELINE_STEPS as FALLBACK_PIPELINE_STEPS } from "./pipeline";

let activeSteps = FALLBACK_PIPELINE_STEPS;

/** Current pipeline steps (hydrated from API when available). */
export function getPipelineSteps() {
  return activeSteps;
}

export function getPipelineStepKeys() {
  return activeSteps.map((step) => step.key);
}

function mergeSteps(remoteSteps) {
  const fallbackByKey = Object.fromEntries(
    FALLBACK_PIPELINE_STEPS.map((step) => [step.key, step])
  );
  return remoteSteps.map((remote) => {
    const fallback = fallbackByKey[remote.key] || {};
    return {
      key: remote.key,
      index: remote.index ?? fallback.index,
      label: remote.label || fallback.label || remote.key,
      matrixLabel: remote.matrixLabel || fallback.matrixLabel || remote.label,
      matrixCol: remote.matrixCol || fallback.matrixCol || "",
    };
  });
}

/** Load canonical step order from the API; keep local fallback on failure. */
export async function hydratePipelineSteps(api) {
  try {
    const data = await api.getPipelineSteps();
    if (Array.isArray(data?.steps) && data.steps.length > 0) {
      activeSteps = mergeSteps(data.steps);
    }
  } catch {
    activeSteps = FALLBACK_PIPELINE_STEPS;
  }
  return activeSteps;
}

/** Reset to bundled fallback (tests). */
export function resetPipelineStepsForTests() {
  activeSteps = FALLBACK_PIPELINE_STEPS;
}
