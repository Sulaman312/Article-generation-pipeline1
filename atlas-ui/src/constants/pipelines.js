import { PIPELINE_STEPS } from "./pipeline";

export const PIPELINE_IDS = {
  ARTICLE: "article",
};

export function stepsForPipeline() {
  return PIPELINE_STEPS;
}

export function stepKeysForPipeline() {
  return PIPELINE_STEPS.map((s) => s.key);
}
