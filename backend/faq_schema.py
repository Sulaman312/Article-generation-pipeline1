"""Build FAQPage JSON-LD from markdown FAQ sections (WordPress / CMS paste)."""

from __future__ import annotations

import json
import re

FAQ_SCHEMA_START = "---FAQ SCHEMA (JSON-LD) START---"
FAQ_SCHEMA_END = "---FAQ SCHEMA (JSON-LD) END---"
FINAL_ARTICLE_START = "---FINAL ARTICLE START---"
FINAL_ARTICLE_END = "---FINAL ARTICLE END---"
CORRECTED_ARTICLE_START = "---CORRECTED ARTICLE START---"
CORRECTED_ARTICLE_END = "---CORRECTED ARTICLE END---"
MIN_FAQ_QUESTIONS = 5

_FAQ_HEADING = re.compile(
    r"^##\s+.*\b(faq|frequently\s+asked\s+questions)\b.*$",
    re.IGNORECASE,
)
_H3 = re.compile(r"^###\s+(.+)$")


def extract_corrected_article_body(text: str) -> str:
    if not text:
        return ""
    start = text.find(CORRECTED_ARTICLE_START)
    end = text.find(CORRECTED_ARTICLE_END)
    if start == -1 or end == -1 or end <= start:
        return ""
    return text[start + len(CORRECTED_ARTICLE_START) : end].strip()


def format_faq_block(pairs: list[tuple[str, str]]) -> str:
    lines = ["## Frequently Asked Questions", ""]
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


def insert_faq_block(article: str, pairs: list[tuple[str, str]]) -> str:
    """Insert or replace the FAQ section with the given Q&A pairs."""
    if not pairs:
        return article
    block = format_faq_block(pairs)
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


def ensure_faq_from_reference(article: str, reference: str) -> str:
    """Restore FAQ Q&As when a later step dropped items from the draft/fact-check."""
    ref_pairs = extract_faq_pairs(reference)
    if len(ref_pairs) < 2:
        return article
    cur_pairs = extract_faq_pairs(article)
    if len(cur_pairs) >= len(ref_pairs):
        return article
    return insert_faq_block(article, ref_pairs)


def extract_faq_pairs(markdown: str) -> list[tuple[str, str]]:
    """Parse H3 questions and answers under a FAQ H2 section."""
    if not (markdown or "").strip():
        return []

    lines = markdown.splitlines()
    in_faq = False
    section_lines: list[str] = []

    for line in lines:
        if _FAQ_HEADING.match(line.strip()):
            in_faq = True
            continue
        if in_faq and line.strip().startswith("## ") and not _FAQ_HEADING.match(
            line.strip()
        ):
            break
        if in_faq:
            section_lines.append(line)

    if not section_lines:
        return []

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
        m = _H3.match(line.strip())
        if m:
            flush()
            question = m.group(1).strip()
            continue
        if question is not None:
            answer_lines.append(line)

    flush()
    return pairs


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


def extract_final_article_body(text: str) -> str:
    if not text:
        return ""
    start = text.find(FINAL_ARTICLE_START)
    end = text.find(FINAL_ARTICLE_END)
    if start == -1 or end == -1 or end <= start:
        return text
    body = text[start + len(FINAL_ARTICLE_START) : end]
    schema_at = body.find(FAQ_SCHEMA_START)
    if schema_at != -1:
        body = body[:schema_at]
    return body.strip()


def replace_final_article_body(full_text: str, new_article: str) -> str:
    start = full_text.find(FINAL_ARTICLE_START)
    end = full_text.find(FINAL_ARTICLE_END)
    if start == -1 or end == -1 or end <= start:
        return full_text
    head = full_text[: start + len(FINAL_ARTICLE_START)]
    tail = full_text[end:]
    return f"{head}\n{new_article.strip()}\n{tail}"


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

    if FINAL_ARTICLE_END in base:
        idx = base.index(FINAL_ARTICLE_END) + len(FINAL_ARTICLE_END)
        return base[:idx] + wrap_faq_schema_block(script) + base[idx:].lstrip("\n")

    return base + wrap_faq_schema_block(script)
