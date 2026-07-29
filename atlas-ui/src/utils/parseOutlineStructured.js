/**
 * Parse outline artifact into header fields + H2 section cards.
 */

const START = "---OUTLINE START---";
const END = "---OUTLINE END---";

const H2_SPLIT = /(?:^|\n)\s*H2\s*:\s*/i;
const SECTION_FIELD =
  /^(PURPOSE|KEY POINTS|PROOF POINT SLOT|EXTERNAL CITE SLOT|IMAGE SLOT|FORMAT|WORD COUNT|QUESTIONS TO ANSWER)\s*:\s*/i;

function extractBody(text) {
  const raw = String(text || "");
  const s = raw.indexOf(START);
  const e = raw.indexOf(END);
  if (s !== -1 && e !== -1 && e > s) {
    return raw.slice(s + START.length, e).trim();
  }
  return raw.trim();
}

function parseSectionBlock(block) {
  const lines = String(block || "").trim().split("\n");
  if (!lines.length) return null;

  let title = lines[0].trim();
  // Title may be on first line after H2: split
  const fields = {};
  let current = null;
  const buf = {};

  for (let i = 1; i < lines.length; i++) {
    const line = lines[i];
    const fm = line.match(
      /^\s*(PURPOSE|KEY POINTS|PROOF POINT SLOT|EXTERNAL CITE SLOT|IMAGE SLOT|FORMAT|WORD COUNT|QUESTIONS TO ANSWER)\s*:\s*(.*)$/i
    );
    if (fm) {
      current = fm[1].toUpperCase();
      buf[current] = buf[current] || [];
      if (fm[2].trim()) buf[current].push(fm[2].trim());
      continue;
    }
    if (current) {
      buf[current].push(line);
    } else if (line.trim() && !title) {
      title = line.trim();
    }
  }

  for (const [k, v] of Object.entries(buf)) {
    fields[k] = v.join("\n").trim();
  }

  if (!title && !Object.keys(fields).length) return null;
  return { title, fields };
}

function extractNote(body, label, nextLabels) {
  const re = new RegExp(
    `(?:^|\\n)\\s*${label}\\s*:\\s*`,
    "i"
  );
  const m = re.exec(body);
  if (!m) return "";
  const after = body.slice(m.index + m[0].length);
  let end = after.length;
  for (const next of nextLabels) {
    const nr = new RegExp(`(?:^|\\n)\\s*${next}\\s*:`, "i");
    const nm = nr.exec(after);
    if (nm && nm.index < end) end = nm.index;
  }
  // Also stop at H2:
  const h2 = /(?:^|\n)\s*H2\s*:/i.exec(after);
  if (h2 && h2.index < end) end = h2.index;
  return after.slice(0, end).trim();
}

