import { describe, expect, test } from "vitest";
import { parseBrief } from "./parseBrief";
import { parseGapRecords, parseH2Sections } from "./parseH2Sections";
import {
  parseOutlineStructured,
  parseWordCountRange,
  summarizeOutlineWordBudgets,
} from "./parseOutlineStructured";
import { parseResearch } from "./parseResearch";

describe("parseBrief", () => {
  test("parses brief fields", () => {
    const fields = parseBrief(`
---BRIEF START---
ARTICLE TITLE: Hello world
PRIMARY KEYWORD: hello
WHAT THIS ARTICLE MUST DO:
  - One
  - Two
---BRIEF END---
`);
    expect(fields).toBeTruthy();
    expect(fields.find((f) => f.key === "ARTICLE TITLE").value).toBe(
      "Hello world"
    );
    expect(fields.find((f) => f.key === "WHAT THIS ARTICLE MUST DO").value).toContain(
      "One"
    );
  });
});

describe("parseH2Sections + gaps", () => {
  test("splits ## sections and gap triples", () => {
    const sections = parseH2Sections(
      `---SERP ANALYSIS START---
## Snapshot
- A
## Content gaps to own
GAP: Missing proof
WHY IT MATTERS: Readers need evidence.
HOW WE WIN: Add a case study.
---SERP ANALYSIS END---`,
      { startMarker: "SERP ANALYSIS START", endMarker: "SERP ANALYSIS END" }
    );
    expect(sections).toHaveLength(2);
    expect(sections[0].heading).toBe("Snapshot");
    const gaps = parseGapRecords(sections[1].body);
    expect(gaps).toHaveLength(1);
    expect(gaps[0].gap).toContain("Missing proof");
    expect(gaps[0].how).toContain("case study");
  });
});

describe("parseResearch", () => {
  test("attaches gap cards", () => {
    const data = parseResearch(`
---SERP ANALYSIS START---
## Content gaps to own
GAP: Alpha
WHY IT MATTERS: Beta
HOW WE WIN: Gamma
---SERP ANALYSIS END---
`);
    expect(data.sections[0].gaps).toHaveLength(1);
  });
});

describe("parseOutlineStructured", () => {
  test("parses h1 and h2 blocks", () => {
    const data = parseOutlineStructured(`
---OUTLINE START---
H1: Sample title
INTRO NOTE: Open with pain.
H2: First section
  PURPOSE: Teach setup
  KEY POINTS:
    - Point A
  WORD COUNT: 200–250 words
H2: Frequently Asked Questions
  PURPOSE: Answer objections
  WORD COUNT: 300 words
CONCLUSION NOTE: Close with next step.
TOTAL ESTIMATED WORD COUNT: 2200
---OUTLINE END---
`);
    expect(data.h1).toBe("Sample title");
    expect(data.introNote).toContain("pain");
    expect(data.sections.length).toBeGreaterThanOrEqual(2);
    expect(data.sections[0].title).toBe("First section");
    expect(data.sections[0].fields.PURPOSE).toContain("Teach");
    expect(data.totalWords).toBe("2200");
  });

  test("summarizes section word budgets", () => {
    expect(parseWordCountRange("180–220 words")).toBe(200);
    const data = parseOutlineStructured(`
---OUTLINE START---
H1: T
H2: A
  WORD COUNT: 200–250 words
H2: B
  PURPOSE: x
TOTAL ESTIMATED WORD COUNT: 2200
---OUTLINE END---
`);
    const summary = summarizeOutlineWordBudgets(data);
    expect(summary.missingTitles).toContain("B");
    expect(summary.sumMid).toBeGreaterThan(0);
    expect(summary.ok).toBe(false);
  });
});
