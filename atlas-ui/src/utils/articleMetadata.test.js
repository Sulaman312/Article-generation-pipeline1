import { describe, expect, test } from "vitest";
import {
  buildFinalOutputMetadata,
  countMarkdownLinks,
} from "./articleMetadata";

describe("articleMetadata", () => {
  test("counts internal and external links", () => {
    const md = [
      "[Home](/path)",
      "[Guide](https://example.com/a)",
      "[Mail](mailto:a@b.com)",
    ].join("\n");
    expect(countMarkdownLinks(md)).toEqual({
      internal: 1,
      external: 1,
      other: 1,
      total: 3,
    });
  });

  test("builds metadata with French FAQ and meta SEO picks", () => {
    const article = [
      "# Title",
      "",
      "Body paragraph with an [external](https://ex.com) link.",
      "",
      "## Questions fréquentes",
      "",
      "### Q one?",
      "",
      "A one.",
      "",
      "### Q two?",
      "",
      "A two.",
    ].join("\n");
    const metaSeo = [
      "---META SEO START---",
      "PAGE TYPE: Blog",
      "TARGET KEYWORD: veterinaires",
      "",
      "META TITLE OPTIONS (50-60 characters):",
      "1. Best title here (50 characters)",
      "2. Other title here (48 characters)",
      "",
      "META DESCRIPTION OPTIONS (120-155 characters):",
      "1. Recommended description text that fits. (120 characters)",
      "---META SEO END---",
    ].join("\n");

    const data = buildFinalOutputMetadata(article, metaSeo, {
      targetWordCount: 2200,
    });
    expect(data.faqCount).toBe(2);
    expect(data.links.external).toBe(1);
    expect(data.recommendedTitle?.text).toContain("Best title");
    expect(data.recommendedDescription?.text).toContain("Recommended");
    expect(data.targetWordCount).toBe(2200);
    expect(data.bodyStats.words).toBeGreaterThan(0);
  });
});
