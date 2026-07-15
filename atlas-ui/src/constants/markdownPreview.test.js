import {
  ensureStepBoundaryMarkers,
  formatStepBoundaryLabel,
  isStepBoundaryMarker,
  normalizePipelineMarkdown,
  normalizeStepArtifactMarkdown,
  STEP_MARKER_LABELS,
} from "./markdownPreview";

describe("step boundary markers", () => {
  test("detects canonical start/end labels", () => {
    expect(isStepBoundaryMarker("SERP ANALYSIS START")).toBe(true);
    expect(isStepBoundaryMarker("SERP ANALYSIS END")).toBe(true);
    expect(isStepBoundaryMarker("OUTLINE START")).toBe(true);
    expect(isStepBoundaryMarker("FACT CHECK REPORT START")).toBe(false);
  });

  test("formats start and end labels consistently", () => {
    expect(formatStepBoundaryLabel("serp analysis start")).toBe(
      "SERP Analysis Start"
    );
    expect(formatStepBoundaryLabel("SERP ANALYSIS END")).toBe(
      "SERP Analysis End"
    );
    expect(formatStepBoundaryLabel("---BRIEF START---")).toBe("Brief Start");
    expect(formatStepBoundaryLabel("META SEO START")).toBe("META SEO Start");
  });

  test("every step key has a display label", () => {
    const keys = Object.keys(STEP_MARKER_LABELS);
    expect(keys.length).toBeGreaterThanOrEqual(9);
    for (const key of keys) {
      const wrapped = ensureStepBoundaryMarkers("Body copy", key);
      expect(wrapped).toContain("START---");
      expect(wrapped).toContain("END---");
    }
  });

  test("normalizeStepArtifactMarkdown keeps fact-check start/end chrome", () => {
    const raw = [
      "---PERPLEXITY WEB FACT-CHECK (raw audit trail)---",
      "signals",
      "---FACT CHECK START---",
      "corrected body",
      "---FACT CHECK END---",
    ].join("\n");
    const out = normalizeStepArtifactMarkdown(raw, "fact_check");
    expect(out).toContain("---FACT CHECK START---");
    expect(out).toContain("---FACT CHECK END---");
    expect(out).toContain("corrected body");
    expect(out).not.toContain("PERPLEXITY WEB FACT-CHECK");
  });

  test("preserves step boundaries during normalization", () => {
    const raw = [
      "---SERP ANALYSIS START---",
      "## Snapshot",
      "- gap one",
      "---SERP ANALYSIS END---",
    ].join("\n");
    const out = normalizePipelineMarkdown(raw);
    expect(out).toContain("---SERP ANALYSIS START---");
    expect(out).toContain("---SERP ANALYSIS END---");
    expect(out).toContain("## Snapshot");
  });

  test("still strips internal fact-check sub-section markers", () => {
    const raw = [
      "---FACT CHECK START---",
      "---FACT CHECK REPORT START---",
      "report body",
      "---FACT CHECK REPORT END---",
      "---FACT CHECK END---",
    ].join("\n");
    const out = normalizePipelineMarkdown(raw);
    expect(out).toContain("---FACT CHECK START---");
    expect(out).toContain("---FACT CHECK END---");
    expect(out).not.toContain("FACT CHECK REPORT START");
  });
});
