"""Build FAQPage JSON-LD from markdown FAQ sections (WordPress / CMS paste)."""

from __future__ import annotations

import json
import re

FAQ_SCHEMA_START = "---FAQ SCHEMA (JSON-LD) START---"
FAQ_SCHEMA_END = "---FAQ SCHEMA (JSON-LD) END---"
FINAL_OUTPUT_START = "---FINAL OUTPUT START---"
FINAL_OUTPUT_END = "---FINAL OUTPUT END---"
FINAL_ARTICLE_START = FINAL_OUTPUT_START
FINAL_ARTICLE_END = FINAL_OUTPUT_END
PUBLISHING_METADATA_START = "---PUBLISHING METADATA START---"
PUBLISHING_METADATA_END = "---PUBLISHING METADATA END---"
CORRECTED_ARTICLE_START = "---CORRECTED ARTICLE START---"
CORRECTED_ARTICLE_END = "---CORRECTED ARTICLE END---"
MIN_FAQ_QUESTIONS = 5

_FAQ_HEADING = re.compile(
    r"^##\s+.*\b("
    r"faq|"
    r"frequently\s+asked\s+questions|"
    r"questions?\s+fr[ée]quentes?|"
    r"foire\s+aux\s+questions|"
    r"preguntas?\s+frecuentes?|"
    r"domande?\s+frequenti|"
    r"h[aä]ufige?\s+fragen"
    r")\b.*$",
    re.IGNORECASE,
)
_H3 = re.compile(r"^###\s+(.+)$")
_BOLD_QUESTION = re.compile(r"^\*\*(.+?\?)\*\*\s*$")


def extract_corrected_article_body(text: str) -> str:
    if not text:
        return ""
    start = text.find(CORRECTED_ARTICLE_START)
    end = text.find(CORRECTED_ARTICLE_END)
    if start == -1 or end == -1 or end <= start:
        return ""
    return text[start + len(CORRECTED_ARTICLE_START) : end].strip()


def format_faq_block(
    pairs: list[tuple[str, str]], *, heading: str = "## Frequently Asked Questions"
) -> str:
    lines = [heading.strip(), ""]
    for q, a in pairs:
        lines.append(f"### {q}")
        lines.append("")
        lines.append(a)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


_CLOSING_H2_PATTERNS = (
    r"\n##\s+Conclusion\b",
    r"\n##\s+Final thoughts\b",
    r"\n##\s+In summary\b",
    r"\n##\s+Wrapping up\b",
)


def insert_faq_block(
    article: str,
    pairs: list[tuple[str, str]],
    *,
    heading: str = "## Frequently Asked Questions",
) -> str:
    """Insert or replace the FAQ section with the given Q&A pairs."""
    if not pairs:
        return article
    block = format_faq_block(pairs, heading=heading)
    base = strip_faq_section(article).strip()
    for pat in _CLOSING_H2_PATTERNS:
        m = re.search(pat, base, re.I)
        if m:
            return (
                base[: m.start()].rstrip()
                + "\n\n"
                + block
                + "\n"
                + base[m.start() :].lstrip("\n")
            )
    return base.rstrip() + "\n\n" + block


def ensure_faq_from_reference(
    article: str,
    reference: str,
    *,
    heading: str = "## Frequently Asked Questions",
) -> str:
    """Restore FAQ Q&As when a later step dropped items from the draft/fact-check."""
    ref_pairs = extract_faq_pairs(reference)
    if len(ref_pairs) < 2:
        return article
    cur_pairs = extract_faq_pairs(article)
    if len(cur_pairs) >= len(ref_pairs):
        return article
    return insert_faq_block(article, ref_pairs, heading=heading)


