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
    "notes": "Notes",
    "semrush_notes": "Semrush / keyword research",
}


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
            out[label] = text[:4000]
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


def faq_editorial_notice() -> str:
    return (
        "\n\n=== FAQ SECTION (REQUIRED FOR SEO) ===\n"
        "Include a **Frequently Asked Questions** block in the outline and draft.\n"
        "- Placement: after the main body sections, **before** the conclusion/CTA.\n"
        "- Format: H2 `## Frequently Asked Questions` then 5–7 items.\n"
        "- Each item: `### Question here?` then a direct 2–4 sentence answer (40–80 words each).\n"
        "- Questions must match real searcher intent (cost, timeline, compliance, how-to, vs alternatives).\n"
        "- Pull questions from SERP gaps, PAA-style queries, and the topic card — not generic filler.\n"
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
        "- **Body keyword use:** use the primary keyword once in the first 100 body words and "
        "do not repeat that exact phrase elsewhere in body prose. Use each secondary keyword "
        "at most once across headings and body prose. Metadata is counted separately.\n"
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
        f"\n\n=== DRAFT LENGTH (NON-NEGOTIABLE) ===\n"
        f"Editor form Word Count: **{target:,}**.\n"
        f"Write at least **{low:,}** words of body prose; aim for **{target:,}** "
        f"(max **{high:,}**). FAQ is additional and does not count. Short body drafts are invalid.\n"
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
