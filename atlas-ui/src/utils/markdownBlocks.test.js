import { describe, expect, test } from "vitest";
import { parseBlocks } from "./markdownBlocks";

const SHELL = `<div class="x">
<h3>Hi</h3>
</div>

<style>
.x{color:red}
</style>`;

describe("parseBlocks fenced CTA shell", () => {
  test("unclosed ```html fence does not turn the rest of the article into code", () => {
    const blocks = parseBlocks(
      `## A\n\nText\n\n\`\`\`html\n${SHELL}\n\n## HR automation\n\nBody text.\n`
    );
    expect(blocks.some((b) => b.type === "code")).toBe(false);
    expect(blocks.some((b) => b.type === "html")).toBe(true);
    expect(
      blocks.some((b) => b.type === "heading" && b.text === "HR automation")
    ).toBe(true);
  });

  test("real code fences are still code", () => {
    const blocks = parseBlocks("```python\nprint('x')\n```\n");
    expect(blocks[0].type).toBe("code");
  });
});
