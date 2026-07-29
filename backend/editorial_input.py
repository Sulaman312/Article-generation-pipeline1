"""Manual editorial fields for new article runs (replaces Google Sheets calendar)."""

from __future__ import annotations

import re

from . import faq_schema
from . import writing_format_lint

# Hard ± window around the form Word Count (body prose only — FAQ/JSON-LD excluded).
WORD_COUNT_TOLERANCE = 100

TOPIC_CARD_START = "---TOPIC CARD START---"
TOPIC_CARD_END = "---TOPIC CARD END---"
_TOPIC_CARD_KEY_LINE = re.compile(r"^([A-Z][A-Z0-9 \-]+):\s*(.*)$")

# Display labels sent to Step 1 as "Header: value" lines.
FIELD_LABELS: tuple[str, ...] = (
    "Topic",
    "Seed Keyword",
    "Secondary Keywords",
    "Search Intent",
    "Target Persona",
    "Word Count",
    "Angle / Hook",
    "Internal Links",
    "Include FAQ",
    "Include External Links",
    "Keyword Data",
    "Notes",
)

# Keys the UI / API may use (snake_case); mapped to FIELD_LABELS.
_KEY_TO_LABEL: dict[str, str] = {
    "topic": "Topic",
    "seed_keyword": "Seed Keyword",
    "secondary_keywords": "Secondary Keywords",
    "search_intent": "Search Intent",
    "target_persona": "Target Persona",
    "word_count": "Word Count",
    "angle_hook": "Angle / Hook",
    "internal_links": "Internal Links",
    "include_faq": "Include FAQ",
    "include_external_links": "Include External Links",
    "keyword_data": "Keyword Data",
    "atp_data": "Keyword Data",
    "notes": "Notes",
    "semrush_notes": "Semrush / keyword research",
}

_LONG_FIELD_LABELS = frozenset({"Keyword Data", "Semrush / keyword research", "Notes"})
_LONG_FIELD_MAX = 50_000
_DEFAULT_FIELD_MAX = 4_000


def sanitize_manual_inputs(raw: dict | None) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    out: dict[str, str] = {}
    for key, label in _KEY_TO_LABEL.items():
        val = raw.get(key)
        if val is None and label in raw:
            val = raw.get(label)
        if val is None:
            continue
        text = str(val).strip()
        if text:
            limit = _LONG_FIELD_MAX if label in _LONG_FIELD_LABELS else _DEFAULT_FIELD_MAX
            out[label] = text[:limit]
    return out or None


def word_count_from_manual(manual: dict | None) -> int | None:
    """Parse numeric word target from manifest ``manual_inputs``."""
    if not isinstance(manual, dict):
        return None
    raw = (manual.get("Word Count") or manual.get("word_count") or "").strip()
    if not raw:
        return None
    m = re.search(r"(\d[\d,]*)", raw)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


def word_count_range_label(target: int) -> str:
    """±WORD_COUNT_TOLERANCE range label for topic card / brief."""
    low, high = word_count_bounds(target)
    return f"{low:,}–{high:,} words"


def word_count_exact_label(target: int) -> str:
    """Single-number label from the article form (what the editor entered)."""
    return f"{max(100, int(target)):,} words (form target)"


def word_count_bounds(
    target: int,
    *,
    tolerance: int | None = None,
) -> tuple[int, int]:
    """Acceptable article body word-count window (±tolerance; FAQ/JSON-LD excluded)."""
    n = max(100, int(target))
    margin = WORD_COUNT_TOLERANCE if tolerance is None else max(25, int(tolerance))
    return max(100, n - margin), n + margin


def count_article_words(text: str) -> int:
    """Count words in article body prose (FAQ section and JSON-LD excluded)."""
    if not text:
        return 0
    cleaned = faq_schema.markdown_for_word_count(text)
    cleaned = re.sub(r"^#{1,6}\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\[DRAFT NOTE:[^\]]*\]", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"```[\s\S]*?```", " ", cleaned)
    tokens = re.findall(r"\b[\w''’-]+\b", cleaned, flags=re.UNICODE)
    return len(tokens)


_OUTLINE_H2_BLOCK = re.compile(
    r"^H2:\s*(.+?)\s*$\n(?:.*?\n)*?^[ \t]*WORD COUNT:\s*(\d+)(?:\s*[–-]\s*(\d+))?",
    re.MULTILINE | re.IGNORECASE,
)


