import { describe, expect, test } from "vitest";
import { manualInputsToDisplayFields } from "./editorialFields";

describe("manualInputsToDisplayFields", () => {
  test("maps snake_case and label keys into ordered rows", () => {
    const rows = manualInputsToDisplayFields({
      topic: "Reduce no-shows",
      seed_keyword: "vet no show",
      "Word Count": "2000",
      notes: "Write in English",
    });
    expect(rows.map((r) => r.label)).toEqual([
      "Topic",
      "Seed Keyword",
      "Word Count",
      "Notes",
    ]);
    expect(rows.find((r) => r.key === "seed_keyword").value).toBe("vet no show");
  });

  test("returns empty for missing inputs", () => {
    expect(manualInputsToDisplayFields(null)).toEqual([]);
    expect(manualInputsToDisplayFields({})).toEqual([]);
  });
});
