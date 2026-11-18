/**
 * Split markdown-ish artifact body into ## heading sections.
 * Also accepts plain lines that look like major ALL-CAPS banners when requested.
 */

const MARKER_LINE = /^---.+---\s*$/;

function stripOuterMarkers(text, startRe, endRe) {
  const raw = String(text || "");
  const sm = startRe?.exec(raw);
  const em = endRe?.exec(raw);
  if (sm && em && em.index > sm.index) {
    return raw.slice(sm.index + sm[0].length, em.index).trim();
  }
  return raw.trim();
}

/**
 * @returns {Array<{ heading: string, body: string }>}
 */
export function parseH2Sections(text, { startMarker = null, endMarker = null } = {}) {
  let body = String(text || "").replace(/\r\n/g, "\n").trim();
  if (!body) return [];

  if (startMarker && endMarker) {
    const startRe = new RegExp(
      `^---\\s*${startMarker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*---\\s*$`,
      "im"
    );
    const endRe = new RegExp(
      `^---\\s*${endMarker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*---\\s*$`,
      "im"
    );
    body = stripOuterMarkers(body, startRe, endRe);
  }

  const lines = body.split("\n");
  const sections = [];
  let current = null;
  let preamble = [];

  const flush = () => {
    if (!current) return;
    sections.push({
      heading: current.heading,
      body: current.lines.join("\n").trim(),
    });
    current = null;
  };

  for (const line of lines) {
    if (MARKER_LINE.test(line.trim())) continue;
    const hm = line.match(/^##\s+(.+?)\s*$/);
    if (hm) {
      flush();
      if (preamble.length) {
        const pre = preamble.join("\n").trim();
        if (pre) sections.push({ heading: "", body: pre });
        preamble = [];
      }
      current = { heading: hm[1].trim(), lines: [] };
      continue;
    }
    if (current) current.lines.push(line);
    else preamble.push(line);
  }
  flush();
  if (!sections.length && preamble.length) {
    const pre = preamble.join("\n").trim();
    if (pre) return [{ heading: "", body: pre }];
  }
  return sections.filter((s) => s.heading || s.body);
}

/** Pull GAP / WHY IT MATTERS / HOW WE WIN triples from a section body. */
export function parseGapRecords(sectionBody) {
  const raw = String(sectionBody || "").trim();
  if (!raw) return [];
  const parts = raw.split(/(?:^|\n)\s*GAP\s*:/i).map((p) => p.trim());
  const records = [];
  for (let i = 1; i < parts.length; i++) {
    const block = parts[i];
    const whyM = /(?:^|\n)\s*WHY IT MATTERS\s*:\s*/i.exec(block);
    const howM = /(?:^|\n)\s*HOW WE WIN\s*:\s*/i.exec(block);
    let gap = block;
    let why = "";
    let how = "";
    if (whyM) {
      gap = block.slice(0, whyM.index).trim();
      const afterWhy = block.slice(whyM.index + whyM[0].length);
      if (howM && howM.index > whyM.index) {
        const howAt = howM.index - (whyM.index + whyM[0].length);
        why = afterWhy.slice(0, howAt).trim();
        how = block.slice(howM.index + howM[0].length).trim();
        // stop how at next GAP-like noise — already split
        how = how.replace(/\n\s*GAP\s*:[\s\S]*$/i, "").trim();
      } else {
        why = afterWhy.trim();
      }
    } else if (howM) {
      gap = block.slice(0, howM.index).trim();
      how = block.slice(howM.index + howM[0].length).trim();
    }
    if (gap || why || how) {
      records.push({ gap, why, how });
    }
  }
  return records;
}
