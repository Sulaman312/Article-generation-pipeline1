"""Hard quality gates — fail the step when critical SEO/trust checks fail.

These are deterministic checks (not prompt hope). Call after draft / final generation.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from . import editorial_input
from . import faq_schema
from . import paa_faq
from . import url_verify
from .step_markers import extract_step_body

logger = logging.getLogger(__name__)

LEDE_MIN_WORDS = 40
LEDE_MAX_WORDS = 80
FIRST_N_BODY_WORDS = 100
FAQ_ANSWER_MIN_SENTENCES = 2
FAQ_ANSWER_MAX_SENTENCES = 4

_H1 = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_H2 = re.compile(r"^##\s+.+$", re.MULTILINE)
# Required opening H2 immediately after H1 (Key takeaways — not an article summary).
_OPENING_TAKEAWAYS_H2 = re.compile(
    r"^##\s+(key\s+takeaways?|takeaways?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
# Duplicate / late takeaway-style or "summary" openings — only valid as the first H2 after H1.
_LATE_OPENING_H2 = re.compile(
    r"^#{1,3}\s+(key\s+takeaways?|takeaways?|what\s+you'?ll\s+learn|"
    r"in\s+this\s+article|what\s+we\s+(cover|discuss|explore)|"
    r"summary|résumé|resume|zusammenfassung|"
    r"quick\s+summary|article\s+summary|top\s+takeaways?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_IMAGE_MD = re.compile(r"!\[[^\]]*\]\([^)]+\)")
_MONEY_OR_STAT = re.compile(
    r"(?:[$€£]\s?\d[\d,]*(?:\.\d+)?"
    r"|\b\d[\d,]*(?:\.\d+)?\s?(?:USD|EUR|GBP|CAD|AUD)\b"
    r"|\b\d{1,3}(?:\.\d+)?\s?%\b)",
    re.IGNORECASE,
)
_HTTPS_LINK = re.compile(r"\]\(https?://[^)]+\)", re.IGNORECASE)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_CLAIM_LINE = re.compile(
    r"^\s*[-*]\s*CLAIM\s*:\s*(.+?)(?:\s*\|\s*WHY:.*)?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_APPROVED_FAQ_NUM = re.compile(r"^\s*\d+\.\s+(.+?)\s*$", re.MULTILINE)
_STATUS_RE = re.compile(
    r"STATUS\s*:\s*(APPROVED|NO APPROVED CASE STUDY)\b", re.IGNORECASE
)
_SOURCE_URL_RE = re.compile(r"SOURCE URL\s*:\s*(https?://\S+)", re.IGNORECASE)
_URL_CHECK_RE = re.compile(r"URL CHECK\s*:\s*(OK|FAIL|n/a)\b", re.IGNORECASE)
_PRIMARY_KW_LINE = re.compile(
    r"^PRIMARY KEYWORD\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE
)


class HardGateError(RuntimeError):
    """Raised when hard gates fail after repair attempts."""

    def __init__(self, report: "GateReport"):
        self.report = report
        super().__init__(report.failure_message())


@dataclass
class GateIssue:
    code: str
    message: str
    blocking: bool = True


@dataclass
class GateReport:
    issues: list[GateIssue] = field(default_factory=list)
    lede_words: int | None = None
    body_words: int | None = None
    primary_keyword: str = ""
    faq_count: int = 0

    @property
    def ok(self) -> bool:
        return not any(i.blocking for i in self.issues)

    def blocking_issues(self) -> list[GateIssue]:
        return [i for i in self.issues if i.blocking]

    def failure_message(self) -> str:
        lines = ["Hard gates failed:"]
        for i in self.blocking_issues():
            lines.append(f"- [{i.code}] {i.message}")
        return "\n".join(lines)

    def as_prompt_block(self) -> str:
        if self.ok:
            return "All hard gates passed."
        lines = ["Fix these hard-gate failures (mandatory):"]
        for i in self.blocking_issues():
            lines.append(f"- [{i.code}] {i.message}")
        return "\n".join(lines)


def _article_body(text: str, *, stage: str = "draft") -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    if stage == "final":
        body = (
            faq_schema.extract_final_article_body(raw)
            or faq_schema.strip_publishing_metadata_block(raw)
            or raw
        )
    elif stage == "draft":
        body = extract_step_body("draft", raw) or raw
        # Unwrap ---DRAFT START--- if present inside
        m = re.search(
            r"---DRAFT START---\s*(.*?)\s*---DRAFT END---",
            body,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            body = m.group(1).strip()
    else:
        body = raw
    return body.strip()


def _word_tokens(text: str) -> list[str]:
    cleaned = re.sub(r"^#{1,6}\s+", "", text or "", flags=re.MULTILINE)
    cleaned = re.sub(r"```[\s\S]*?```", " ", cleaned)
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    return re.findall(r"\b[\w''’-]+\b", cleaned, flags=re.UNICODE)


def extract_lede_text(article: str) -> str:
    """Key-takeaways text between ``## Key takeaways`` and the hero image (or next H2)."""
    text = (article or "").replace("\r\n", "\n").strip()
    if not text:
        return ""
    h1 = _H1.search(text)
    if not h1:
        return ""
    after_h1 = text[h1.end() :]
    h2s = list(_H2.finditer(after_h1))
    if not h2s:
        return after_h1.strip()
    first = h2s[0]
    if not _OPENING_TAKEAWAYS_H2.match(first.group(0).strip()):
        # Legacy plain-lede articles: prose between H1 and first H2.
        return after_h1[: first.start()].strip()
    zone_end = h2s[1].start() if len(h2s) > 1 else len(after_h1)
    zone = after_h1[first.end() : zone_end]
    img = _IMAGE_MD.search(zone)
    prose = zone[: img.start()] if img else zone
    return prose.strip()


