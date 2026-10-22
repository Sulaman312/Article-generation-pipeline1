"""Parse PAA / FAQ research artifacts for downstream FAQ use."""

from __future__ import annotations

import re

_Q_HEADING = re.compile(r"^###\s+Q\d+\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_BANK_START = re.compile(
    r"##\s+Recommended FAQ bank.*?\n", re.IGNORECASE
)
_BANK_END = re.compile(
    r"\n##\s+(?:Questions to skip|Language|Citable sources)\b",
    re.IGNORECASE,
)
_FAQ_LANG = re.compile(
    r"FAQ\s+LANGUAGE\s*:\s*([a-z]{2,5})",
    re.IGNORECASE,
)
# Research metadata that must never appear in published FAQ question text.
_SOURCE_META_PAREN = re.compile(
    r"\s*\(\s*(?:source\s+signal|citation|url\s+unverified|same\s+caveat|"
    r"use\s+for\s+answer\s+framing\s+only|"
    r"competitor\s+h2|related\s+search|related_questions\s+api|"
    r"keyword-tool|inferred|paa|forum)[^)]*\)\s*",
    re.IGNORECASE,
)
_SOURCE_META_TRAIL = re.compile(
    r"\s*[—–-]\s*(?:source\s+signal|citation)\s*:?\s*.+$",
    re.IGNORECASE,
)
_SOURCE_META_INLINE = re.compile(
    r"\s*(?:source\s+signal|citation)\s*:\s*[^?]*",
    re.IGNORECASE,
)


def clean_faq_question(question: str) -> str:
    """Strip research-only source/citation notes from FAQ question wording."""
    q = re.sub(r"\s+", " ", (question or "").strip())
    if not q:
        return ""
    for _ in range(4):
        nxt = _SOURCE_META_PAREN.sub(" ", q)
        nxt = _SOURCE_META_TRAIL.sub("", nxt)
        nxt = _SOURCE_META_INLINE.sub(" ", nxt)
        nxt = re.sub(r"\s+", " ", nxt).strip(" ;,.-")
        if nxt == q:
            break
        q = nxt
    # Keep publishable wording through the first question mark only.
    m = re.search(r"^(.*?\?)", q)
    if m:
        q = m.group(1).strip()
    q = re.sub(r"\s+\?", " ?", q)
    q = re.sub(r"\?{2,}", "?", q)
    return q.strip()


def extract_faq_language(paa_text: str) -> str:
    """Return FAQ LANGUAGE code from the PAA artifact when present."""
    m = _FAQ_LANG.search(paa_text or "")
    if not m:
        return ""
    return m.group(1).strip().lower()


def extract_recommended_faq_questions(paa_text: str) -> list[str]:
    """Return Recommended FAQ bank question texts (without Qn: prefix)."""
    text = (paa_text or "").strip()
    if not text:
        return []
    start = _BANK_START.search(text)
    if not start:
        raw = _Q_HEADING.findall(text)
    else:
        body = text[start.end() :]
        end = _BANK_END.search(body)
        if end:
            body = body[: end.start()]
        raw = _Q_HEADING.findall(body)
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        q = clean_faq_question(item)
        if not q:
            continue
        key = re.sub(r"\W+", "", q.lower())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(q)
    return out


def format_faq_bank_for_prompt(paa_text: str, *, max_questions: int = 8) -> str:
    """Compact block of recommended questions for FAQ inject / repair prompts."""
    qs = extract_recommended_faq_questions(paa_text)[:max_questions]
    if not qs:
        return ""
    lines = [
        "Use these FAQ questions (preferred wording — clean question text only, "
        "never include SOURCE SIGNAL / CITATION notes in the published H3):"
    ]
    for i, q in enumerate(qs, start=1):
        lines.append(f"{i}. {q}")
    low = "LOW SIGNAL TOPIC" in (paa_text or "")
    demand = "KEYWORD DATA SHOWS LOW/NO DEMAND" in (paa_text or "")
    if low or demand:
        lines.append(
            "Respect LOW SIGNAL / low-demand flags — do not invent extra questions to pad."
        )
    return "\n".join(lines)
