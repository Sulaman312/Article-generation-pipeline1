import { parseGapRecords, parseH2Sections } from "./parseH2Sections";

export function parseResearch(text) {
  const sections = parseH2Sections(text, {
    startMarker: "SERP ANALYSIS START",
    endMarker: "SERP ANALYSIS END",
  });
  if (!sections.length) {
    // try without markers
    const fallback = parseH2Sections(text);
    if (!fallback.length) return null;
    return { sections: enrichSections(fallback) };
  }
  return { sections: enrichSections(sections) };
}

function enrichSections(sections) {
  return sections.map((sec) => {
    const isGaps = /content gaps/i.test(sec.heading);
    const gaps = isGaps ? parseGapRecords(sec.body) : [];
    return {
      ...sec,
      gaps,
      bodyWithoutGaps:
        gaps.length > 0
          ? sec.body
              .replace(/(?:^|\n)\s*GAP\s*:[\s\S]*/i, "")
              .trim()
          : sec.body,
    };
  });
}

export function isResearchFormat(text) {
  const data = parseResearch(text);
  return Boolean(data?.sections?.some((s) => s.heading));
}

export function parseSerpResearch(text) {
  const sections = parseH2Sections(text, {
    startMarker: "SERP RESEARCH START",
    endMarker: "SERP RESEARCH END",
  });
  if (!sections.length) {
    const fallback = parseH2Sections(text);
    if (!fallback.length) return null;
    return { sections: fallback };
  }
  return { sections };
}

export function isSerpResearchFormat(text) {
  const data = parseSerpResearch(text);
  return Boolean(data?.sections?.some((s) => s.heading || s.body));
}