def check_lede(article: str) -> GateIssue | None:
    """Require H1 → ## Key takeaways → takeaways → hero image → next H2."""
    text = (article or "").replace("\r\n", "\n").strip()
    if not text:
        return GateIssue(
            "lede_missing",
            f"Opening missing — need ## Key takeaways ({LEDE_MIN_WORDS}–{LEDE_MAX_WORDS} words) "
            "then a hero image immediately after H1.",
        )
    h1 = _H1.search(text)
    if not h1:
        return GateIssue("h1_missing", "Article must start with an H1 title.")
    after_h1 = text[h1.end() :]
    h2s = list(_H2.finditer(after_h1))
    if not h2s:
        return GateIssue(
            "summary_missing",
            'First block after H1 must be "## Key takeaways", then takeaways, then a hero image.',
        )
    first_h2 = h2s[0].group(0).strip()
    if not _OPENING_TAKEAWAYS_H2.match(first_h2):
        return GateIssue(
            "summary_heading",
            'First H2 after H1 must be "## Key takeaways" '
            "(order: H1 → Key takeaways → Image → content). Do not use ## Summary.",
        )
    zone_end = h2s[1].start() if len(h2s) > 1 else len(after_h1)
    zone = after_h1[h2s[0].end() : zone_end]
    img = _IMAGE_MD.search(zone)
    if not img:
        return GateIssue(
            "summary_image",
            "Place a hero image immediately after the Key takeaways block, before the next H2 "
            "(`![descriptive alt text](IMAGE: slug)`).",
        )
    prose = zone[: img.start()].strip()
    trailing = zone[img.end() :].strip()
    if trailing and _word_tokens(trailing):
        return GateIssue(
            "summary_order",
            "Order must be H1 → ## Key takeaways → takeaways → image → next H2 "
            "(no extra body prose between the image and the next H2).",
        )
    if not prose:
        return GateIssue(
            "lede_missing",
            f"## Key takeaways content missing — need {LEDE_MIN_WORDS}–{LEDE_MAX_WORDS} words "
            "before the hero image.",
        )
    n = len(_word_tokens(prose))
    if n < LEDE_MIN_WORDS or n > LEDE_MAX_WORDS:
        return GateIssue(
            "lede_length",
            f"## Key takeaways is {n} words; required {LEDE_MIN_WORDS}-{LEDE_MAX_WORDS}.",
        )
    return None


def _answer_sentence_count(answer: str) -> int:
    text = re.sub(r"\s+", " ", (answer or "").strip())
    if not text:
        return 0
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(text) if p.strip()]
    return len(parts)


def check_cited_numbers(article: str) -> list[GateIssue]:
    """Block concrete prices/stats that lack an inline HTTPS citation in-paragraph."""
    text = (article or "").replace("\r\n", "\n")
    # Ignore code fences and image lines
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = _IMAGE_MD.sub(" ", text)
    issues: list[GateIssue] = []
    seen: set[str] = set()
    for para in re.split(r"\n\s*\n", text):
        if not para.strip() or para.strip().startswith("#"):
            continue
        if faq_schema._FAQ_HEADING.match(para.strip()):
            continue
        m = _MONEY_OR_STAT.search(para)
        if not m:
            continue
        if _HTTPS_LINK.search(para):
            continue
        snippet = m.group(0).strip()
        if snippet in seen:
            continue
        seen.add(snippet)
        issues.append(
            GateIssue(
                "uncited_number",
                f'Price/stat "{snippet}" must include an inline HTTPS citation in the same '
                "paragraph, or remove/generalize the number (no invented prices).",
            )
        )
    return issues


def check_no_late_takeaways(article: str) -> GateIssue | None:
    """Fail if takeaways/summary headings appear again after the opening Key takeaways block."""
    text = (article or "").replace("\r\n", "\n").strip()
    if not text:
        return None
    h1 = _H1.search(text)
    if not h1:
        return None
    after_h1 = text[h1.end():]
    h2s = list(_H2.finditer(after_h1))
    # Skip the first H2 (## Key takeaways) — only scan the rest of the body.
    body_after_opening = after_h1[h2s[1].start():] if len(h2s) > 1 else ""
    if not body_after_opening:
        return None
    m = _LATE_OPENING_H2.search(body_after_opening)
    if m:
        heading = m.group(0).strip()
        return GateIssue(
            "late_takeaways",
            f'"{heading}" must not appear in the article body. '
            "Key takeaways belong only in the ## Key takeaways block at the top — "
            "not as ## Summary and not repeated later. Merge into the opening block.",
        )
    return None


