"""Deterministic linting for writing-format guidelines (no LLM)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

Stage = Literal["outline", "draft", "final", "brief"]

BRIEF_START = "---BRIEF START---"
BRIEF_END = "---BRIEF END---"

MAX_SENTENCE_WORDS = 30
MAX_PARAGRAPH_SENTENCES = 4
DEMO_CTA_SLUG = "/book-a-demo/"
_BANNED_DEMO_SLUGS = ("/demo", "/request-demo")

_EM_DASH_CHARS = ("\u2014",)  # — only; en-dash in ranges (2–4) is allowed in stats
_BANNED_CLOSING_HEADING = re.compile(
    r"^(conclusion|final thoughts|in summary|summary|closing thoughts|wrap[- ]?up)\.?$",
    re.I,
)
_HEADING_MD_RE = re.compile(r"^(#{1,4})\s+(.+)$")
_OUTLINE_HEADING_RE = re.compile(r"^(H[1-4]):\s*(.+)$", re.I)
_WORD_RE = re.compile(r"\b[\w''’-]+\b", re.UNICODE)
_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+(?=[A-Z"\'(])')
_ACRONYM_RE = re.compile(r"^[A-Z0-9]{2,}$")


@dataclass(frozen=True)
class FormatViolation:
    code: str
    message: str
    line: int | None = None
    excerpt: str | None = None


@dataclass
class LintReport:
    violations: list[FormatViolation] = field(default_factory=list)
    stage: Stage = "draft"

    @property
    def ok(self) -> bool:
        return not self.violations

    def summary(self, *, max_items: int = 25) -> str:
        if self.ok:
            return "No format violations."
        lines = [f"- [{v.code}] {v.message}" for v in self.violations[:max_items]]
        if len(self.violations) > max_items:
            lines.append(f"- … and {len(self.violations) - max_items} more")
        return "\n".join(lines)


def lint(text: str, *, stage: Stage = "draft") -> LintReport:
    """Run stage-appropriate format checks."""
    if stage == "outline":
        return _lint_outline(text)
    if stage == "brief":
        return _lint_brief(text)
    return _lint_article(text, stage=stage)


def strip_em_dashes(text: str) -> tuple[str, bool]:
    """Replace Unicode em dashes with colons or commas."""
    if not text or "\u2014" not in text:
        return text, False
    out = text.replace(" — ", ": ")
    out = out.replace(" —", ":")
    out = out.replace("— ", ": ")
    out = out.replace("—", ", ")
    return out, out != text


def _lint_em_dashes_in_lines(body: str, report: LintReport) -> None:
    for i, line in enumerate(body.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        for ch in _EM_DASH_CHARS:
            if ch in stripped:
                report.violations.append(
                    FormatViolation(
                        "EM_DASH",
                        "Em dash found; use commas, colons, or sentence breaks.",
                        line=i,
                        excerpt=stripped[:120],
                    )
                )
                break


def _lint_brief(text: str) -> LintReport:
    report = LintReport(stage="brief")
    body = _brief_body(text) or (text or "")
    _lint_em_dashes_in_lines(body, report)
    return report


def _brief_body(text: str) -> str:
    start = text.find(BRIEF_START)
    end = text.find(BRIEF_END)
    if start == -1 or end == -1 or end <= start:
        return ""
    return text[start + len(BRIEF_START) : end].strip()


def _lint_outline(text: str) -> LintReport:
    report = LintReport(stage="outline")
    lines = (text or "").splitlines()
    h2_titles: list[tuple[int, str]] = []
    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        for ch in _EM_DASH_CHARS:
            if ch in stripped:
                report.violations.append(
                    FormatViolation(
                        "EM_DASH",
                        "Em dash found; use commas, colons, or sentence breaks.",
                        line=i,
                        excerpt=stripped[:120],
                    )
                )
                break
        m = _OUTLINE_HEADING_RE.match(stripped)
        if not m:
            continue
        level, title = m.group(1).upper(), m.group(2).strip()
        if level == "H2":
            h2_titles.append((i, title))
        if _looks_like_title_case(title):
            report.violations.append(
                FormatViolation(
                    "HEADING_TITLE_CASE",
                    f"Outline {level} uses title case; use sentence case.",
                    line=i,
                    excerpt=title[:120],
                )
            )
    if h2_titles:
        _check_banned_closing_heading(report, h2_titles[-1][1], line=h2_titles[-1][0])
    return report


def _lint_article(text: str, *, stage: Stage) -> LintReport:
    report = LintReport(stage=stage)
    body = _article_body(text)
    lines = body.splitlines()
    h2_lines: list[tuple[int, str]] = []

    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        hm = _HEADING_MD_RE.match(stripped)
        if hm:
            level, title = len(hm.group(1)), hm.group(2).strip()
            if level <= 4 and _looks_like_title_case(title):
                report.violations.append(
                    FormatViolation(
                        "HEADING_TITLE_CASE",
                        f"H{level} uses title case; use sentence case.",
                        line=i,
                        excerpt=title[:120],
                    )
                )
            if level == 2:
                h2_lines.append((i, title))
            continue
        for ch in _EM_DASH_CHARS:
            if ch in stripped:
                report.violations.append(
                    FormatViolation(
                        "EM_DASH",
                        "Em dash found; use commas, colons, or sentence breaks.",
                        line=i,
                        excerpt=stripped[:120],
                    )
                )
                break

    if h2_lines:
        _check_banned_closing_heading(report, h2_lines[-1][1], line=h2_lines[-1][0])

    _lint_paragraphs(body, report)
    _lint_h2_h3_bridges(lines, report)
    _lint_sections_end_on_bullets(lines, report)

    if stage == "final":
        _lint_cta_slugs(body, report)

    return report


def _article_body(text: str) -> str:
    """Strip publishing wrappers; lint prose only."""
    from . import faq_schema

    extracted = faq_schema.extract_final_article_body(text)
    if extracted:
        return extracted.strip()
    for marker in ("---CORRECTED ARTICLE START---", "---DRAFT NOTE:"):
        if marker in text:
            chunk = text.split(marker, 1)[-1]
            if "---" in chunk[:40]:
                continue
            return chunk.strip()
    return (text or "").strip()


def _check_banned_closing_heading(
    report: LintReport, title: str, *, line: int
) -> None:
    clean = re.sub(r"^#+\s*", "", title).strip()
    clean = re.sub(r"^\d+\.\s*", "", clean).strip()
    if _BANNED_CLOSING_HEADING.match(clean):
        report.violations.append(
            FormatViolation(
                "BANNED_CLOSING_HEADING",
                'Closing section must not use generic headings like "Conclusion".',
                line=line,
                excerpt=clean[:120],
            )
        )


def _looks_like_title_case(heading: str) -> bool:
    text = re.sub(r"^\d+\.\s*", "", heading).strip()
    words = _WORD_RE.findall(text)
    if len(words) < 2:
        return False
    mid_caps = 0
    for w in words[1:]:
        if _ACRONYM_RE.match(w):
            continue
        if w[0].isupper():
            mid_caps += 1
    return mid_caps >= 2


def _plain_for_sentences(paragraph: str) -> str:
    plain = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", paragraph)
    plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", plain)
    plain = re.sub(r"`[^`]+`", " ", plain)
    plain = re.sub(r"^\s*[-*+]\s+", "", plain, flags=re.MULTILINE)
    return plain.strip()


def _sentences(paragraph: str) -> list[str]:
    plain = _plain_for_sentences(paragraph)
    if not plain:
        return []
    parts = _SENTENCE_SPLIT_RE.split(plain)
    return [p.strip() for p in parts if p.strip()]


def _word_count(sentence: str) -> int:
    return len(_WORD_RE.findall(sentence))


def _lint_paragraphs(body: str, report: LintReport) -> None:
    blocks = re.split(r"\n\s*\n", body)
    line_offset = 1
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        first_line = block.splitlines()[0].strip()
        if _HEADING_MD_RE.match(first_line) or first_line.startswith("```"):
            line_offset += block.count("\n") + 2
            continue
        if re.match(r"^[-*+]\s", first_line):
            line_offset += block.count("\n") + 2
            continue
        if first_line.startswith("**") and first_line.endswith("**"):
            line_offset += block.count("\n") + 2
            continue

        sents = _sentences(block)
        if len(sents) > MAX_PARAGRAPH_SENTENCES:
            report.violations.append(
                FormatViolation(
                    "PARAGRAPH_TOO_LONG",
                    f"Paragraph has {len(sents)} sentences (max {MAX_PARAGRAPH_SENTENCES}).",
                    line=line_offset,
                    excerpt=block[:100],
                )
            )
        for sent in sents:
            wc = _word_count(sent)
            if wc > MAX_SENTENCE_WORDS:
                report.violations.append(
                    FormatViolation(
                        "SENTENCE_TOO_LONG",
                        f"Sentence has {wc} words (max {MAX_SENTENCE_WORDS}).",
                        line=line_offset,
                        excerpt=sent[:140],
                    )
                )
        line_offset += block.count("\n") + 2


def _lint_h2_h3_bridges(lines: list[str], report: LintReport) -> None:
    i = 0
    while i < len(lines):
        if not _HEADING_MD_RE.match(lines[i].strip()) or not lines[i].strip().startswith("## "):
            i += 1
            continue
        if lines[i].strip().startswith("###"):
            i += 1
            continue
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j < len(lines) and lines[j].strip().startswith("### "):
            report.violations.append(
                FormatViolation(
                    "H2_H3_NO_BRIDGE",
                    "H3 follows H2 with no bridging prose.",
                    line=j + 1,
                    excerpt=lines[j].strip()[:120],
                )
            )
        i += 1


def _lint_sections_end_on_bullets(lines: list[str], report: LintReport) -> None:
    section_lines: list[str] = []
    section_start = 1
    for i, line in enumerate(lines, start=1):
        if _HEADING_MD_RE.match(line.strip()) and line.strip().startswith("##"):
            if section_lines:
                _check_section_ends_on_bullet(report, section_lines, section_start)
            section_lines = []
            section_start = i + 1
            continue
        if line.strip():
            section_lines.append(line)
    if section_lines:
        _check_section_ends_on_bullet(report, section_lines, section_start)


def _check_section_ends_on_bullet(
    report: LintReport, section_lines: list[str], line_hint: int
) -> None:
    for line in reversed(section_lines):
        s = line.strip()
        if not s:
            continue
        if re.match(r"^[-*+]\s", s):
            report.violations.append(
                FormatViolation(
                    "SECTION_ENDS_ON_BULLET",
                    "Section ends on a bullet; close with prose.",
                    line=line_hint,
                    excerpt=s[:120],
                )
            )
        break


def _lint_cta_slugs(body: str, report: LintReport) -> None:
    for m in re.finditer(r"\]\((/[^)]+)\)", body):
        slug = m.group(1).rstrip("/") + "/"
        norm = slug if slug.startswith("/") else f"/{slug}"
        for banned in _BANNED_DEMO_SLUGS:
            b = banned if banned.endswith("/") else banned + "/"
            if norm.rstrip("/") == b.rstrip("/") or norm.startswith(b):
                report.violations.append(
                    FormatViolation(
                        "CTA_DEMO_SLUG",
                        f"Demo CTA must use {DEMO_CTA_SLUG}, not {banned}.",
                        excerpt=m.group(0)[:80],
                    )
                )


def apply_deterministic_fixes(text: str) -> tuple[str, list[str]]:
    """Safe mechanical fixes before LLM repair. Returns (text, log)."""
    log: list[str] = []
    if not (text or "").strip():
        return text, log

    current, em_fixed = strip_em_dashes(text)
    if em_fixed:
        log.append("Replaced em dashes with colons or commas")

    body = _article_body(current)
    if not body:
        return current, log

    fixed = body
    for banned in _BANNED_DEMO_SLUGS:
        pattern = re.compile(
            rf"\]\({re.escape(banned.rstrip('/'))}/?\)",
            re.I,
        )
        if pattern.search(fixed):
            fixed = pattern.sub(f"]({DEMO_CTA_SLUG.rstrip('/')}/)", fixed)
            log.append(f"Replaced demo slug {banned} → {DEMO_CTA_SLUG}")

    if fixed == body and not em_fixed:
        return text, log

    from . import faq_schema

    if faq_schema.FINAL_ARTICLE_START in current:
        return faq_schema.replace_final_article_body(current, fixed), log
    if fixed != body:
        return fixed, log
    return current, log
