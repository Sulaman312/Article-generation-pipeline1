import { canRunStep, inputSourceForStep } from "./pipelineFlow";

const ALL_DONE = {
  topic_card: "done",
  serp_research: "done",
  research: "done",
  atp_topic_research: "done",
  paa_faq_research: "done",
  case_study_research: "done",
  research_audit: "done",
  assignment_brief: "done",
  outline: "done",
  draft: "done",
  supporting_posts: "done",
  fact_check: "done",
  meta_seo: "done",
  final_output: "pending",
};

describe("inputSourceForStep", () => {
  test("final_output uses fact_check, not meta_seo", () => {
    const src = inputSourceForStep("final_output", ALL_DONE);
    expect(src).toEqual({ kind: "artifact", stepKey: "fact_check" });
  });

  test("final_output still resolves fact_check when meta_seo is pending", () => {
    const src = inputSourceForStep("final_output", {
      ...ALL_DONE,
      meta_seo: "pending",
    });
    expect(src).toEqual({ kind: "artifact", stepKey: "fact_check" });
  });

  test("meta_seo still takes fact_check as its input", () => {
    const src = inputSourceForStep("meta_seo", {
      ...ALL_DONE,
      meta_seo: "pending",
      final_output: "pending",
    });
    expect(src).toEqual({ kind: "artifact", stepKey: "fact_check" });
  });

  test("draft still takes outline as its input", () => {
    const src = inputSourceForStep("draft", {
      ...ALL_DONE,
      draft: "pending",
      supporting_posts: "pending",
      fact_check: "pending",
      meta_seo: "pending",
      final_output: "pending",
    });
    expect(src).toEqual({ kind: "artifact", stepKey: "outline" });
  });

  test("fact_check skips supporting_posts sidecar and uses draft", () => {
    const src = inputSourceForStep("fact_check", ALL_DONE);
    expect(src).toEqual({ kind: "artifact", stepKey: "draft" });
  });
});

describe("canRunStep", () => {
  test("final_output can run once fact_check is done even if meta is pending", () => {
    expect(
      canRunStep(
        "final_output",
        { ...ALL_DONE, meta_seo: "pending" },
        "Some topic"
      )
    ).toBe(true);
  });
});
