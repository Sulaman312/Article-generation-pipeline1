import { stepsForPipeline } from "../constants/pipelines";
import { inputSourceForStep } from "./pipelineFlow";

/** Load prior input and execute a pipeline step. */
export async function executeRunStep(
  api,
  client,
  runId,
  stepKey,
  topic,
  statuses,
  signal,
  pipelineId = null
) {
  const src = inputSourceForStep(stepKey, statuses, pipelineId);
  let previous = "";
  if (src.kind === "topic") {
    previous = topic || "";
  } else if (src.kind === "artifact") {
    previous = await api.getArtifact(client, runId, src.stepKey);
  } else {
    throw new Error("Complete earlier steps first.");
  }
  await api.runStep(client, runId, stepKey, previous, signal);
  const steps = stepsForPipeline(pipelineId);
  return steps.find((s) => s.key === stepKey);
}
