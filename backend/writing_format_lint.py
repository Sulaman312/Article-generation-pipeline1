"""Deterministic linting for writing-format guidelines (no LLM)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from . import yoast_transitions

Stage = Literal["outline", "draft", "final", "brief"]

BRIEF_START = "---BRIEF START---"
BRIEF_END = "---BRIEF END---"

MAX_SENTENCE_WORDS = 30
MAX_PARAGRAPH_SENTENCES = 4
# Legacy Arsuno default — prefer resolve_cta_href() from workspace artifacts.
DEMO_CTA_SLUG = "/book-a-demo/"
DEFAULT_CTA_HREF = "/contact"
_BANNED_DEMO_SLUGS = ("/demo", "/request-demo")

# Long dashes that must never appear in published copy (article, meta, brief).
# Includes em dash, en dash, figure dash, horizontal bar, minus, 2/3-em dashes.
_EM_DASH_CHARS = (
    "\u2014",  # —
    "\u2013",  # –
    "\u2015",  # ―
    "\u2012",  # ‒
    "\u2212",  # −
    "\u2e3a",  # ⸺
    "\u2e3b",  # ⸻
)
_DASH_CLASS = "".join(_EM_DASH_CHARS)
_BANNED_CLOSING_HEADING = re.compile(
    r"^(conclusion|final thoughts|in summary|summary|closing thoughts|wrap[- ]?up)\.?$",
    re.I,
)
_HEADING_MD_RE = re.compile(r"^(#{1,4})\s+(.+)$")
_OUTLINE_HEADING_RE = re.compile(r"^(H[1-4]):\s*(.+)$", re.I)
_WORD_RE = re.compile(r"\b[\w''’-]+\b", re.UNICODE)
# Allow accented capitals (French À, É, …) at sentence starts.
_SENTENCE_SPLIT_RE = re.compile(
    r'(?<=[.!?])\s+(?=[\\"\'(\[]*[A-ZÀÂÄÆÇÉÈÊËÎÏÔŒÙÛÜŸ])',
    re.UNICODE,
)
_ACRONYM_RE = re.compile(r"^[A-Z0-9]{2,}$")
_FR_BODY_HINT_RE = re.compile(
    r"\b(les|des|une|dans|pour|avec|est|sont|cette|ces|qui|que|pas|"
    r"aussi|donc|ainsi|cependant|lorsque|selon)\b",
    re.I,
)


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


def lint(
    text: str,
    *,
    stage: Stage = "draft",
    cta_href: str | None = None,
    lang: str | None = None,
) -> LintReport:
    """Run stage-appropriate format checks."""
    if stage == "outline":
        return _lint_outline(text)
    if stage == "brief":
        return _lint_brief(text)
    return _lint_article(text, stage=stage, cta_href=cta_href, lang=lang)


def detect_article_lang(text: str, *, hint: str | None = None) -> str:
    """Prefer explicit hint; otherwise score French function words in the body."""
    code = (hint or "").strip().lower()
    if code in ("fr", "en", "de", "es", "it"):
        return code
    body = _article_body(text)
    sample = body[:8000]
    fr_hits = len(_FR_BODY_HINT_RE.findall(sample))
    if fr_hits >= 12 or "questions fréquentes" in sample.lower():
        return "fr"
    return "en"


def strip_em_dashes(text: str) -> tuple[str, bool]:
    """Replace Unicode em/en dashes with colons, commas, or ASCII hyphens."""
    if not text:
        return text, False
    original = text
    out = text
    out = re.sub(r"&mdash;|&#8212;|&#x2014;", ": ", out, flags=re.I)
    out = re.sub(r"&ndash;|&#8211;|&#x2013;", "-", out, flags=re.I)
    out = out.replace(" -- ", ": ")
    if any(ch in out for ch in _EM_DASH_CHARS):
        for dash in _EM_DASH_CHARS:
            out = out.replace(f" {dash} ", ": ")
            out = out.replace(f" {dash}", ":")
            out = out.replace(f"{dash} ", ": ")
        out = re.sub(rf"(?<=\d)[{_DASH_CLASS}](?=\d)", "-", out)
        out = re.sub(r"[\u2014\u2015\u2e3a\u2e3b]", ", ", out)
        out = re.sub(r"[\u2012\u2013\u2212]", "-", out)
    return out, out != original


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
                        "Em dash or en dash found; use commas, colons, or ASCII hyphens.",
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
                        "Em dash or en dash found; use commas, colons, or ASCII hyphens.",
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


def _lint_article(
    text: str,
    *,
    stage: Stage,
    cta_href: str | None = None,
    lang: str | None = None,
) -> LintReport:
    report = LintReport(stage=stage)
    body = _article_body(text)
    lines = body.splitlines()
    h2_lines: list[tuple[int, str]] = []
    article_lang = detect_article_lang(text, hint=lang)

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
                        "Em dash or en dash found; use commas, colons, or ASCII hyphens.",
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
    _lint_transition_words(body, report, lang=article_lang)
    _lint_repeated_starts(body, report, lang=article_lang)

    if stage == "final":
        _lint_cta_slugs(body, report, cta_href=cta_href)

    return report


def _collect_body_sentence_groups(body: str) -> list[list[str]]:
    """Body prose sentences grouped by section (a heading starts a new group).

    Skips CTAs, images, bullets and code. Used for the transition ratio (flattened)
    and for the repeated-sentence-start check (which must not run across headings).
    """
    groups: list[list[str]] = [[]]
    for block in re.split(r"\n\s*\n", body or ""):
        block = block.strip()
        if not block:
            continue
        first = block.splitlines()[0].strip()
        if _HEADING_MD_RE.match(first):
            if groups[-1]:
                groups.append([])
            continue
        if first.startswith("```"):
            continue
        if re.match(r"^[-*+]\s", first):
            continue
        if first.startswith("**") and first.endswith("**"):
            continue
        if first.startswith("![") or first.startswith("IMAGE:"):
            continue
        groups[-1].extend(_sentences(block))
    return [g for g in groups if g]


def _collect_body_sentences(body: str) -> list[str]:
    """Body prose sentences only (skip headings, CTAs, images, bullets)."""
    return [s for group in _collect_body_sentence_groups(body) for s in group]


def _lint_transition_words(body: str, report: LintReport, *, lang: str) -> None:
    """Yoast: ≥30% of body sentences need a recognized transition word."""
    if lang not in ("en", "fr"):
        return
    sents = _collect_body_sentences(body)
    if not yoast_transitions.meets_threshold(sents, lang):
        ratio = yoast_transitions.transition_ratio(sents, lang)
        pct = int(round(ratio * 100))
        need = int(yoast_transitions.MIN_TRANSITION_RATIO * 100)
        examples = yoast_transitions.prompt_examples(lang)
        avoid = (
            ' Do not use "de plus" — Yoast French does not count it; use "en outre" or "en plus".'
            if lang == "fr"
            else ""
        )
        report.violations.append(
            FormatViolation(
                "TRANSITION_WORDS",
                (
                    f"Only ~{pct}% of body sentences use Yoast-recognized transition "
                    f"words (need ≥{need}%). Weave natural connectors "
                    f"({examples}).{avoid} Prefer starting follow-up sentences with a "
                    "connector after you split long ideas."
                ),
                excerpt=f"{len(sents)} sentences scored",
            )
        )


MAX_SAME_START_RUN = 2  # three sentences in a row with the same first word is a violation
_LEADING_NOISE_RE = re.compile(r"^[\s\"'“”‘’«»(\[*_>•\-]+")
_FIRST_WORD_RE = re.compile(r"[^\W\d_]+|\d+", re.UNICODE)


def sentence_first_word(sentence: str) -> str:
    """Lower-cased first word of a sentence; an elision counts as its own word
    (« L'équipe » starts with « l »), so « L'… L'… L'… » is caught too."""
    text = _LEADING_NOISE_RE.sub("", (sentence or "").replace("’", "'"))
    m = _FIRST_WORD_RE.match(text)
    return m.group(0).lower() if m else ""


def find_repeated_starts(
    sentences: list[str], *, max_run: int = MAX_SAME_START_RUN
) -> list[tuple[str, list[str]]]:
    """Runs longer than ``max_run`` sentences that start with the same word.

    Returns ``[(word, [sentences of the run])]``, one entry per maximal run.
    """
    runs: list[tuple[str, list[str]]] = []
    current_word = ""
    current: list[str] = []

    def flush() -> None:
        if current_word and len(current) > max_run:
            runs.append((current_word, list(current)))

    for sent in sentences:
        word = sentence_first_word(sent)
        if word and word == current_word:
            current.append(sent)
            continue
        flush()
        current_word, current = word, ([sent] if word else [])
    flush()
    return runs


def _lint_repeated_starts(body: str, report: LintReport, *, lang: str) -> None:
    """Never start three sentences in a row with the same word."""
    for group in _collect_body_sentence_groups(body):
        for word, run in find_repeated_starts(group):
            if lang == "fr":
                message = (
                    f"{len(run)} phrases de suite commencent par « {word} » (maximum "
                    f"{MAX_SAME_START_RUN}). Variez les débuts de phrase : réorganisez ou "
                    "ajoutez un connecteur (ainsi, en effet, par ailleurs, en revanche, "
                    "donc, toutefois…)."
                )
            else:
                message = (
                    f"{len(run)} sentences in a row start with \"{word}\" (max "
                    f"{MAX_SAME_START_RUN}). Vary the openings: restructure or add a "
                    "connector."
                )
            report.violations.append(
                FormatViolation(
                    "REPEATED_SENTENCE_START",
                    message,
                    excerpt=" | ".join(s[:50] for s in run[:3]),
                )
            )


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


def _preferred_cta_href(cta_href: str | None) -> str:
    href = (cta_href or "").strip()
    if href:
        return href.rstrip("/")
    return DEFAULT_CTA_HREF


def _lint_cta_slugs(
    body: str, report: LintReport, *, cta_href: str | None = None
) -> None:
    preferred = _preferred_cta_href(cta_href)
    # Relative banned paths only (absolute URLs are checked separately below).
    for m in re.finditer(r"\]\((/[^)]+)\)", body):
        slug = m.group(1).rstrip("/") + "/"
        norm = slug if slug.startswith("/") else f"/{slug}"
        for banned in _BANNED_DEMO_SLUGS:
            b = banned if banned.endswith("/") else banned + "/"
            if norm.rstrip("/") == b.rstrip("/") or norm.startswith(b):
                report.violations.append(
                    FormatViolation(
                        "CTA_DEMO_SLUG",
                        f"CTA must use {preferred}, not {banned}.",
                        excerpt=m.group(0)[:80],
                    )
                )
    # Hardcoded legacy Arsuno demo slug is wrong when this client uses /contact.
    if preferred.rstrip("/") != DEMO_CTA_SLUG.rstrip("/"):
        for m in re.finditer(
            rf"\]\({re.escape(DEMO_CTA_SLUG.rstrip('/'))}/?\)", body, re.I
        ):
            report.violations.append(
                FormatViolation(
                    "CTA_WRONG_HREF",
                    f"CTA must use the project CTA URL ({preferred}), not {DEMO_CTA_SLUG}.",
                    excerpt=m.group(0)[:80],
                )
            )


def apply_deterministic_fixes(
    text: str, *, cta_href: str | None = None
) -> tuple[str, list[str]]:
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

    preferred = _preferred_cta_href(cta_href)
    # Absolute preferred URLs keep no forced trailing slash; relative keep one.
    if preferred.startswith("http://") or preferred.startswith("https://"):
        replacement = preferred
    else:
        replacement = preferred if preferred.endswith("/") else preferred + "/"

    fixed = body
    for banned in _BANNED_DEMO_SLUGS:
        pattern = re.compile(
            rf"\]\({re.escape(banned.rstrip('/'))}/?\)",
            re.I,
        )
        if pattern.search(fixed):
            fixed = pattern.sub(f"]({replacement})", fixed)
            log.append(f"Replaced demo slug {banned} → {replacement}")

    # Replace legacy /book-a-demo/ when this workspace uses a different CTA.
    if preferred.rstrip("/") != DEMO_CTA_SLUG.rstrip("/"):
        demo_pat = re.compile(
            rf"\]\({re.escape(DEMO_CTA_SLUG.rstrip('/'))}/?\)",
            re.I,
        )
        if demo_pat.search(fixed):
            fixed = demo_pat.sub(f"]({replacement})", fixed)
            log.append(f"Replaced {DEMO_CTA_SLUG} → {replacement}")

    if fixed == body and not em_fixed:
        return text, log

    from . import faq_schema

    if faq_schema.FINAL_ARTICLE_START in current:
        return faq_schema.replace_final_article_body(current, fixed), log
    if fixed != body:
        return fixed, log
    return current, log
