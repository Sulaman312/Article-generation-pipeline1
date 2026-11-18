import {
  copyFormattedMarkdown,
  markdownToHtml,
  markdownToPlainText,
} from "./markdownExport";

describe("markdownToHtml", () => {
  test("keeps headings, bold, lists, and links", () => {
    const md = [
      "# Title",
      "",
      "This has **bold** and *italic*.",
      "",
      "- One",
      "- Two with [link](https://example.com)",
      "",
      "## Section",
      "",
      "1. First",
      "2. Second",
    ].join("\n");

    const html = markdownToHtml(md);
    expect(html).toContain("<h1");
    expect(html).toContain("Title");
    expect(html).toContain("<strong>bold</strong>");
    expect(html).toContain("<em>italic</em>");
    expect(html).toContain("<ul");
    expect(html).toContain('<a href="https://example.com">link</a>');
    expect(html).toContain("<h2");
    expect(html).toContain("<ol");
  });
});

describe("markdownToPlainText", () => {
  test("flattens markdown without markers", () => {
    expect(markdownToPlainText("**Hi** world")).toContain("Hi world");
  });
});

describe("copyFormattedMarkdown", () => {
  test("writes html and markdown plain payload when ClipboardItem is available", async () => {
    const written = [];
    const ClipboardItemMock = function (items) {
      this.items = items;
    };
    globalThis.ClipboardItem = ClipboardItemMock;
    const write = vi.fn(async (items) => {
      written.push(items);
    });
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { write },
    });

    const md = "# Hello\n\n**World**";
    const ok = await copyFormattedMarkdown(md);
    expect(ok).toBe(true);
    expect(write).toHaveBeenCalledTimes(1);
    const item = written[0][0];
    expect(item.items["text/plain"]).toBeInstanceOf(Blob);
    expect(item.items["text/html"]).toBeInstanceOf(Blob);
    expect(item.items["text/plain"].type).toBe("text/plain");
    expect(item.items["text/html"].type).toBe("text/html");
    expect(item.items["text/plain"].size).toBeGreaterThan(0);
    expect(item.items["text/html"].size).toBeGreaterThan(0);
    // Content fidelity covered by markdownToHtml above.
    expect(markdownToHtml(md)).toContain("<strong>World</strong>");
  });
});
