import { getPipelineSteps, getPipelineStepKeys } from "./pipelineRegistry";

export function stepsForPipeline() {
  return getPipelineSteps();
}

export function stepKeysForPipeline() {
  return getPipelineStepKeys();
}
