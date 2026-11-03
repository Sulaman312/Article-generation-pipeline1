/**
 * Parse fact-check artifact report into structured fields for UI rendering.
 */

const REPORT_START = /---FACT CHECK REPORT START---/i;
const REPORT_END = /---FACT CHECK REPORT END---/i;
const ARTICLE_START = /---CORRECTED ARTICLE START---/i;
const ARTICLE_END = /---CORRECTED ARTICLE END---/i;
const FACT_START = /---FACT CHECK START---/i;
const FACT_END = /---FACT CHECK END---/i;

const ISSUE_SPLIT = /(?:^|\n)\s*ISSUE\s*#\s*:\s*/i;
const FIELD =
  /^(LOCATION|ISSUE TYPE|ACTION TAKEN|CORRECTION OR FLAG)\s*:\s*/i;

function sliceBetween(text, startRe, endRe) {
  const raw = String(text || "");
  const sm = startRe.exec(raw);
  if (!sm) return null;
  const from = sm.index + sm[0].length;
  const rest = raw.slice(from);
  const em = endRe.exec(rest);
  if (!em) return rest.trim();
  return rest.slice(0, em.index).trim();
}

function extractSection(body, headerRe, nextHeaderRe) {
  const m = headerRe.exec(body);
  if (!m) return "";
  const after = body.slice(m.index + m[0].length);
  if (!nextHeaderRe) return after.trim();
  const nm = nextHeaderRe.exec(after);
  return (nm ? after.slice(0, nm.index) : after).trim();
}

function parseIssueBlock(block) {
  const lines = String(block || "").trim().split("\n");
  if (!lines.length) return null;

  let number = "";
  let i = 0;
  const first = lines[0].trim();
  if (/^\d+\s*$/.test(first)) {
    number = first;
    i = 1;
  } else {
    const nm = first.match(/^(\d+)\s*(.*)$/);
    if (nm && !FIELD.test(first)) {
      number = nm[1];
      if (nm[2]) {
        lines[0] = nm[2];
        i = 0;
      } else {
        i = 1;
      }
    }
  }

  const fields = {
    location: "",
    issueType: "",
    actionTaken: "",
    correctionOrFlag: "",
  };
  let current = null;
  const buf = { location: [], issueType: [], actionTaken: [], correctionOrFlag: [] };

  for (; i < lines.length; i++) {
    const line = lines[i];
    const fm = line.match(
      /^\s*(LOCATION|ISSUE TYPE|ACTION TAKEN|CORRECTION OR FLAG)\s*:\s*(.*)$/i
    );
    if (fm) {
      const key = fm[1].toUpperCase();
      current =
        key === "LOCATION"
          ? "location"
          : key === "ISSUE TYPE"
            ? "issueType"
            : key === "ACTION TAKEN"
              ? "actionTaken"
              : "correctionOrFlag";
      const rest = fm[2].trim();
      if (rest) buf[current].push(rest);
      continue;
    }
    if (current) buf[current].push(line);
  }

  fields.location = buf.location.join("\n").trim();
  fields.issueType = buf.issueType.join("\n").trim();
  fields.actionTaken = buf.actionTaken.join("\n").trim();
  fields.correctionOrFlag = buf.correctionOrFlag.join("\n").trim();

  if (
    !fields.location &&
    !fields.issueType &&
    !fields.actionTaken &&
    !fields.correctionOrFlag
  ) {
    return null;
  }

  return { number, ...fields };
}

function parseIssues(issuesBody) {
  const raw = String(issuesBody || "").trim();
  if (!raw) return [];
  if (/^NO FACTUAL ISSUES IDENTIFIED/i.test(raw)) return [];

  const parts = raw.split(ISSUE_SPLIT).map((p) => p.trim()).filter(Boolean);
  // If the body started with "ISSUE #:" the first split part may be empty-ish;
  // if it didn't, the first part may be preamble ("ISSUES FOUND:" leftover).
  const issues = [];
  for (const part of parts) {
    if (/^ISSUES FOUND/i.test(part) && !/^ISSUE/i.test(part)) continue;
    const issue = parseIssueBlock(part);
    if (issue) issues.push(issue);
  }
  return issues.map((issue, idx) => ({
    ...issue,
    number: issue.number || String(idx + 1),
  }));
}