export function parseOutlineStructured(text) {
  const body = extractBody(text);
  if (!body) return null;
  if (!/H1\s*:/i.test(body) && !/H2\s*:/i.test(body)) return null;

  const h1 = (body.match(/^\s*H1\s*:\s*(.+)$/im) || [])[1]?.trim() || "";
  const ledeNote =
    extractNote(body, "SUMMARY NOTE", [
      "LEDE NOTE",
      "INTRO NOTE",
      "H2",
      "FAQ SECTION",
      "CONCLUSION NOTE",
      "CTA NOTE",
      "IMAGE PLAN",
      "TOTAL ESTIMATED WORD COUNT",
    ]) ||
    extractNote(body, "LEDE NOTE", [
      "INTRO NOTE",
      "H2",
      "FAQ SECTION",
      "CONCLUSION NOTE",
      "CTA NOTE",
      "IMAGE PLAN",
      "TOTAL ESTIMATED WORD COUNT",
    ]) ||
    extractNote(body, "LEDE NOTE / SUMMARY NOTE", [
      "INTRO NOTE",
      "H2",
      "FAQ SECTION",
      "CONCLUSION NOTE",
      "CTA NOTE",
      "IMAGE PLAN",
      "TOTAL ESTIMATED WORD COUNT",
    ]);
  const introNote = extractNote(body, "INTRO NOTE", [
    "H2",
    "FAQ SECTION",
    "CONCLUSION NOTE",
    "CTA NOTE",
    "IMAGE PLAN",
    "TOTAL ESTIMATED WORD COUNT",
  ]);
  const conclusionNote = extractNote(body, "CONCLUSION NOTE", [
    "CTA NOTE",
    "IMAGE PLAN",
    "TOTAL ESTIMATED WORD COUNT",
  ]);
  const ctaNote = extractNote(body, "CTA NOTE", [
    "IMAGE PLAN",
    "TOTAL ESTIMATED WORD COUNT",
  ]);
  const imagePlan = extractNote(body, "IMAGE PLAN", [
    "TOTAL ESTIMATED WORD COUNT",
  ]);
  const totalWords =
    (body.match(/TOTAL ESTIMATED WORD COUNT\s*:\s*(.+)$/im) || [])[1]?.trim() ||
    "";

  // Sections: from first H2 through FAQ / conclusion
  const h2Start = /(?:^|\n)\s*H2\s*:/i.exec(body);
  let sectionsRaw = "";
  if (h2Start) {
    sectionsRaw = body.slice(h2Start.index);
    const stop = /(?:^|\n)\s*(?:CONCLUSION NOTE|CTA NOTE|IMAGE PLAN|TOTAL ESTIMATED WORD COUNT)\s*:/i.exec(
      sectionsRaw
    );
    if (stop) sectionsRaw = sectionsRaw.slice(0, stop.index);
  }

  const parts = sectionsRaw.split(H2_SPLIT).map((p) => p.trim()).filter(Boolean);
  const sections = [];
  for (const part of parts) {
    const cleaned = part
      .replace(/(?:^|\n)\s*FAQ SECTION[^\n]*\n?/gi, "\n")
      .trim();
    if (!cleaned || SECTION_FIELD.test(cleaned)) continue;
    const sec = parseSectionBlock(cleaned);
    if (sec) sections.push(sec);
  }

  if (!h1 && !sections.length && !introNote && !ledeNote) return null;

  return {
    h1,
    ledeNote,
    introNote,
    sections,
    conclusionNote,
    ctaNote,
    imagePlan,
    totalWords,
  };
}

/** Parse "180–220 words" / "200-250" / "~300" into a midpoint estimate. */
export function parseWordCountRange(text) {
  const raw = String(text || "");
  const nums = [...raw.matchAll(/(\d{2,5})/g)].map((m) => Number(m[1]));
  if (!nums.length) return null;
  if (nums.length === 1) return nums[0];
  return Math.round((nums[0] + nums[1]) / 2);
}

export function summarizeOutlineWordBudgets(data) {
  if (!data?.sections?.length) {
    return {
      sectionEstimates: [],
      missingTitles: [],
      sumMid: 0,
      targetMid: null,
      delta: null,
      ok: true,
    };
  }
  const sectionEstimates = data.sections.map((sec) => {
    const mid = parseWordCountRange(sec.fields?.["WORD COUNT"] || "");
    return { title: sec.title, mid, missing: mid == null };
  });
  const missingTitles = sectionEstimates
    .filter((s) => s.missing)
    .map((s) => s.title);
  const sumMid = sectionEstimates.reduce(
    (acc, s) => acc + (s.mid || 0),
    0
  );
  const targetMid = parseWordCountRange(data.totalWords);
  const delta =
    targetMid != null && sumMid > 0 ? sumMid - targetMid : null;
  const ok =
    missingTitles.length === 0 &&
    (delta == null || Math.abs(delta) <= 150);
  return { sectionEstimates, missingTitles, sumMid, targetMid, delta, ok };
}

export function isOutlineFormat(text) {
  return Boolean(parseOutlineStructured(text));
}
