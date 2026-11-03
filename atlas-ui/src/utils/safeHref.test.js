import { describe, expect, test } from "vitest";
import { sanitizeHref } from "./safeHref";

describe("sanitizeHref", () => {
  test("allows http and https", () => {
    expect(sanitizeHref("https://example.com/a")).toBe(
      "https://example.com/a"
    );
    expect(sanitizeHref("http://example.com")).toBe("http://example.com");
  });

  test("allows mailto", () => {
    expect(sanitizeHref("mailto:a@b.com")).toBe("mailto:a@b.com");
  });

  test("blocks javascript and data URLs", () => {
    expect(sanitizeHref("javascript:alert(1)")).toBeNull();
    expect(sanitizeHref("data:text/html,<script>")).toBeNull();
    expect(sanitizeHref("vbscript:msg")).toBeNull();
    expect(sanitizeHref("//evil.example")).toBeNull();
  });
});
