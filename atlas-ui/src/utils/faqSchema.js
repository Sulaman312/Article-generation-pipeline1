/** Client-side FAQPage JSON-LD helpers (mirrors backend/faq_schema.py). */

const FAQ_HEADING =
  /^##\s+.*\b(faq|frequently\s+asked\s+questions|questions?\s+fr[ée]quentes?|foire\s+aux\s+questions|preguntas?\s+frecuentes?|domande?\s+frequenti|h[aä]ufige?\s+fragen)\b.*$/i;

const H3 = /^###\s+(.+)$/;
const BOLD_QUESTION = /^\*\*(.+?\?)\*\*\s*$/;

export function extractFaqPairs(markdown) {
  if (!String(markdown || "").trim()) return [];
  const lines = String(markdown).split("\n");
  let inFaq = false;
  const sectionLines = [];

  for (const line of lines) {
    const stripped = line.trim();
    if (FAQ_HEADING.test(stripped)) {
      inFaq = true;
      continue;
    }
    if (inFaq && stripped.startsWith("## ") && !FAQ_HEADING.test(stripped)) {
      break;
    }
    if (inFaq) sectionLines.push(line);
  }

  if (!sectionLines.length) return [];

  const pairs = [];
  let question = null;
  let answerLines = [];

  function flush() {
    if (!question) return;
    const answer = normalizeAnswer(answerLines);
    if (answer) pairs.push([question, answer]);
    question = null;
    answerLines = [];
  }

  for (const line of sectionLines) {
    const stripped = line.trim();
    let m = stripped.match(H3);
    if (!m) m = stripped.match(BOLD_QUESTION);
    if (m) {
      flush();
      question = m[1].trim();
      continue;
    }
    if (question != null) answerLines.push(line);
  }
  flush();
  return pairs;
}

function normalizeAnswer(lines) {
  const parts = [];
  for (const raw of lines) {
    let s = String(raw || "").trim();
    if (!s) continue;
    s = s.replace(/^[-*]\s+/, "").replace(/^\d+\.\s+/, "");
    parts.push(s);
  }
  return parts.join(" ").trim();
}

export function buildFaqPageSchemaScript(pairs, { minQuestions = 2 } = {}) {
  if (!Array.isArray(pairs) || pairs.length < minQuestions) return "";
  const payload = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: pairs.map(([q, a]) => ({
      "@type": "Question",
      name: q,
      acceptedAnswer: { "@type": "Answer", text: a },
    })),
  };
  const json = JSON.stringify(payload, null, 2);
  return `<script type="application/ld+json">\n${json}\n</script>`;
}