def _parse_faq_section_lines(section_lines: list[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    question: str | None = None
    answer_lines: list[str] = []

    def flush() -> None:
        nonlocal question, answer_lines
        if not question:
            return
        answer = _normalize_answer(answer_lines)
        if answer:
            pairs.append((question, answer))
        question = None
        answer_lines = []

    for line in section_lines:
        stripped = line.strip()
        m = _H3.match(stripped)
        if not m:
            m = _BOLD_QUESTION.match(stripped)
        if m:
            flush()
            question = m.group(1).strip()
            continue
        if question is not None:
            answer_lines.append(line)

    flush()
    return pairs


def extract_faq_sections(markdown: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """Return each FAQ H2 block as (heading, pairs)."""
    if not (markdown or "").strip():
        return []

    lines = markdown.splitlines()
    sections: list[tuple[str, list[tuple[str, str]]]] = []
    in_faq = False
    current_heading = ""
    section_lines: list[str] = []

    def flush_section() -> None:
        nonlocal section_lines, current_heading
        if not in_faq:
            return
        pairs = _parse_faq_section_lines(section_lines)
        if pairs:
            sections.append((current_heading, pairs))
        section_lines = []

    for line in lines:
        stripped = line.strip()
        if _FAQ_HEADING.match(stripped):
            flush_section()
            in_faq = True
            current_heading = stripped
            continue
        if in_faq and stripped.startswith("## ") and not _FAQ_HEADING.match(stripped):
            flush_section()
            in_faq = False
            current_heading = ""
        elif in_faq:
            section_lines.append(line)

    flush_section()
    return sections


def extract_faq_pairs(markdown: str) -> list[tuple[str, str]]:
    """Parse all FAQ H2 blocks and merge Q&A pairs (deduped by question text)."""
    sections = extract_faq_sections(markdown)
    if not sections:
        return []

    seen: set[str] = set()
    merged: list[tuple[str, str]] = []
    for _heading, pairs in sections:
        for q, a in pairs:
            key = q.lower().strip()
            if key in seen:
                continue
            seen.add(key)
            merged.append((q, a))
    return merged


def _faq_section_lang_score(
    heading: str, pairs: list[tuple[str, str]], lang: str
) -> int:
    score = len(pairs) * 5
    h = heading.lower()
    if lang == "fr":
        if "fréquent" in h or "foire aux" in h:
            score += 100
        if "frequently asked" in h:
            score -= 80
    elif lang == "en":
        if "frequently asked" in h or re.fullmatch(r"##\s+faq\b", h):
            score += 100
        if "fréquent" in h or "foire aux" in h:
            score -= 80
    french_markers = sum(
        1 for q, a in pairs for ch in f"{q} {a}" if ch in "àâäéèêëïîôùûüçœæ"
    )
    if lang == "fr":
        score += french_markers * 3
    elif lang == "en":
        score -= french_markers * 3
    return score


def consolidate_faq_sections(
    article: str,
    *,
    heading: str = "## Frequently Asked Questions",
    lang: str = "en",
) -> str:
    """Collapse duplicate FAQ blocks into one localized section."""
    sections = extract_faq_sections(article)
    if not sections:
        return article

    target_heading = heading.strip()
    best_heading, best_pairs = max(
        sections,
        key=lambda item: _faq_section_lang_score(item[0], item[1], lang),
    )
    if (
        len(sections) == 1
        and best_heading.strip() == target_heading
    ):
        return article

    if not best_pairs:
        return article
    base = strip_faq_section(article).strip()
    return insert_faq_block(base, best_pairs, heading=target_heading)


def _normalize_answer(lines: list[str]) -> str:
    parts: list[str] = []
    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        s = re.sub(r"^[-*]\s+", "", s)
        s = re.sub(r"^\d+\.\s+", "", s)
        parts.append(s)
    return " ".join(parts).strip()


def build_faq_page_schema(pairs: list[tuple[str, str]]) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {"@type": "Answer", "text": a},
            }
            for q, a in pairs
        ],
    }


def faq_schema_script_tag(pairs: list[tuple[str, str]]) -> str:
    payload = json.dumps(build_faq_page_schema(pairs), indent=2, ensure_ascii=False)
    return f'<script type="application/ld+json">\n{payload}\n</script>'


def wrap_faq_schema_block(script_tag: str) -> str:
    return f"\n\n{FAQ_SCHEMA_START}\n{script_tag.strip()}\n{FAQ_SCHEMA_END}\n"


def strip_publishing_metadata_block(text: str) -> str:
    """Remove legacy publishing metadata wrapper from final_output artifacts."""
    if not text:
        return ""
    start = text.find(PUBLISHING_METADATA_START)
    end = text.find(PUBLISHING_METADATA_END)
    if start == -1 or end == -1 or end <= start:
        return text
    before = text[:start].rstrip()
    after = text[end + len(PUBLISHING_METADATA_END) :].lstrip()
    if before and after:
        return f"{before}\n\n{after}".strip()
    return (before or after).strip()