def parse_outline_section_budgets(outline: str) -> list[tuple[str, int]]:
    """Return (H2 title, target words) from outline WORD COUNT lines."""
    out: list[tuple[str, int]] = []
    for m in _OUTLINE_H2_BLOCK.finditer(outline or ""):
        title = m.group(1).strip()
        lo = int(m.group(2))
        hi = int(m.group(3)) if m.group(3) else lo
        mid = max(40, (lo + hi) // 2)
        out.append((title, mid))
    return out


def draft_section_budget_guidance(outline: str, target: int) -> str:
    """Instruct the drafter to hit per-H2 budgets that sum near the form target."""
    low, high = word_count_bounds(target)
    budgets = parse_outline_section_budgets(outline)
    lines = [
        "\n\n=== SECTION WORD BUDGETS (WRITE TO THESE — DO NOT OVERSHOOT) ===\n",
        f"Total body prose (FAQ excluded) must land in **{low:,}–{high:,}** words ",
        f"(form target **{target:,}**).\n",
        "Write each H2 section to roughly the budget below. Prefer slightly under on each ",
        "section over blowing past the total max.\n",
    ]
    if budgets:
        for title, words in budgets:
            lines.append(f"- H2 «{title}»: ~{words:,} words of body prose\n")
        planned = sum(w for _, w in budgets)
        lines.append(
            f"Outline section budgets sum to ~{planned:,} words "
            f"(adjust slightly so the full body stays ≤ {high:,}).\n"
        )
    else:
        lines.append(
            "Outline has no per-H2 WORD COUNT lines — estimate even section lengths "
            f"so the full body stays in {low:,}–{high:,}.\n"
        )
    lines.append(
        "FAQ (## Frequently Asked Questions / Questions fréquentes) is EXTRA and "
        "does not count toward this budget.\n"
    )
    return "".join(lines)


def split_article_h2_sections(markdown: str) -> list[dict]:
    """Split article into preamble + H2 sections for structure-preserving edits."""
    text = (markdown or "").replace("\r\n", "\n")
    if not text.strip():
        return []
    lines = text.split("\n")
    sections: list[dict] = []
    buf: list[str] = []
    heading = ""

    def flush() -> None:
        nonlocal buf, heading
        body = "\n".join(buf).strip("\n")
        raw = (heading + ("\n" + body if body else "")).strip()
        if not raw and not heading:
            buf = []
            return
        is_faq = bool(heading and faq_schema._FAQ_HEADING.match(heading.strip()))
        words = 0 if is_faq else count_article_words(body if body else raw)
        sections.append(
            {
                "heading": heading,
                "body": body,
                "is_faq": is_faq,
                "words": words,
            }
        )
        buf = []

    for line in lines:
        if line.startswith("## ") and not line.startswith("### "):
            flush()
            heading = line
            continue
        buf.append(line)
    flush()
    return sections


def reassemble_h2_sections(sections: list[dict]) -> str:
    parts: list[str] = []
    for sec in sections:
        heading = (sec.get("heading") or "").rstrip()
        body = (sec.get("body") or "").strip("\n")
        if heading and body:
            parts.append(f"{heading}\n{body}")
        elif heading:
            parts.append(heading)
        elif body:
            parts.append(body)
    return "\n\n".join(parts).strip() + "\n"


def allocate_section_word_caps(
    sections: list[dict],
    target: int,
    *,
    outline: str = "",
) -> list[int]:
    """Per-section body word caps totaling ≤ high; FAQ sections get 0 (ignored)."""
    _low, high = word_count_bounds(target)
    budgets = parse_outline_section_budgets(outline)
    non_faq = [i for i, s in enumerate(sections) if not s.get("is_faq")]
    caps = [0] * len(sections)
    if not non_faq:
        return caps

    used_budget: set[int] = set()
    outline_caps: dict[int, int] = {}
    for i in non_faq:
        heading = re.sub(r"^##\s+", "", sections[i].get("heading") or "").strip()
        if not heading:
            continue
        for bi, (title, words) in enumerate(budgets):
            if bi in used_budget:
                continue
            if title.lower() in heading.lower() or heading.lower() in title.lower():
                outline_caps[i] = words
                used_budget.add(bi)
                break

    if len(outline_caps) >= max(1, len(non_faq) // 2):
        for i in non_faq:
            caps[i] = outline_caps.get(
                i, max(60, high // max(1, len(non_faq)))
            )
    else:
        total_words = sum(max(1, sections[i]["words"]) for i in non_faq) or 1
        for i in non_faq:
            share = sections[i]["words"] / total_words
            caps[i] = max(60, int(high * share))

    sum_caps = sum(caps[i] for i in non_faq) or 1
    scale = (high * 0.98) / sum_caps
    for i in non_faq:
        caps[i] = max(50, int(caps[i] * scale))
    return caps


def word_count_target_from_manifest(manifest: dict | None) -> int | None:
    """Resolve numeric target from manifest (stored field or manual_inputs)."""
    if not isinstance(manifest, dict):
        return None
    stored = manifest.get("target_word_count")
    if isinstance(stored, int) and stored > 0:
        return stored
    if isinstance(stored, str) and stored.strip().isdigit():
        return int(stored.strip())
    return word_count_from_manual(manifest.get("manual_inputs"))


def mandatory_word_count_notice(target: int) -> str:
    low, high = word_count_bounds(target)
    exact = word_count_exact_label(target)
    return (
        f"\n\n=== MANDATORY EDITORIAL TARGET (from article form) ===\n"
        f"Word Count: {target:,} — the editor entered this number; the draft must hit it.\n"
        f"- Topic card: RECOMMENDED WORD COUNT: {exact}\n"
        f"- Brief: WORD COUNT TARGET: {exact}\n"
        f"- Outline: TOTAL ESTIMATED WORD COUNT must be {target:,} words; each H2 section "
        f"WORD COUNT must sum to ~{target:,} (not 1,000–1,200).\n"
        f"- Draft body (prose before FAQ): minimum {low:,} words, target {target:,} words, "
        f"**maximum {high:,} words** (hard cap). FAQ and JSON-LD are **extra** and do not "
        f"count toward this total.\n"
        f"Do NOT use 800–1,200, 1,000–1,200, or other shorter defaults from content type "
        f"or workspace writing_guidelines when this block is present.\n"
    )


def should_include_faq(fields: dict | None) -> bool:
    """FAQ section is on by default; disable via form or Notes (e.g. 'no FAQ')."""
    if not isinstance(fields, dict):
        return True
    notes = (fields.get("Notes") or fields.get("notes") or "").lower()
    if any(p in notes for p in ("no faq", "skip faq", "without faq", "omit faq")):
        return False
    raw = (fields.get("Include FAQ") or fields.get("include_faq") or "yes").strip().lower()
    return raw not in ("no", "false", "0", "skip", "off", "n")


_FAQ_HEADING_BY_LANG: dict[str, str] = {
    "en": "## Frequently Asked Questions",
    "fr": "## Questions fréquentes",
    "de": "## Häufig gestellte Fragen",
    "es": "## Preguntas frecuentes",
    "it": "## Domande frequenti",
}

_LANGUAGE_LABELS: dict[str, str] = {
    "en": "English",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "it": "Italian",
}


def article_language_from_manual(manual: dict | None) -> str:
    """Infer article language from Notes / Topic (defaults to English)."""
    notes = notes_from_manual(manual).lower()
    topic = ""
    if isinstance(manual, dict):
        topic = (manual.get("Topic") or manual.get("topic") or "").lower()
    combined = f"{notes} {topic}"
    if re.search(
        r"\b(french|français|en français|in french|rédig(?:er|e|é)\s+en\s+français)\b",
        combined,
        re.I,
    ):
        return "fr"
    if re.search(r"\b(german|deutsch|auf deutsch|in german)\b", combined, re.I):
        return "de"
    if re.search(r"\b(spanish|español|en español|in spanish)\b", combined, re.I):
        return "es"
    if re.search(r"\b(italian|italiano|in italian)\b", combined, re.I):
        return "it"
    return "en"


def language_label_for_code(lang: str) -> str:
    return _LANGUAGE_LABELS.get((lang or "en").lower(), "English")


def faq_heading_for_language(lang: str) -> str:
    return _FAQ_HEADING_BY_LANG.get((lang or "en").lower(), _FAQ_HEADING_BY_LANG["en"])


def faq_editorial_notice(manual: dict | None = None) -> str:
    lang = article_language_from_manual(manual)
    heading = faq_heading_for_language(lang)
    language_label = _LANGUAGE_LABELS.get(lang, "English")
    return (
        "\n\n=== FAQ SECTION (REQUIRED FOR SEO) ===\n"
        f"Include **one** FAQ block in the outline and draft — written entirely in **{language_label}**.\n"
        "- Placement: after the main body sections, **before** the conclusion/CTA.\n"
        f"- Format: H2 `{heading}` then items from the **PAA / FAQ RESEARCH** Recommended FAQ bank.\n"
        "- Prefer bank question wording; do **not** invent a second FAQ block in another language.\n"
        "- If the PAA bank says LOW SIGNAL or KEYWORD DATA SHOWS LOW/NO DEMAND, use fewer questions — do not pad.\n"
        "- Each item: `### Question here?` then a direct **3–4 line** answer (3–4 sentences each).\n"
        "- Do not invent brands, products, or prices without a cited source.\n"
        "- FAQ does **not** count toward the form Word Count (body prose only).\n"
    )


def should_include_external_links(fields: dict | None) -> bool:
    """Outbound authority links on by default; disable via form or Notes."""
    if not isinstance(fields, dict):
        return True
    notes = (fields.get("Notes") or fields.get("notes") or "").lower()
    if any(
        p in notes
        for p in (
            "no external",
            "skip external",
            "without external",
            "omit external",
            "no outbound",
        )
    ):
        return False
    raw = (
        fields.get("Include External Links")
        or fields.get("include_external_links")
        or "yes"
    ).strip().lower()
    return raw not in ("no", "false", "0", "skip", "off", "n")


def notes_from_manual(manual: dict | None) -> str:
    if not isinstance(manual, dict):
        return ""
    return (manual.get("Notes") or manual.get("notes") or "").strip()


def notes_editorial_notice(manual: dict | None) -> str:
    notes = notes_from_manual(manual)
    if not notes:
        return ""
    return (
        "\n\n=== EDITOR NOTES (MANDATORY - from article form) ===\n"
        "These constraints override generic defaults when they conflict. "
        "Carry every requirement through the brief, outline, draft, and final output.\n\n"
        f"{notes}\n"
    )


def seo_readability_notice() -> str:
    """Shared SEO/readability rules injected from brief through final output."""
    return (
        "\n\n=== SEO & READABILITY RULES (NON-NEGOTIABLE) ===\n"
        "- **H1 title:** maximum **60 characters**, **5-12 words**, with the primary keyword "
        "once (exact or near-exact).\n"
        "- **Opening:** `# H1` → `## Summary` (40–80 words / 3–4 lines) → hero "
        "`![alt](IMAGE: …)` → first content H2.\n"
        "- **Body keyword use:** use the primary keyword once in the first 100 body words and "
        "do not repeat that exact phrase elsewhere in body prose. Use each secondary keyword "
        "at most once across headings and body prose. Metadata is counted separately.\n"
        "- **E-E-A-T (in-body):** proof points where planned, 3–5 credible external links, honest limits — "
        "never a standalone \"Why trust us\" section; **prices and numbers must be real and cited** "
        "(inline HTTPS in the same paragraph) or generalized without inventing figures.\n"
        "- **FAQ answers:** each answer is **3–4 lines** (3–4 sentences).\n"
        "- **Length:** honor the form Word Count target. When competitors are lean, write toward "
        "the lower end of the allowed range by cutting filler, not useful detail.\n"
        "- **Links:** weave 3-5 working external authority links and 2-4 internal cluster links "
        "inline. Do not use broken URLs, bare URLs, or footer link dumps.\n"
        "- **Images:** include 2-3 in-text placeholders formatted as "
        "`![descriptive alt text](IMAGE: slug-or-description)`.\n"
        "- **Tone:** keep brand voice, formality, perspective, and energy consistent from the "
        "introduction through the CTA.\n"
    )


def writing_format_guidelines_notice() -> str:
    """Thin pointer — full rules live in the system prompt; pipeline enforces after generation."""
    return (
        "\n\n=== WRITING FORMAT COMPLIANCE ===\n"
        "Full rules are in your system prompt (WRITING FORMAT GUIDELINES block). "
        "The pipeline automatically lints and repairs violations after this step.\n"
    )


def outline_format_guidelines_notice() -> str:
    """Outline-stage reminder (details enforced by lint + system guidelines)."""
    return (
        "\n\n=== OUTLINE STRUCTURE CHECKLIST ===\n"
        "Headings: sentence case, progressive H2 story, numbered H3s for sequences, "
        "1–2 bridging sentences planned under each H2, topical closing H2 (not \"Conclusion\"), "
        "2–3 CTA placements at H2 breaks. Violations are auto-checked after generation.\n"
    )


def cta_format_guidelines_notice() -> str:
    """Final-output CTA reminder (enforced by lint + repair)."""
    return (
        "\n\n=== CTA PLACEMENT CHECKLIST ===\n"
        "2–3 inline CTAs at H2 section breaks; each CTA: bold heading, description, "
        f"markdown link on separate lines; demo slug `{writing_format_lint.DEMO_CTA_SLUG}` only. "
        "Violations are auto-checked after generation.\n"
    )


def external_links_editorial_notice() -> str:
    return (
        "\n\n=== EXTERNAL AUTHORITY LINKS (REQUIRED FOR TRUST) ===\n"
        "Articles must cite **real, authoritative outbound sources** — not only internal links.\n"
        "- Target **3–5** external markdown links in the draft/final article: "
        "`[2–3 word anchor](https://full-url)` woven mid-sentence.\n"
        "- Prefer: government (.gov), standards bodies, major research/industry publishers, "
        "official product/docs pages — sources a skeptical reader would trust.\n"
        "- Use URLs from the **SERP research digest** and **SERP analysis** when provided; "
        "do **not** invent or guess URLs.\n"
        "- Place links where you cite stats, regulations, market data, or \"according to …\" claims.\n"
        "- Do **not** link to direct competitors' sales pages unless the article is explicitly "
        "a comparison piece.\n"
        "- Internal cluster links: `[2–3 words](INTERNAL: cluster name)` inline in prose.\n"
        "- External links: `[2–3 words](https://…)` inline in prose — not end-of-paragraph citations.\n"
    )


def draft_word_count_requirement(target: int) -> str:
    low, high = word_count_bounds(target)
    return (
        f"\n\n=== DRAFT LENGTH (NON-NEGOTIABLE — ENFORCED AT GENERATION) ===\n"
        f"Editor form Word Count: **{target:,}**.\n"
        f"Body prose MUST land in **{low:,}–{high:,}** words (FAQ excluded).\n"
        f"Aim for **{target:,}**. Going above **{high:,}** is invalid.\n"
        f"Hit the length while writing — do not plan to 'fix later' by deleting sections.\n"
    )


def system_word_count_override(target: int) -> str:
    """Prepended to system prompts so context.md length tables do not override the form."""
    label = word_count_range_label(target)
    return (
        f"\n\n=== ARTICLE FORM WORD COUNT (HIGHEST PRIORITY) ===\n"
        f"The editor set Word Count: {target:,} for this run. Required length: {label}.\n"
        f"This overrides writing_guidelines.md default ranges (e.g. 800–1,200 for checklists) "
        f"and any inferred shorter length from content type.\n"
    )


def user_word_count_block(target: int) -> str:
    """Short block prepended to step user messages (brief, outline, draft)."""
    low, high = word_count_bounds(target)
    return (
        f"=== REQUIRED ARTICLE LENGTH (from form — do not shorten) ===\n"
        f"WORD COUNT TARGET: {target:,} words (minimum {low:,}, maximum {high:,})\n\n"
    )


def _replace_delimited_line(
    text: str,
    *,
    start_marker: str,
    end_marker: str,
    line_prefix: str,
    new_line: str,
) -> str:
    start = text.find(start_marker)
    end = text.find(end_marker)
    if start == -1 or end == -1 or end <= start:
        return text
    body = text[start + len(start_marker) : end]
    prefix_re = re.escape(line_prefix)
    if re.search(rf"^{prefix_re}", body, re.MULTILINE):
        body = re.sub(
            rf"^{prefix_re}.*$",
            new_line,
            body,
            count=1,
            flags=re.MULTILINE,
        )
    else:
        body = body.rstrip() + "\n" + new_line + "\n"
    return text[: start + len(start_marker)] + body + text[end:]


def enforce_word_count_in_brief(text: str, target: int) -> str:
    exact = word_count_exact_label(target)
    return _replace_delimited_line(
        text,
        start_marker="---BRIEF START---",
        end_marker="---BRIEF END---",
        line_prefix="WORD COUNT TARGET:",
        new_line=f"WORD COUNT TARGET: {exact}",
    )


def enforce_word_count_in_outline(text: str, target: int) -> str:
    n = max(100, int(target))
    return _replace_delimited_line(
        text,
        start_marker="---OUTLINE START---",
        end_marker="---OUTLINE END---",
        line_prefix="TOTAL ESTIMATED WORD COUNT:",
        new_line=f"TOTAL ESTIMATED WORD COUNT: {n:,} words (form target)",
    )


_OUTLINE_SECTION_WC = re.compile(r"(^  WORD COUNT:\s*)(.+)$", re.MULTILINE)


def enforce_outline_section_word_counts(text: str, target: int) -> str:
    """Rescale per-H2 WORD COUNT lines so they sum to the form target."""
    text = enforce_word_count_in_outline(text, target)
    matches = list(_OUTLINE_SECTION_WC.finditer(text))
    if not matches:
        return text
    n = len(matches)
    body_target = max(n * 80, int(target * 0.9))
    base, extra = divmod(body_target, n)
    out: list[str] = []
    pos = 0
    for i, m in enumerate(matches):
        out.append(text[pos : m.start()])
        words = base + (1 if i < extra else 0)
        slack = max(25, words // 6)
        out.append(f"{m.group(1)}{words}–{words + slack} words")
        pos = m.end()
    out.append(text[pos:])
    return "".join(out)


def enforce_word_count_in_topic_card(text: str, target: int) -> str:
    """Replace RECOMMENDED WORD COUNT in a topic card if the model ignored the form."""
    if not text or not target:
        return text
    start = text.find(TOPIC_CARD_START)
    end = text.find(TOPIC_CARD_END)
    if start == -1 or end == -1 or end <= start:
        return text
    new_line = f"RECOMMENDED WORD COUNT: {word_count_exact_label(target)}"
    body = text[start + len(TOPIC_CARD_START) : end]
    if re.search(r"^RECOMMENDED WORD COUNT:", body, re.MULTILINE):
        body = re.sub(
            r"^RECOMMENDED WORD COUNT:.*$",
            new_line,
            body,
            count=1,
            flags=re.MULTILINE,
        )
    else:
        body = body.rstrip() + "\n" + new_line + "\n"
    return (
        text[: start + len(TOPIC_CARD_START)]
        + body
        + text[end:]
    )


_TOPIC_CARD_SEMRUSH_ONLY_LINES = (
    "SEMRUSH LOCALE DEVICE:",
    "SEMRUSH METRICS VERBATIM:",
    "SEMRUSH SERP FEATURES VERBATIM:",
    "SEMRUSH RELATED VARIANTS VERBATIM:",
)
_NOT_PROVIDED_VALUES = frozenset(
    {"NOT PROVIDED", "NOT PROVIDED.", "[NOT PROVIDED]", "Not stated", "Not stated."}
)


def has_tool_keyword_paste(semrush_notes: str) -> bool:
    """True when the user pasted an external keyword-tool export (optional field)."""
    t = (semrush_notes or "").strip()
    if len(t) < 50:
        return False
    if re.search(
        r"\b(KD|CPC|keyword difficulty|search volume|volume:|SERP features?)\b",
        t,
        re.I,
    ):
        return True
    return len(t) >= 150


def _split_keyword_list(raw: str) -> list[str]:
    if not raw:
        return []
    return [p.strip() for p in re.split(r"[,·\n;]+", raw) if p.strip()]


def _search_intent_from_form(raw: str) -> str | None:
    key = (raw or "").strip().lower()
    if not key:
        return None
    mapping = {
        "awareness": "informational",
        "informational": "informational",
        "information": "informational",
        "consideration": "commercial",
        "commercial": "commercial",
        "decision": "transactional",
        "transactional": "transactional",
        "navigational": "navigational",
    }
    for fragment, intent in mapping.items():
        if fragment in key:
            return intent
    return None


def _strip_empty_semrush_lines(body: str) -> str:
    kept: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            kept.append(line)
            continue
        upper = stripped.upper()
        if any(upper.startswith(p) for p in _TOPIC_CARD_SEMRUSH_ONLY_LINES):
            val = stripped.split(":", 1)[-1].strip()
            if val in _NOT_PROVIDED_VALUES or not val:
                continue
        if upper.startswith("SEMRUSH TOOL STATUS:"):
            val = stripped.split(":", 1)[-1].strip()
            if val in _NOT_PROVIDED_VALUES:
                continue
        kept.append(line)
    return "\n".join(kept)


def _merge_secondary_keywords(existing: str, from_form: list[str]) -> str:
    if not from_form:
        return existing
    merged: list[str] = []
    seen: set[str] = set()
    for term in from_form + _split_keyword_list(existing):
        key = term.lower()
        if key not in seen:
            seen.add(key)
            merged.append(term)
    return ", ".join(merged[:7])


def apply_manual_keywords_topic_card(
    text: str,
    fields: dict[str, str] | None,
    *,
    semrush_notes: str = "",
) -> str:
    """Form-only keywords: friendly labels, no NOT PROVIDED Semrush spam."""
    if not text or not fields or has_tool_keyword_paste(semrush_notes):
        return text
    if re.search(
        r"^SEMRUSH TOOL STATUS:\s*COPIED FROM INPUT",
        text,
        re.MULTILINE | re.IGNORECASE,
    ):
        return text
    seed = (fields.get("Seed Keyword") or "").strip()
    secondaries = _split_keyword_list(fields.get("Secondary Keywords") or "")
    if not seed and not secondaries:
        return text

    start = text.find(TOPIC_CARD_START)
    end = text.find(TOPIC_CARD_END)
    if start == -1 or end == -1 or end <= start:
        return text

    body = _strip_empty_semrush_lines(text[start + len(TOPIC_CARD_START) : end])
    wrapped = TOPIC_CARD_START + body + TOPIC_CARD_END

    wrapped = _replace_delimited_line(
        wrapped,
        start_marker=TOPIC_CARD_START,
        end_marker=TOPIC_CARD_END,
        line_prefix="KEYWORD SOURCE:",
        new_line="KEYWORD SOURCE: MANUAL (article form)",
    )
    wrapped = _replace_delimited_line(
        wrapped,
        start_marker=TOPIC_CARD_START,
        end_marker=TOPIC_CARD_END,
        line_prefix="SEMRUSH TOOL STATUS:",
        new_line="SEMRUSH TOOL STATUS: MANUAL KEYWORDS (article form)",
    )
    if seed:
        wrapped = _replace_delimited_line(
            wrapped,
            start_marker=TOPIC_CARD_START,
            end_marker=TOPIC_CARD_END,
            line_prefix="PRIMARY KEYWORD:",
            new_line=f"PRIMARY KEYWORD: {seed}",
        )
    form_intent = _search_intent_from_form(fields.get("Search Intent") or "")
    if form_intent:
        wrapped = _replace_delimited_line(
            wrapped,
            start_marker=TOPIC_CARD_START,
            end_marker=TOPIC_CARD_END,
            line_prefix="SEARCH INTENT:",
            new_line=f"SEARCH INTENT: {form_intent}",
        )
    if secondaries:
        fields_map = _parse_topic_card_field_map(wrapped)
        existing = fields_map.get("RELATED SECONDARY KEYWORDS", "")
        merged = _merge_secondary_keywords(existing, secondaries)
        wrapped = _replace_delimited_line(
            wrapped,
            start_marker=TOPIC_CARD_START,
            end_marker=TOPIC_CARD_END,
            line_prefix="RELATED SECONDARY KEYWORDS:",
            new_line=f"RELATED SECONDARY KEYWORDS: {merged}",
        )

    tail = end + len(TOPIC_CARD_END)
    return text[:start] + wrapped + text[tail:]


def build_topic_payload(fields: dict[str, str] | None, *, semrush_notes: str = "") -> str:
    """Build the Step 1 user message body from labeled fields."""
    lines: list[str] = []
    extra = (semrush_notes or "").strip()
    if fields and not has_tool_keyword_paste(extra):
        seed = (fields.get("Seed Keyword") or "").strip()
        sec = (fields.get("Secondary Keywords") or "").strip()
        if seed or sec:
            lines.append(
                "Keyword source: Article form (Seed Keyword + Secondary Keywords). "
                "No external tool export pasted — do not output NOT PROVIDED for Semrush fields."
            )
            lines.append("")
    if fields:
        for label in FIELD_LABELS:
            v = (fields.get(label) or "").strip()
            if v:
                lines.append(f"{label}: {v}")
    if extra:
        if lines:
            lines.append("")
        lines.append("Optional keyword tool paste (Semrush, etc.):")
        lines.append(extra[:12000])
    return "\n".join(lines).strip()


def topic_title_from_fields(fields: dict[str, str] | None) -> str:
    if not fields:
        return ""
    for label in ("Topic", "Seed Keyword"):
        v = (fields.get(label) or "").strip()
        if v:
            return v[:500]
    return ""


def _parse_topic_card_field_map(text: str) -> dict[str, str]:
    """Parse delimited topic card body into uppercase keys → values."""
    start = text.find(TOPIC_CARD_START)
    end = text.find(TOPIC_CARD_END)
    if start == -1 or end == -1 or end <= start:
        return {}
    body = text[start + len(TOPIC_CARD_START) : end].strip()
    fields: dict[str, str] = {}
    current_key: str | None = None
    for line in body.splitlines():
        m = _TOPIC_CARD_KEY_LINE.match(line)
        if m:
            current_key = m.group(1).strip().upper()
            fields[current_key] = m.group(2).strip()
        elif current_key and line.strip():
            fields[current_key] = f"{fields[current_key]}\n{line.strip()}".strip()
    return fields


META_SEO_START = "---META SEO START---"
META_SEO_END = "---META SEO END---"
_DELIMITED_KEY_LINE = re.compile(r"^([A-Z][A-Z0-9 \-]+):\s*(.*)$")


def _parse_delimited_field_map(
    text: str,
    *,
    start_marker: str,
    end_marker: str,
) -> dict[str, str]:
    """Parse a delimited block body into uppercase keys → values."""
    if not (text or "").strip():
        return {}
    start = text.find(start_marker)
    end = text.find(end_marker)
    if start == -1 or end == -1 or end <= start:
        return {}
    body = text[start + len(start_marker) : end].strip()
    fields: dict[str, str] = {}
    current_key: str | None = None
    for line in body.splitlines():
        m = _DELIMITED_KEY_LINE.match(line)
        if m:
            current_key = m.group(1).strip().upper()
            fields[current_key] = m.group(2).strip()
        elif current_key and line.strip():
            fields[current_key] = f"{fields[current_key]}\n{line.strip()}".strip()
    return fields


def _normalize_page_type(raw: str) -> str:
    text = (raw or "").strip().lower()
    if not text:
        return "blog page"
    if "page" in text:
        return text
    if text in ("blog", "article", "guide", "how-to", "how to", "listicle"):
        return f"{text} page" if text != "article" else "blog page"
    return f"{text} page"


def _first_nonempty(*values: str | None) -> str:
    for v in values:
        t = (v or "").strip()
        if t and not (t.startswith("[") and t.endswith("]")):
            return t
    return ""


def _trim_content_description(text: str, *, limit: int = 240) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) <= limit:
        return t
    cut = t[:limit].rsplit(" ", 1)[0]
    return (cut or t[:limit]).strip().rstrip(",.;:")


def build_meta_seo_context(
    *,
    topic_card: str = "",
    assignment_brief: str = "",
    article_source: str = "",
    final_output: str = "",
    manual: dict | None = None,
) -> dict[str, str]:
    """Build placeholders for meta title / description generation prompts."""
    source = (article_source or final_output or "").strip()
    tc = _parse_topic_card_field_map(topic_card)
    brief = _parse_delimited_field_map(
        assignment_brief,
        start_marker="---BRIEF START---",
        end_marker="---BRIEF END---",
    )
    pub = _parse_delimited_field_map(
        source,
        start_marker="---PUBLISHING METADATA START---",
        end_marker="---PUBLISHING METADATA END---",
    )

    article_h1 = ""
    if source:
        from . import faq_schema

        body = faq_schema.extract_corrected_article_body(source) or source
        h1 = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        if h1:
            article_h1 = h1.group(1).strip()

    manual_seed = ""
    manual_topic = ""
    if isinstance(manual, dict):
        manual_seed = (manual.get("Seed Keyword") or manual.get("seed_keyword") or "").strip()
        manual_topic = (manual.get("Topic") or manual.get("topic") or "").strip()

    keyword = _first_nonempty(
        tc.get("PRIMARY KEYWORD"),
        brief.get("PRIMARY KEYWORD"),
        pub.get("PRIMARY KEYWORD"),
        tc.get("SEED KEYWORD"),
        manual_seed,
    )
    if not keyword:
        keyword = "your target keyword"

    page_type = _normalize_page_type(
        _first_nonempty(tc.get("CONTENT TYPE"), tc.get("SEARCH INTENT"), "blog")
    )

    content_description = _trim_content_description(
        _first_nonempty(
            tc.get("TOPIC"),
            brief.get("ARTICLE TITLE"),
            article_h1,
            pub.get("H1 TITLE"),
            manual_topic,
            tc.get("SUGGESTED ANGLE"),
            tc.get("PRIMARY KEYWORD"),
        )
        or "the main topics covered in this article"
    )

    meta_title_prompt = (
        f'Write a meta title for a {page_type} featuring {content_description}. '
        f'Include my target keyword, "{keyword}," in a natural way. '
        f"Keep the title to between 50 and 60 characters. Give me 5 options to choose from. "
        f"Use varied high-CTR patterns where the content supports them — e.g. step-by-step guide, "
        f"N steps to, how to, best (for list/comparison pieces), or complete guide. "
        f"Only use real step or list counts from the article; do not invent numbers."
    )
    meta_description_prompt = (
        f"Write a meta description for a {page_type} featuring {content_description}. "
        f'Include my target keyword, "{keyword}," in a natural way. '
        f"Keep the description to between 120 and 155 characters. "
        f"Give me 5 options to choose from."
    )

    return {
        "page_type": page_type,
        "keyword": keyword,
        "content_description": content_description,
        "meta_title_prompt": meta_title_prompt,
        "meta_description_prompt": meta_description_prompt,
    }


_META_SEO_PROMPT_ECHO = re.compile(
    r"^META (?:TITLE|DESCRIPTION) PROMPT USED:\s*\n(?:.*\n)*?(?=^META (?:TITLE|DESCRIPTION) OPTIONS|\Z)",
    re.MULTILINE | re.IGNORECASE,
)
_META_SEO_CONTENT_SUMMARY = re.compile(
    r"^CONTENT SUMMARY:.*\n",
    re.MULTILINE | re.IGNORECASE,
)
_META_SEO_MARKERS = re.compile(
    r"^---?\s*META SEO (?:START|END)\s*---?\s*\n?",
    re.MULTILINE | re.IGNORECASE,
)


def finalize_meta_seo_output(text: str) -> str:
    """Clean meta SEO artifact: drop echoed prompts and content summary; keep step delimiters."""
    if not (text or "").strip():
        return text
    cleaned = _META_SEO_PROMPT_ECHO.sub("", text)
    cleaned = _META_SEO_CONTENT_SUMMARY.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    from .step_markers import wrap_step_artifact

    return wrap_step_artifact("meta_seo", cleaned)


def strip_meta_seo_prompt_echo(text: str) -> str:
    """Alias for finalize_meta_seo_output."""
    return finalize_meta_seo_output(text)


_META_SEO_OPTION_LINE = re.compile(
    r"^\s*\d+\.\s+(.+?)(?:\s*\(\d+\s*characters?\))?\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def _parse_meta_seo_option_list(body: str, section_label: str) -> list[str]:
    """Extract numbered options under a META * OPTIONS heading."""
    match = re.search(
        rf"^{re.escape(section_label)}[^\n]*\n(.*?)(?=^[A-Z][A-Z0-9 \-/]+(?:\s*\([^)]+\))?:\s*|\Z)",
        body,
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return []
    options: list[str] = []
    for line in match.group(1).splitlines():
        m = _META_SEO_OPTION_LINE.match(line)
        if m:
            options.append(m.group(1).strip())
    return options


def parse_meta_seo_artifact(text: str) -> dict[str, str | list[str]]:
    """Parse meta SEO step output into page type, keyword, and option lists."""
    cleaned = finalize_meta_seo_output(text or "")
    field_map: dict[str, str] = {}
    current_key: str | None = None
    for line in cleaned.splitlines():
        m = _DELIMITED_KEY_LINE.match(line)
        if m:
            current_key = m.group(1).strip().upper()
            field_map[current_key] = m.group(2).strip()
        elif current_key and line.strip() and not _META_SEO_OPTION_LINE.match(line):
            if "OPTIONS" not in current_key:
                field_map[current_key] = f"{field_map[current_key]}\n{line.strip()}".strip()

    titles = _parse_meta_seo_option_list(cleaned, "META TITLE OPTIONS")
    descriptions = _parse_meta_seo_option_list(cleaned, "META DESCRIPTION OPTIONS")
    return {
        "page_type": (field_map.get("PAGE TYPE") or "").strip(),
        "keyword": (field_map.get("TARGET KEYWORD") or "").strip(),
        "title_options": titles,
        "description_options": descriptions,
    }


def format_meta_seo_publishing_lines(parsed: dict[str, str | list[str]]) -> str:
    """Format meta SEO options for the final_output publishing metadata block."""
    titles = parsed.get("title_options") or []
    descriptions = parsed.get("description_options") or []
    if not isinstance(titles, list):
        titles = []
    if not isinstance(descriptions, list):
        descriptions = []
    lines: list[str] = []
    if titles:
        lines.append(f"META TITLE: {titles[0]}")
        lines.append("META TITLE OPTIONS:")
        for i, title in enumerate(titles, 1):
            lines.append(f"  {i}. {title}")
    if descriptions:
        lines.append(f"META DESCRIPTION: {descriptions[0]}")
        lines.append("META DESCRIPTION OPTIONS:")
        for i, desc in enumerate(descriptions, 1):
            lines.append(f"  {i}. {desc}")
    return "\n".join(lines)


def inject_meta_seo_into_publishing_metadata(text: str, meta_seo_text: str) -> str:
    """Insert meta title/description options from the meta_seo step into publishing metadata."""
    if not (text or "").strip():
        return text
    block = format_meta_seo_publishing_lines(parse_meta_seo_artifact(meta_seo_text))
    if not block:
        return text

    start = text.find("---PUBLISHING METADATA START---")
    end = text.find("---PUBLISHING METADATA END---")
    if start == -1 or end == -1 or end <= start:
        return text

    head = text[: start + len("---PUBLISHING METADATA START---")]
    tail = text[end:]
    body = text[start + len("---PUBLISHING METADATA START---") : end]

    body = re.sub(r"^META TITLE:.*\n", "", body, flags=re.MULTILINE)
    body = re.sub(
        r"^META TITLE OPTIONS[^\n]*\n(?:\s+\d+\..*\n)*",
        "",
        body,
        flags=re.MULTILINE,
    )
    body = re.sub(r"^META DESCRIPTION:.*\n", "", body, flags=re.MULTILINE)
    body = re.sub(
        r"^META DESCRIPTION OPTIONS[^\n]*\n(?:\s+\d+\..*\n)*",
        "",
        body,
        flags=re.MULTILINE,
    )

    anchor = "H1 WORD COUNT:"
    if re.search(rf"^{re.escape(anchor)}", body, re.MULTILINE):
        body = re.sub(
            rf"^({re.escape(anchor)}.*)$",
            rf"\1\n{block}",
            body,
            count=1,
            flags=re.MULTILINE,
        )
    elif re.search(r"^H1 TITLE:", body, re.MULTILINE):
        body = re.sub(
            r"^(H1 TITLE:.*)$",
            rf"\1\n{block}",
            body,
            count=1,
            flags=re.MULTILINE,
        )
    else:
        body = f"{block}\n{body}"

    return head + body + tail


def topic_title_from_topic_card_markdown(text: str) -> str:
    """Human title from a generated topic_card.md (not the START/END markers)."""
    if not (text or "").strip():
        return ""
    fields = _parse_topic_card_field_map(text)
    for key in (
        "TOPIC",
        "SEED KEYWORD",
        "PRIMARY KEYWORD",
        "SUGGESTED ANGLE",
        "CONTENT TYPE",
    ):
        v = (fields.get(key) or "").strip()
        if v:
            return v[:500]
    for line in text.splitlines():
        t = line.strip().lstrip("#").strip()
        if t and not t.startswith("---"):
            return t[:500]
    return ""


def is_placeholder_topic_title(topic: str | None) -> bool:
    t = (topic or "").strip()
    if not t or t.lower() in ("untitled", "(untitled)", "(untitled run)"):
        return True
    return t.startswith("---") or t in (TOPIC_CARD_START, TOPIC_CARD_END)
