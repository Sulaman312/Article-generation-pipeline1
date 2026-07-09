import { getPipelineSteps, getPipelineStepKeys } from "./pipelineRegistry";

export const PIPELINE_IDS = {
  ARTICLE: "article",
};

export function stepsForPipeline() {
  return getPipelineSteps();
}

export function stepKeysForPipeline() {
  return getPipelineStepKeys();
}