def wrap_final_article(article_md: str) -> str:
    body = (article_md or "").strip()
    if not body:
        return ""
    return f"{FINAL_OUTPUT_START}\n{body}\n{FINAL_OUTPUT_END}\n"


def extract_final_article_body(text: str) -> str:
    if not text:
        return ""
    cleaned = strip_publishing_metadata_block(text)
    marker_pairs = [
        (FINAL_OUTPUT_START, FINAL_OUTPUT_END),
        ("---FINAL ARTICLE START---", "---FINAL ARTICLE END---"),
    ]
    for start, end in marker_pairs:
        s = cleaned.find(start)
        e = cleaned.find(end)
        if s != -1 and e != -1 and e > s:
            body = cleaned[s + len(start) : e]
            schema_at = body.find(FAQ_SCHEMA_START)
            if schema_at != -1:
                body = body[:schema_at]
            return body.strip()
    return cleaned.strip()


def replace_final_article_body(full_text: str, new_article: str) -> str:
    for start, end in (
        (FINAL_OUTPUT_START, FINAL_OUTPUT_END),
        ("---FINAL ARTICLE START---", "---FINAL ARTICLE END---"),
    ):
        s = full_text.find(start)
        e = full_text.find(end)
        if s != -1 and e != -1 and e > s:
            head = full_text[: s + len(start)]
            tail = full_text[e:]
            return f"{head}\n{new_article.strip()}\n{tail}"
    return full_text


def extract_faq_schema_script(text: str) -> str:
    if not text:
        return ""
    start = text.find(FAQ_SCHEMA_START)
    end = text.find(FAQ_SCHEMA_END)
    if start == -1 or end == -1 or end <= start:
        return ""
    return text[start + len(FAQ_SCHEMA_START) : end].strip()


def strip_faq_section(markdown: str) -> str:
    """Remove the FAQ H2 block (for editorial word-count limits)."""
    if not (markdown or "").strip():
        return ""
    lines = markdown.splitlines()
    out: list[str] = []
    in_faq = False
    for line in lines:
        stripped = line.strip()
        if _FAQ_HEADING.match(stripped):
            in_faq = True
            continue
        if in_faq and stripped.startswith("## ") and not _FAQ_HEADING.match(stripped):
            in_faq = False
        if not in_faq:
            out.append(line)
    return "\n".join(out).strip()


def markdown_for_word_count(markdown: str) -> str:
    """Article markdown counted toward the form word target (excludes FAQ + JSON-LD)."""
    text = strip_faq_schema_block(markdown or "")
    text = re.sub(
        r"<script\s+type=[\"']application/ld\+json[\"'][^>]*>[\s\S]*?</script>",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    return strip_faq_section(text)


def strip_faq_schema_block(text: str) -> str:
    if FAQ_SCHEMA_START not in text:
        return text
    start = text.find(FAQ_SCHEMA_START)
    end = text.find(FAQ_SCHEMA_END)
    if end == -1:
        return text[:start].rstrip()
    return (text[:start] + text[end + len(FAQ_SCHEMA_END) :]).strip()


def ensure_faq_schema_block(final_output: str, *, min_questions: int = 2) -> str:
    """Append or refresh FAQ JSON-LD block when the article has a FAQ section."""
    text = (final_output or "").strip()
    if not text:
        return final_output

    article_md = extract_final_article_body(text)
    pairs = extract_faq_pairs(article_md)
    if len(pairs) < min_questions:
        return strip_faq_schema_block(text)

    script = faq_schema_script_tag(pairs)
    base = strip_faq_schema_block(text)

    if FINAL_OUTPUT_END in base:
        idx = base.index(FINAL_OUTPUT_END) + len(FINAL_OUTPUT_END)
        return base[:idx] + wrap_faq_schema_block(script) + base[idx:].lstrip("\n")
    if FINAL_ARTICLE_END in base:
        idx = base.index(FINAL_ARTICLE_END) + len(FINAL_ARTICLE_END)
        return base[:idx] + wrap_faq_schema_block(script) + base[idx:].lstrip("\n")

    return base + wrap_faq_schema_block(script)
