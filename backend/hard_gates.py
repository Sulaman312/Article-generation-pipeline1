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
FAQ_ANSWER_MIN_SENTENCES = 3
FAQ_ANSWER_MAX_SENTENCES = 4

_H1 = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_H2 = re.compile(r"^##\s+.+$", re.MULTILINE)
_SUMMARY_H2 = re.compile(
    r"^##\s+(summary|résumé|resume|zusammenfassung)\s*$",
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
    """Summary prose between ``## Summary`` and the hero image (or next H2)."""
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
    if not _SUMMARY_H2.match(first.group(0).strip()):
        # Legacy plain-lede articles: prose between H1 and first H2.
        return after_h1[: first.start()].strip()
    zone_end = h2s[1].start() if len(h2s) > 1 else len(after_h1)
    zone = after_h1[first.end() : zone_end]
    img = _IMAGE_MD.search(zone)
    prose = zone[: img.start()] if img else zone
    return prose.strip()


def check_lede(article: str) -> GateIssue | None:
    """Require H1 → ## Summary → summary prose → hero image → next H2."""
    text = (article or "").replace("\r\n", "\n").strip()
    if not text:
        return GateIssue(
            "lede_missing",
            f"Opening missing — need ## Summary ({LEDE_MIN_WORDS}–{LEDE_MAX_WORDS} words) "
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
            'First block after H1 must be "## Summary", then prose, then a hero image.',
        )
    first_h2 = h2s[0].group(0).strip()
    if not _SUMMARY_H2.match(first_h2):
        return GateIssue(
            "summary_heading",
            'First H2 after H1 must be "## Summary" (order: H1 → Summary → Image → content).',
        )
    zone_end = h2s[1].start() if len(h2s) > 1 else len(after_h1)
    zone = after_h1[h2s[0].end() : zone_end]
    img = _IMAGE_MD.search(zone)
    if not img:
        return GateIssue(
            "summary_image",
            "Place a hero image immediately after the Summary prose, before the next H2 "
            "(`![descriptive alt text](IMAGE: slug)`).",
        )
    prose = zone[: img.start()].strip()
    trailing = zone[img.end() :].strip()
    if trailing and _word_tokens(trailing):
        return GateIssue(
            "summary_order",
            "Order must be H1 → ## Summary → summary prose → image → next H2 "
            "(no extra body prose between the image and the next H2).",
        )
    if not prose:
        return GateIssue(
            "lede_missing",
            f"## Summary prose missing — need {LEDE_MIN_WORDS}–{LEDE_MAX_WORDS} words "
            "before the hero image.",
        )
    n = len(_word_tokens(prose))
    if n < LEDE_MIN_WORDS or n > LEDE_MAX_WORDS:
        return GateIssue(
            "lede_length",
            f"## Summary is {n} words; required {LEDE_MIN_WORDS}-{LEDE_MAX_WORDS}.",
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


def _count_phrase_in_words(words: list[str], phrase: str) -> int:
    """Count non-overlapping occurrences of phrase token sequence in word list."""
    needle = _normalize_phrase(phrase).split()
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


def check_primary_keyword(article: str, primary: str) -> GateIssue | None:
    kw = (primary or "").strip()
    if not kw or kw.lower() in ("your target keyword", "not provided"):
        return None  # no keyword to enforce
    body = faq_schema.strip_faq_section(article)
    # Drop H1 from body keyword scan for "first 100 body words"
    body_no_h1 = _H1.sub("", body, count=1)
    # Only count keyword occurrences in body prose, not in subtitle headings.
    # This lets headings carry the key phrase for SEO without breaking stuffing gates.
    body_prose_only = re.sub(r"^#{1,6}\s+.*$", "", body_no_h1, flags=re.MULTILINE)
    tokens = _word_tokens(body_prose_only)
    first = tokens[:FIRST_N_BODY_WORDS]
    rest = tokens[FIRST_N_BODY_WORDS:]
    in_first = _count_phrase_in_words(first, kw)
    in_rest = _count_phrase_in_words(rest, kw)
    if in_first != 1:
        return GateIssue(
            "keyword_first_100",
            f'Primary keyword "{kw}" must appear exactly once in the first '
            f"{FIRST_N_BODY_WORDS} body words (found {in_first}).",
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
    return [m.group(1).strip() for m in _APPROVED_FAQ_NUM.finditer(section) if m.group(1).strip()]


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
        if n < FAQ_ANSWER_MIN_SENTENCES or n > FAQ_ANSWER_MAX_SENTENCES:
            issues.append(
                GateIssue(
                    "faq_answer_length",
                    f'FAQ answer for "{q[:70]}" has {n} sentence(s); '
                    f"need {FAQ_ANSWER_MIN_SENTENCES}–{FAQ_ANSWER_MAX_SENTENCES} lines.",
                )
            )
    return issues


def evaluate_article_gates(
    article_md: str,
    *,
    primary_keyword: str = "",
    word_target: int | None = None,
    research_audit: str = "",
    case_study_research: str = "",
    paa_faq_research: str = "",
    require_faq: bool = True,
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
        f"- Opening order: `# H1` → `## Summary` ({LEDE_MIN_WORDS}–{LEDE_MAX_WORDS} words) "
        "→ hero `![alt](IMAGE: …)` → first content H2.\n"
        f"- Primary keyword exact match once in first {FIRST_N_BODY_WORDS} body words; "
        "no further exact body repeats.\n"
        "- Every concrete price / % / fee needs an inline HTTPS citation in the same "
        "paragraph, or remove/generalize the number.\n"
        "- Remove any FLAGGED claims and FAIL URLs.\n"
        "- FAQ questions must match the approved/PAA bank when those gates failed.\n"
        f"- Each FAQ answer must be {FAQ_ANSWER_MIN_SENTENCES}–{FAQ_ANSWER_MAX_SENTENCES} "
        "sentences/lines.\n"
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
    primary = parse_primary_keyword(brief, topic_card)
    if not primary:
        primary = (
            manual.get("Seed Keyword")
            or manual.get("seed_keyword")
            or manual.get("PRIMARY KEYWORD")
            or ""
        ).strip()

    research_audit = _load("research_audit")
    case_study = _load("case_study_research")
    paa = _load("paa_faq_research")

    current = article_md
    report = evaluate_article_gates(
        current,
        primary_keyword=primary,
        word_target=word_target,
        research_audit=research_audit,
        case_study_research=case_study,
        paa_faq_research=paa,
        require_faq=require_faq,
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
                # Re-wrap if final/draft markers existed
                if stage == "final" and (
                    faq_schema.FINAL_OUTPUT_START in current
                    or faq_schema.FINAL_ARTICLE_START in current
                ):
                    current = faq_schema.replace_final_article_body(current, repaired)
                elif stage == "draft" and "---DRAFT START---" in current.upper():
                    current = re.sub(
                        r"(---DRAFT START---\s*).*?(\s*---DRAFT END---)",
                        r"\1" + repaired.strip() + r"\2",
                        current,
                        count=1,
                        flags=re.IGNORECASE | re.DOTALL,
                    )
                else:
                    current = repaired
                report = evaluate_article_gates(
                    current,
                    primary_keyword=primary,
                    word_target=word_target,
                    research_audit=research_audit,
                    case_study_research=case_study,
                    paa_faq_research=paa,
                    require_faq=require_faq,
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