function extractField(body, label) {
  const re = new RegExp(
    `^${label}\\s*:\\s*(.+)$`,
    "im"
  );
  const m = body.match(re);
  return m ? m[1].trim() : "";
}

/**
 * @returns {null | {
 *   overallAssessment: string,
 *   totalIssues: string,
 *   issues: Array<{number, location, issueType, actionTaken, correctionOrFlag}>,
 *   noIssues: boolean,
 *   humanReview: string,
 *   companyClaimReview: string,
 *   correctedArticle: string,
 *   hasReport: boolean,
 * }}
 */
export function parseFactCheckReport(text) {
  const raw = String(text || "").trim();
  if (!raw) return null;

  let scope = raw;
  if (FACT_START.test(raw) && FACT_END.test(raw)) {
    const inner = sliceBetween(raw, FACT_START, FACT_END);
    if (inner) scope = inner;
  }

  let report =
    sliceBetween(scope, REPORT_START, REPORT_END) ||
    sliceBetween(scope, REPORT_START, ARTICLE_START);

  // Fallback: text that already had report markers stripped
  if (!report) {
    if (
      /OVERALL ASSESSMENT\s*:/i.test(scope) ||
      /TOTAL ISSUES FOUND\s*:/i.test(scope) ||
      /ISSUE\s*#\s*:/i.test(scope)
    ) {
      const beforeArticle = ARTICLE_START.exec(scope);
      report = beforeArticle
        ? scope.slice(0, beforeArticle.index).trim()
        : scope;
    }
  }

  const correctedArticle =
    sliceBetween(scope, ARTICLE_START, ARTICLE_END) ||
    sliceBetween(raw, ARTICLE_START, ARTICLE_END) ||
    "";

  if (!report && !correctedArticle) return null;

  const reportBody = report || "";
  const overallAssessment = extractField(reportBody, "OVERALL ASSESSMENT");
  const totalIssues = extractField(reportBody, "TOTAL ISSUES FOUND");
  const noIssues = /NO FACTUAL ISSUES IDENTIFIED/i.test(reportBody);

  let issuesBody = "";
  const issuesHeader = /(?:^|\n)\s*ISSUES FOUND\s*:?\s*/i.exec(reportBody);
  if (issuesHeader) {
    const from = issuesHeader.index + issuesHeader[0].length;
    const after = reportBody.slice(from);
    const stop =
      /(?:^|\n)\s*(?:ITEMS FLAGGED FOR HUMAN REVIEW|COMPANY CLAIM REVIEW)\s*:/i.exec(
        after
      );
    issuesBody = (stop ? after.slice(0, stop.index) : after).trim();
  }

  const issues = parseIssues(issuesBody);

  const humanReview = extractSection(
    reportBody,
    /(?:^|\n)\s*ITEMS FLAGGED FOR HUMAN REVIEW\s*:?\s*/i,
    /(?:^|\n)\s*COMPANY CLAIM REVIEW\s*:/i
  );
  const companyClaimReview = extractSection(
    reportBody,
    /(?:^|\n)\s*COMPANY CLAIM REVIEW\s*:?\s*/i,
    null
  );

  const hasReport = Boolean(
    overallAssessment ||
      totalIssues ||
      issues.length ||
      noIssues ||
      humanReview ||
      companyClaimReview
  );

  if (!hasReport && !correctedArticle) return null;

  return {
    overallAssessment,
    totalIssues:
      totalIssues ||
      (issues.length ? String(issues.length) : noIssues ? "0" : ""),
    issues,
    noIssues: noIssues || (issues.length === 0 && hasReport),
    humanReview,
    companyClaimReview,
    correctedArticle,
    hasReport,
  };
}

export function isFactCheckFormat(text) {
  return Boolean(parseFactCheckReport(text));
}
