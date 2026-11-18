import { describe, expect, test } from "vitest";
import { parseFactCheckReport } from "./parseFactCheck";

const SAMPLE = `
---FACT CHECK START---
---FACT CHECK REPORT START---
OVERALL ASSESSMENT: MINOR ISSUES
TOTAL ISSUES FOUND: 2

ISSUES FOUND:
  ISSUE #: 1
  LOCATION: Les rappels par WhatsApp réduisent les no-shows de 50 à 70 %.
  ISSUE TYPE: fabricated statistic
  ACTION TAKEN: corrected in article
  CORRECTION OR FLAG: Softened to "réduisent significativement" — no source for 50–70%.

  ISSUE #: 2
  LOCATION: Tous les patients préfèrent le SMS.
  ISSUE TYPE: overgeneralization
  ACTION TAKEN: flagged for human review
  CORRECTION OR FLAG: Needs a named source before publishing.

ITEMS FLAGGED FOR HUMAN REVIEW:
1. Verify SMS preference claim with a real survey.

COMPANY CLAIM REVIEW:
NOT CHECKED — Company Context not provided.
---FACT CHECK REPORT END---

---CORRECTED ARTICLE START---
# Title

Corrected body.
---CORRECTED ARTICLE END---
---FACT CHECK END---
`;

describe("parseFactCheckReport", () => {
  test("parses assessment, issues, and corrected article", () => {
    const data = parseFactCheckReport(SAMPLE);
    expect(data).toBeTruthy();
    expect(data.overallAssessment).toBe("MINOR ISSUES");
    expect(data.totalIssues).toBe("2");
    expect(data.issues).toHaveLength(2);
    expect(data.issues[0].issueType).toBe("fabricated statistic");
    expect(data.issues[0].location).toContain("WhatsApp");
    expect(data.issues[1].actionTaken).toContain("flagged");
    expect(data.humanReview).toContain("SMS preference");
    expect(data.companyClaimReview).toContain("NOT CHECKED");
    expect(data.correctedArticle).toContain("Corrected body");
  });

  test("handles clean report with no issues", () => {
    const data = parseFactCheckReport(`
---FACT CHECK REPORT START---
OVERALL ASSESSMENT: CLEAN
TOTAL ISSUES FOUND: 0
ISSUES FOUND:
NO FACTUAL ISSUES IDENTIFIED
---FACT CHECK REPORT END---
---CORRECTED ARTICLE START---
Hello
---CORRECTED ARTICLE END---
`);
    expect(data.noIssues).toBe(true);
    expect(data.issues).toHaveLength(0);
    expect(data.correctedArticle.trim()).toBe("Hello");
  });
});
