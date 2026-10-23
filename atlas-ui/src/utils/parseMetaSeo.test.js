import { describe, expect, test } from "vitest";
import { parseMetaSeoOptionLines, parseMetaSeoStructured } from "./parseMetaSeo";

describe("parseMetaSeo", () => {
  test("strips em dashes from option text and recounts characters", () => {
    const options = parseMetaSeoOptionLines(
      "  1. Book an online visit — skip the wait (40 characters)\n"
    );
    expect(options).toHaveLength(1);
    expect(options[0].text).toBe("Book an online visit: skip the wait");
    expect(options[0].text).not.toMatch(/[\u2013\u2014]/);
    expect(options[0].charCount).toBe(options[0].text.length);
  });

  test("parseMetaSeoStructured cleans description options", () => {
    const parsed = parseMetaSeoStructured(
      [
        "---META SEO START---",
        "PAGE TYPE: blog page",
        "TARGET KEYWORD: ai automation services",
        "META TITLE OPTIONS (50-60 characters):",
        "  1. AI automation services: complete guide (42 characters)",
        "META DESCRIPTION OPTIONS (120-155 characters):",
        "  1. See what agencies actually build — and what they charge (58 characters)",
        "---META SEO END---",
      ].join("\n")
    );
    expect(parsed.descriptionOptions[0].text).toContain("build: and");
    expect(parsed.descriptionOptions[0].text).not.toMatch(/[\u2013\u2014]/);
  });
});