def check_word_count(article: str, target: int | None) -> tuple[GateIssue | None, int]:
    words = editorial_input.count_article_words(article)
    if not target:
        return None, words
    low, high = editorial_input.word_count_bounds(target)
    if words < low or words > high:
        return (
            GateIssue(
                "word_count",
                f"Body word count is {words:,}; required {low:,}–{high:,} "
                f"(target {target:,}, FAQ excluded).",
            ),
            words,
        )
    return None, words


def _normalize_phrase(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _phrase_tokens(phrase: str) -> list[str]:
    """Keyword tokens using the same rules as body prose (punctuation ignored)."""
    return [w.lower() for w in _word_tokens(phrase)]


def _plain_keyword(primary: str) -> str:
    return " ".join(_word_tokens(primary or ""))


def _count_phrase_in_words(words: list[str], phrase: str) -> int:
    """Count non-overlapping occurrences of phrase token sequence in word list."""
    needle = _phrase_tokens(phrase)
    if not needle:
        return 0
    n = len(needle)
    hay = [w.lower() for w in words]
    count = 0
    i = 0
    while i <= len(hay) - n:
        if hay[i : i + n] == needle:
            count += 1
            i += n
        else:
            i += 1
    return count


def _body_prose_for_keyword(article: str) -> str:
    """Body prose used for the first-100 keyword scan.

    H1 and other headings do not count. FAQ is excluded.
    """
    body = faq_schema.strip_faq_section(article)
    body_no_h1 = _H1.sub("", body, count=1)
    return re.sub(r"^#{1,6}\s+.*$", "", body_no_h1, flags=re.MULTILINE)


def _keyword_counts(article: str, primary: str) -> tuple[int, int]:
    tokens = _word_tokens(_body_prose_for_keyword(article))
    first = tokens[:FIRST_N_BODY_WORDS]
    rest = tokens[FIRST_N_BODY_WORDS:]
    return (
        _count_phrase_in_words(first, primary),
        _count_phrase_in_words(rest, primary),
    )


def _opening_prose_bounds(article: str) -> tuple[int, int] | None:
    """Character span of the opening prose (Key takeaways, else the first paragraph)."""
    text = (article or "").replace("\r\n", "\n")
    h1 = _H1.search(text)
    if not h1:
        return None
    after = text[h1.end() :]
    h2s = list(_H2.finditer(after))
    if h2s and _OPENING_TAKEAWAYS_H2.match(h2s[0].group(0).strip()):
        zone_rel_start = h2s[0].end()
        zone_rel_end = h2s[1].start() if len(h2s) > 1 else len(after)
        zone = after[zone_rel_start:zone_rel_end]
        img = _IMAGE_MD.search(zone)
        end = h1.end() + zone_rel_start + (img.start() if img else len(zone))
        return h1.end() + zone_rel_start, end
    nxt = _H2.search(after)
    start_rel = re.search(r"\S", after)
    if not start_rel:
        return None
    start = h1.end() + start_rel.start()
    end = h1.end() + nxt.start() if nxt else len(text)
    return start, end


def _keyword_lead(keyword: str) -> str:
    kw = keyword.strip().rstrip(".")
    lower = kw.lower()
    if lower.startswith(("a ", "an ", "the ", "how ", "what ", "why ", "when ", "where ")):
        return kw[0].upper() + kw[1:] if kw[:1].islower() else kw
    article = "an" if lower[:1] in "aeiou" else "a"
    return f"{article} {kw}"


def _weave_keyword_into_line(line: str, keyword: str) -> str:
    m = re.match(r"^(\s*(?:[-*+]|\d+[.)])\s+)(.*)$", line)
    if m:
        prefix, text = m.group(1), m.group(2)
    else:
        m2 = re.match(r"^(\s*)(.*)$", line)
        prefix, text = (m2.group(1), m2.group(2)) if m2 else ("", line)
    rest = text.strip()
    if rest and _count_phrase_in_words(_word_tokens(rest), keyword):
        return line
    lead = _keyword_lead(keyword)
    if rest:
        if rest[0].isupper():
            rest = rest[0].lower() + rest[1:]
        woven = f"For {lead}, {rest}"
    else:
        woven = f"{lead[0].upper() + lead[1:]}."
    return prefix + woven


def _strip_keyword_phrase(text: str, keyword: str) -> str:
    """Remove later exact uses so the opening placement stays the only body use."""
    kw = (keyword or "").strip()
    if not kw:
        return text
    pattern = re.compile(
        r"(?i)\b(?:(?:a|an|the)\s+)?" + re.escape(kw) + r"\b"
    )
    out_lines: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("!["):
            out_lines.append(line)
            continue
        cleaned = pattern.sub("", line)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        cleaned = re.sub(r" +([.,;:!?])", r"\1", cleaned)
        cleaned = re.sub(r"\(\s*\)", "", cleaned)
        out_lines.append(cleaned)
    return "\n".join(out_lines)


def _keyword_sentence(phrase: str) -> str:
    lead = phrase.strip()
    if lead and lead[0].islower():
        lead = lead[0].upper() + lead[1:]
    if not lead.endswith("."):
        lead = f"{lead} belongs in the opening of this article."
    return lead


def ensure_primary_keyword_in_first_100(article: str, primary: str) -> str:
    """Put the exact primary keyword in the first 100 body words.

    Headings do not count. When the phrase is missing from that window, it is
    woven into the first Key takeaways sentence (or the first paragraph) and
    later exact repeats in body prose are removed.
    """
    kw = _plain_keyword(primary)
    if not kw or kw.lower() in ("your target keyword", "not provided"):
        return article
    if not (article or "").strip():
        return article
    text = article.replace("\r\n", "\n")
    in_first, _in_rest = _keyword_counts(text, kw)
    if in_first >= 1:
        return article
    bounds = _opening_prose_bounds(text)
    if bounds:
        start, end = bounds
        block = text[start:end]
        lines = block.split("\n")
        edited = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("![") or stripped.startswith("#"):
                continue
            lines[i] = _weave_keyword_into_line(line, kw)
            edited = True
            head = lines[: i + 1]
            tail = _strip_keyword_phrase("\n".join(lines[i + 1 :]), kw)
            lines = head + ([tail] if lines[i + 1 :] else [])
            break
        if edited:
            text = text[:start] + "\n".join(lines) + _strip_keyword_phrase(text[end:], kw)
        else:
            sentence = _keyword_sentence(kw)
            text = (
                text[:start]
                + sentence
                + "\n\n"
                + block.lstrip("\n")
                + _strip_keyword_phrase(text[end:], kw)
            )
    else:
        sentence = _keyword_sentence(kw)
        h1 = _H1.search(text)
        if h1:
            text = text[: h1.end()] + "\n\n" + sentence + "\n" + text[h1.end() :]
        else:
            text = sentence + "\n\n" + text
    in_first, _in_rest = _keyword_counts(text, kw)
    if in_first >= 1:
        return text
    sentence = _keyword_sentence(kw)
    h1 = _H1.search(text)
    if h1:
        return text[: h1.end()] + "\n\n" + sentence + "\n" + text[h1.end() :]
    return sentence + "\n\n" + text


def check_primary_keyword(article: str, primary: str) -> GateIssue | None:
    kw = (primary or "").strip()
    if not kw or kw.lower() in ("your target keyword", "not provided"):
        return None  # no keyword to enforce
    # Only count keyword occurrences in body prose, not in headings.
    in_first, in_rest = _keyword_counts(article, kw)
    if in_first != 1:
        return GateIssue(
            "keyword_first_100",
            f'Primary keyword "{kw}" must appear verbatim exactly once in the first '
            f"{FIRST_N_BODY_WORDS} body words (found {in_first}). "
            "Headings do not count. Put it in the first Key takeaways sentence.",
        )
    if in_rest > 0:
        return GateIssue(
            "keyword_repeat",
            f'Primary keyword "{kw}" is repeated {in_rest} more time(s) after the '
            f"first {FIRST_N_BODY_WORDS} body words — exact-match body repeats are not allowed.",
        )
    return None


def parse_primary_keyword(*texts: str) -> str:
    for text in texts:
        if not text:
            continue
        m = _PRIMARY_KW_LINE.search(text)
        if m:
            val = m.group(1).strip()
            if val and val.lower() not in ("not provided", "[not provided]"):
                return val
    return ""


def parse_audit_flagged_claims(audit: str) -> list[str]:
    section = _section(audit, r"Flagged\s*/\s*reject list")
    if not section:
        return []
    claims: list[str] = []
    for m in _CLAIM_LINE.finditer(section):
        claim = m.group(1).strip().rstrip("|").strip()
        if len(claim) >= 8:
            claims.append(claim)
    return claims


def parse_audit_approved_faq(audit: str) -> list[str]:
    section = _section(audit, r"Approved FAQ questions")
    if not section:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for m in _APPROVED_FAQ_NUM.finditer(section):
        q = paa_faq.clean_faq_question(m.group(1))
        if not q:
            continue
        key = _norm_q(q)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(q)
    return out


def parse_audit_case_study(audit: str) -> dict:
    section = _section(audit, r"Approved case study")
    if not section:
        return {"status": "", "url": "", "url_check": ""}
    status_m = _STATUS_RE.search(section)
    url_m = _SOURCE_URL_RE.search(section)
    check_m = _URL_CHECK_RE.search(section)
    url = (url_m.group(1).strip().rstrip(".,);]") if url_m else "")
    return {
        "status": (status_m.group(1).upper() if status_m else ""),
        "url": url,
        "url_check": (check_m.group(1).upper() if check_m else ""),
    }


def parse_pipeline_fail_urls(*texts: str) -> list[str]:
    """URLs marked [FAIL] in pipeline URL verification sections."""
    fails: list[str] = []
    for text in texts:
        for m in re.finditer(
            r"\[FAIL\]\s*`?(https?://[^`\s]+)`?", text or "", re.IGNORECASE
        ):
            fails.append(m.group(1).rstrip(".,);]"))
    return fails


def _section(text: str, heading_pat: str) -> str:
    if not text:
        return ""
    m = re.search(
        rf"##\s+{heading_pat}.*?\n(.*?)(?=\n##\s+|\Z)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    return m.group(1).strip() if m else ""


def check_flagged_claims(article: str, claims: list[str]) -> list[GateIssue]:
    issues: list[GateIssue] = []
    hay = _normalize_phrase(faq_schema.strip_faq_section(article))
    for claim in claims:
        needle = _normalize_phrase(claim)
        if len(needle) < 12:
            continue
        # Require a substantial substring match (first 48 chars) to reduce false positives
        probe = needle[:48] if len(needle) > 48 else needle
        if probe in hay:
            issues.append(
                GateIssue(
                    "flagged_claim",
                    f'Research-audit FLAGGED claim appears in article: "{claim[:80]}"',
                )
            )
    return issues


def check_case_study_urls(article: str, audit: str, case_study_raw: str) -> list[GateIssue]:
    issues: list[GateIssue] = []
    meta = parse_audit_case_study(audit)
    fail_urls = set(parse_pipeline_fail_urls(audit, case_study_raw))
    article_urls = set(url_verify.extract_http_urls(article, limit=50))

    for url in article_urls & fail_urls:
        issues.append(
            GateIssue(
                "fail_url",
                f"Article links to a pipeline FAIL URL (unreachable/rejected): {url}",
            )
        )

    status = meta.get("status") or ""
    approved_url = (meta.get("url") or "").rstrip("/")
    url_check = meta.get("url_check") or ""

    if status.startswith("NO APPROVED"):
        # If audit forbids a case study, don't require one — but still block FAIL urls above.
        return issues

    if status == "APPROVED" and approved_url:
        if url_check == "FAIL":
            issues.append(
                GateIssue(
                    "case_study_url_fail",
                    f"Approved case study URL failed verification and must not be used: {approved_url}",
                )
            )
        elif url_check == "OK":
            # If the article mentions a case-study-like narrative with a different URL
            # from case_study_research that isn't the approved one — soft check:
            # only fail if approved URL is missing AND another case-study research URL is present.
            cs_urls = set(url_verify.extract_http_urls(case_study_raw, limit=20))
            other = (article_urls & cs_urls) - {approved_url, approved_url + "/"}
            # normalize trailing slash
            normalized_article = {u.rstrip("/") for u in article_urls}
            if approved_url.rstrip("/") not in normalized_article and other:
                issues.append(
                    GateIssue(
                        "case_study_wrong_url",
                        "Article cites a case-study research URL that is not the "
                        f"audit-approved OK URL ({approved_url}).",
                    )
                )
    return issues


def _norm_q(q: str) -> str:
    return re.sub(r"[^\w\s]", "", _normalize_phrase(q))


def check_faq(
    article: str,
    *,
    require_faq: bool,
    approved_faq: list[str],
    paa_bank: list[str],
) -> list[GateIssue]:
    if not require_faq:
        return []
    pairs = faq_schema.extract_faq_pairs(article)
    issues: list[GateIssue] = []
    allowed = approved_faq or paa_bank
    min_n = 2
    if allowed:
        min_n = min(5, max(2, len(allowed)))
    else:
        min_n = 5

    if len(pairs) < min_n:
        issues.append(
            GateIssue(
                "faq_count",
                f"FAQ has {len(pairs)} question(s); need at least {min_n}.",
            )
        )

    if allowed:
        allowed_norm = [_norm_q(q) for q in allowed]
        for q, _a in pairs:
            nq = _norm_q(q)
            if not any(
                nq == aq or nq in aq or aq in nq
                for aq in allowed_norm
                if aq
            ):
                issues.append(
                    GateIssue(
                        "faq_unapproved",
                        f'FAQ question not in approved/PAA bank: "{q[:90]}"',
                    )
                )

    for q, a in pairs:
        n = _answer_sentence_count(a)
        words = faq_schema.faq_answer_word_count(a)
        lines = len([ln for ln in (a or "").splitlines() if ln.strip()]) or n
        if (
            n < FAQ_ANSWER_MIN_SENTENCES
            or n > FAQ_ANSWER_MAX_SENTENCES
            or lines > FAQ_ANSWER_MAX_SENTENCES
            or words > faq_schema.FAQ_ANSWER_MAX_WORDS
        ):
            issues.append(
                GateIssue(
                    "faq_answer_length",
                    f'FAQ answer for "{q[:70]}" is {n} sentence(s) / {lines} line(s) / '
                    f"{words} words; need {FAQ_ANSWER_MIN_SENTENCES}-{FAQ_ANSWER_MAX_SENTENCES} "
                    f"sentences in one paragraph (max {faq_schema.FAQ_ANSWER_MAX_WORDS} words, "
                    "no bullets). "
                    "Hit the article word count in body sections, not FAQ.",
                )
            )
    return issues


_FAQ_ANSWER_FILLERS_BY_LANG: dict[str, tuple[str, ...]] = {
    "en": (
        "It depends on your situation, your constraints, and what you can prepare first.",
        "Start with one clear step that has a result you can check.",
        "Adjust based on that result before you widen the approach.",
    ),
    "fr": (
        "Cela dépend de votre situation, de vos contraintes et de ce que vous pouvez préparer d'abord.",
        "Commencez par une étape claire avec un résultat simple à vérifier.",
        "Ajustez ensuite selon ce résultat avant d'élargir.",
    ),
    "de": (
        "Das hängt von Ihrer Situation, Ihren Rahmenbedingungen und dem ab, was Sie zuerst vorbereiten können.",
        "Beginnen Sie mit einem klaren Schritt, dessen Ergebnis Sie prüfen können.",
        "Passen Sie den Ansatz danach an, bevor Sie ihn ausweiten.",
    ),
    "es": (
        "Depende de tu situación, tus límites y de lo que puedas preparar primero.",
        "Empieza con un paso claro que tenga un resultado fácil de comprobar.",
        "Ajusta según ese resultado antes de ampliar el enfoque.",
    ),
    "it": (
        "Dipende dalla tua situazione, dai vincoli e da ciò che puoi preparare per primo.",
        "Inizia con un passo chiaro che abbia un risultato verificabile.",
        "Poi regola l'approccio in base a quel risultato prima di allargarlo.",
    ),
}


def _faq_fillers_for_lang(lang: str) -> tuple[str, ...]:
    return _FAQ_ANSWER_FILLERS_BY_LANG.get(
        (lang or "en").lower(), _FAQ_ANSWER_FILLERS_BY_LANG["en"]
    )


def _detect_faq_language(
    article: str,
    *,
    lang_hint: str = "",
    questions: list[str] | None = None,
) -> str:
    hint = (lang_hint or "").strip().lower()
    if hint in _FAQ_ANSWER_FILLERS_BY_LANG and hint != "en":
        return hint
    sections = faq_schema.extract_faq_sections(article or "")
    if sections:
        heading = sections[0][0].lower()
        if "fréquent" in heading or "foire aux" in heading:
            return "fr"
        if "häufig" in heading:
            return "de"
        if "preguntas" in heading:
            return "es"
        if "domande" in heading:
            return "it"
    sample = " ".join(questions or [])
    if not sample and sections:
        sample = " ".join(q for _h, pairs in sections for q, _a in pairs)
    low = sample.lower()
    if re.search(
        r"\b(comment|pourquoi|quel(?:le)?s?|combien|quand|où|est-ce|d['’]|qu['’])\b"
        r"|[àâäéèêëïîôùûüç]",
        low,
    ):
        return "fr"
    if hint in _FAQ_ANSWER_FILLERS_BY_LANG:
        return hint
    return "en"


def _shape_faq_answer(answer: str, *, lang: str = "en") -> str:
    """Keep a normal 2–4 sentence paragraph so the FAQ length gate passes."""
    fillers = _faq_fillers_for_lang(lang)
    sentences = faq_schema.split_faq_sentences(faq_schema.trim_faq_answer(answer))
    # Drop stale English automation fillers when writing a non-English FAQ.
    if lang != "en":
        english = set(_FAQ_ANSWER_FILLERS_BY_LANG["en"])
        legacy_en = {
            "It depends on the task, the tools already in place, and how much should stay with a person.",
            "Start with one clear job that has a known input and a known output.",
            "Review the result before you widen the setup.",
            "Change the approach when the process or the volume changes.",
        }
        sentences = [s for s in sentences if s not in english and s not in legacy_en]
    for filler in fillers:
        if len(sentences) >= FAQ_ANSWER_MIN_SENTENCES:
            break
        if filler not in sentences:
            sentences.append(filler)
    text = " ".join(sentences[:FAQ_ANSWER_MAX_SENTENCES])
    return faq_schema.trim_faq_answer(text)


def align_faq_to_allowed(
    article: str,
    allowed: list[str],
    *,
    lang: str = "",
) -> str:
    """Replace invented FAQ questions with the approved or PAA bank wording."""
    questions = []
    seen: set[str] = set()
    for raw in allowed or []:
        q = paa_faq.clean_faq_question(raw)
        if not q:
            continue
        key = _norm_q(q)
        if not key or key in seen:
            continue
        seen.add(key)
        questions.append(q if q.endswith("?") else f"{q}?")
        if len(questions) >= 7:
            break
    if not questions or not (article or "").strip():
        return article

    faq_lang = _detect_faq_language(article, lang_hint=lang, questions=questions)
    pairs = faq_schema.extract_faq_pairs(article)
    sections = faq_schema.extract_faq_sections(article)
    heading = (
        sections[0][0]
        if sections
        else editorial_input.faq_heading_for_language(faq_lang)
    )
    fillers = _faq_fillers_for_lang(faq_lang)
    new_pairs: list[tuple[str, str]] = []
    for idx, q in enumerate(questions):
        nq = _norm_q(q)
        answer = ""
        for existing_q, existing_a in pairs:
            en = _norm_q(existing_q)
            if nq and en and (nq == en or nq in en or en in nq):
                answer = existing_a
                break
        # Index fallback when wording drifted but answers already exist.
        if not answer and idx < len(pairs):
            answer = pairs[idx][1]
        if answer and faq_lang != "en" and _looks_wrong_faq_lang(answer, faq_lang):
            # Don't keep English stub answers under French (etc.) questions.
            answer = ""
        if not answer:
            answer = fillers[0]
        new_pairs.append((q, _shape_faq_answer(answer, lang=faq_lang)))
    return faq_schema.insert_faq_block(article, new_pairs, heading=heading)


def _looks_wrong_faq_lang(answer: str, lang: str) -> bool:
    """True when a fallback answer is clearly not in the article FAQ language."""
    text = (answer or "").strip()
    if not text or lang == "en":
        return False
    low = text.lower()
    if lang == "fr":
        has_fr = bool(
            re.search(
                r"\b(le|la|les|des|une|pour|avec|dans|vous|votre|cela|commencez|"
                r"préparez|ajoutez|selon)\b|[àâäéèêëïîôùûüç]",
                low,
            )
        )
        has_en = bool(
            re.search(
                r"\b(the|and|with|your|start|depends|review|before|tools|task)\b",
                low,
            )
        )
        return has_en and not has_fr
    return False


def check_form_internal_links(
    article: str, links: list[dict[str, str]] | None
) -> list[GateIssue]:
    """Require article-form Internal Links (URLs/paths) to appear as markdown links."""
    missing = editorial_input.missing_form_internal_links(article, links)
    if not missing:
        return []
    required = [item for item in (links or []) if (item.get("href") or "").strip()]
    # Cap so a long paste does not become an impossible gate.
    need = min(len(required), 4)
    placed = len(required) - len(missing)
    if placed >= need:
        return []
    listed = "; ".join(
        f"{item.get('title') or 'page'} → {item.get('href')}" for item in missing[:4]
    )
    return [
        GateIssue(
            "form_internal_link",
            "Article is missing editor-provided internal links from the article form. "
            f"Weave these mid-sentence with 2–3 word anchors: {listed}",
        )
    ]


def evaluate_article_gates(
    article_md: str,
    *,
    primary_keyword: str = "",
    word_target: int | None = None,
    research_audit: str = "",
    case_study_research: str = "",
    paa_faq_research: str = "",
    require_faq: bool = True,
    form_internal_links: list[dict[str, str]] | None = None,
    stage: str = "draft",
) -> GateReport:
    article = _article_body(article_md, stage=stage)
    report = GateReport(primary_keyword=(primary_keyword or "").strip())

    if not article.strip():
        report.issues.append(GateIssue("empty", "Article body is empty."))
        return report

    lede_issue = check_lede(article)
    if lede_issue:
        report.issues.append(lede_issue)
    else:
        report.lede_words = len(_word_tokens(extract_lede_text(article)))

    # Block duplicate takeaways / Summary headings anywhere after the opening Key takeaways block.
    takeaway_issue = check_no_late_takeaways(article)
    if takeaway_issue:
        report.issues.append(takeaway_issue)

    wc_issue, words = check_word_count(article, word_target)
    report.body_words = words
    if wc_issue:
        report.issues.append(wc_issue)

    kw_issue = check_primary_keyword(article, report.primary_keyword)
    if kw_issue:
        report.issues.append(kw_issue)

    report.issues.extend(check_cited_numbers(article))

    flagged = parse_audit_flagged_claims(research_audit)
    report.issues.extend(check_flagged_claims(article, flagged))

    if research_audit or case_study_research:
        report.issues.extend(
            check_case_study_urls(article, research_audit, case_study_research)
        )

    approved_faq = parse_audit_approved_faq(research_audit)
    paa_bank = paa_faq.extract_recommended_faq_questions(paa_faq_research)
    faq_issues = check_faq(
        article,
        require_faq=require_faq,
        approved_faq=approved_faq,
        paa_bank=paa_bank,
    )
    report.issues.extend(faq_issues)
    report.faq_count = len(faq_schema.extract_faq_pairs(article))
    report.issues.extend(check_form_internal_links(article, form_internal_links))
    return report


def _repair_article_llm(
    article: str,
    report: GateReport,
    *,
    step_label: str,
) -> str:
    from .integrations import anthropic as claude

    system = (
        "You are a publishing editor. Fix ONLY the hard-gate failures listed. "
        "Do not rewrite the whole article. Preserve meaning, brand voice, and structure. "
        "Return the full corrected article markdown only — no preamble."
    )
    user = (
        f"{report.as_prompt_block()}\n\n"
        "Rules:\n"
        f"- Opening order: `# H1` → `## Key takeaways` ({LEDE_MIN_WORDS}–{LEDE_MAX_WORDS} words) "
        "→ hero `![alt](IMAGE: …)` → first content H2. "
        "Write actionable takeaways — not an article summary/recap. Do not use ## Summary.\n"
        f"- Primary keyword must appear verbatim once in the first {FIRST_N_BODY_WORDS} "
        "body words, in the first Key takeaways sentence. Headings and the H1 do not "
        "count. A synonym does not count. No further exact body repeats.\n"
        "- Every concrete price / % / fee needs an inline HTTPS citation in the same "
        "paragraph, or remove/generalize the number.\n"
        "- Remove any FLAGGED claims and FAIL URLs.\n"
        "- If [late_takeaways] failed: remove duplicate 'Key takeaways' / 'Summary' / "
        "'What you'll learn' headings from the body and keep a single ## Key takeaways at the top.\n"
        "- FAQ questions must use the approved/PAA bank wording exactly. "
        "Do not invent new FAQ questions.\n"
        f"- Each FAQ answer must be one normal paragraph of "
        f"{FAQ_ANSWER_MIN_SENTENCES}-{FAQ_ANSWER_MAX_SENTENCES} sentences "
        f"(max {faq_schema.FAQ_ANSWER_MAX_WORDS} words). "
        "Do not use bullets, numbered lists, or one sentence per line. "
        "Do not pad FAQ; keep article word count in the body.\n"
        "- If [form_internal_link] failed: weave each listed URL/path as "
        "`[2–3 word anchor](exact-href)` mid-sentence. Do not invent different URLs "
        "or dump a footer list.\n"
        "- Keep body word count inside the stated band if word_count failed.\n\n"
        "---ARTICLE---\n"
        f"{article.strip()}\n"
        "---END ARTICLE---"
    )
    return claude.chat_complete(
        system,
        user,
        step_label=step_label,
        max_tokens=8000,
        temperature=0.2,
    ).strip()


def _replace_stage_body(current: str, new_body: str, *, stage: str) -> str:
    """Put an edited article body back inside draft/final markers when present."""
    body = (new_body or "").strip()
    if not body:
        return current
    if stage == "final" and (
        faq_schema.FINAL_OUTPUT_START in current
        or faq_schema.FINAL_ARTICLE_START in current
    ):
        return faq_schema.replace_final_article_body(current, body)
    if stage == "draft" and "---DRAFT START---" in current.upper():
        return re.sub(
            r"(---DRAFT START---\s*).*?(\s*---DRAFT END---)",
            r"\1" + body + r"\2",
            current,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )
    return body


def enforce_article_gates(
    article_md: str,
    *,
    client_id: str,
    run_id: str,
    stage: str = "draft",
    allow_llm_repair: bool = True,
    raise_on_fail: bool = True,
) -> str:
    """Evaluate hard gates; optionally LLM-repair once; raise HardGateError if still failing."""
    from . import artifacts
    from . import config

    if not getattr(config, "HARD_GATES_ENABLED", True):
        return article_md

    manifest = artifacts.read_run_manifest(client_id, run_id) or {}
    manual = manifest.get("manual_inputs")
    if not isinstance(manual, dict):
        manual = {}
    word_target = editorial_input.word_count_target_from_manifest(manifest)
    require_faq = editorial_input.should_include_faq(manual)

    def _load(step: str) -> str:
        try:
            return artifacts.load_artifact(client_id, run_id, step)
        except FileNotFoundError:
            return ""

    brief = _load("assignment_brief")
    topic_card = _load("topic_card")
    # The article-form seed is the main keyword. Topic-card rewrites must not replace it.
    primary = (
        (manual.get("Seed Keyword") or manual.get("seed_keyword") or "").strip()
        or parse_primary_keyword(topic_card, brief)
        or (manual.get("PRIMARY KEYWORD") or "").strip()
    )

    research_audit = _load("research_audit")
    case_study = _load("case_study_research")
    paa = _load("paa_faq_research")
    form_internal_links = editorial_input.parse_form_internal_links(manual)
    allowed_faq = parse_audit_approved_faq(research_audit) or paa_faq.extract_recommended_faq_questions(
        paa
    )
    faq_lang = editorial_input.article_language_from_manual(manual)
    if faq_lang == "en":
        paa_lang = paa_faq.extract_faq_language(paa)
        if paa_lang:
            faq_lang = paa_lang

    def _correct(body: str) -> str:
        text = body
        if require_faq and allowed_faq:
            text = align_faq_to_allowed(text, allowed_faq, lang=faq_lang)
        return ensure_primary_keyword_in_first_100(text, primary)

    current = _replace_stage_body(
        article_md,
        _correct(_article_body(article_md, stage=stage)),
        stage=stage,
    )
    report = evaluate_article_gates(
        current,
        primary_keyword=primary,
        word_target=word_target,
        research_audit=research_audit,
        case_study_research=case_study,
        paa_faq_research=paa,
        require_faq=require_faq,
        form_internal_links=form_internal_links,
        stage=stage,
    )

    if report.ok:
        logger.info(
            "hard gates passed (%s) body_words=%s lede_words=%s faq=%s",
            stage,
            report.body_words,
            report.lede_words,
            report.faq_count,
        )
        return current

    logger.warning("hard gates failed (%s): %s", stage, report.failure_message())

    if allow_llm_repair and report.blocking_issues():
        try:
            repaired = _repair_article_llm(
                _article_body(current, stage=stage),
                report,
                step_label=f"Hard gate repair ({stage})",
            )
            if repaired:
                repaired = _correct(repaired)
                current = _replace_stage_body(current, repaired, stage=stage)
                report = evaluate_article_gates(
                    current,
                    primary_keyword=primary,
                    word_target=word_target,
                    research_audit=research_audit,
                    case_study_research=case_study,
                    paa_faq_research=paa,
                    require_faq=require_faq,
                    form_internal_links=form_internal_links,
                    stage=stage,
                )
        except Exception:
            logger.exception("hard gate LLM repair failed (%s)", stage)

    if report.ok:
        logger.info("hard gates passed after repair (%s)", stage)
        return current

    if raise_on_fail and getattr(config, "HARD_GATES_STRICT", True):
        raise HardGateError(report)

    # Non-strict: append a visible report and return
    body = _article_body(current, stage=stage)
    annotated = (
        body.rstrip()
        + "\n\n## Hard gate report (non-strict)\n"
        + report.failure_message()
        + "\n"
    )
    if stage == "final" and faq_schema.FINAL_OUTPUT_START in current:
        return faq_schema.replace_final_article_body(current, annotated)
    return annotated
