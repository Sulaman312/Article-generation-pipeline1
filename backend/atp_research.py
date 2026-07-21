"""Parse AnswerThePublic-style topic research artifacts for downstream prompts."""

from __future__ import annotations

import re

_HIGH_INTENT_START = re.compile(
    r"##\s+High-intent shortlist.*?\n", re.IGNORECASE
)
_LONGTAIL_START = re.compile(
    r"##\s+Long-tail keyword bank.*?\n", re.IGNORECASE
)
_SUPPORTING_START = re.compile(
    r"##\s+Supporting blog cluster.*?\n", re.IGNORECASE
)
_MAIN_KW_START = re.compile(
    r"##\s+Keywords to weave into the main article.*?\n", re.IGNORECASE
)
_NEXT_H2 = re.compile(r"\n##\s+")
_S_HEADING = re.compile(
    r"^###\s+S\d+\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE
)
_RANKED_LINE = re.compile(
    r"^\s*\d+\.\s+PHRASE\s*:\s*(.+?)(?:\s*\|\s*INTENT:|\s*$)",
    re.IGNORECASE | re.MULTILINE,
)
_BULLET_PHRASE = re.compile(
    r"^\s*[-*]\s+(.+?)(?:\s*\|\s*USE IN:|\s*\|\s*INTENT:|\s*$)",
    re.IGNORECASE | re.MULTILINE,
)
_NUMBERED_ITEM = re.compile(r"^\s*\d+\.\s+(.+?)\s*$", re.MULTILINE)


def _section_after(text: str, start_re: re.Pattern[str]) -> str:
    m = start_re.search(text or "")
    if not m:
        return ""
    body = text[m.end() :]
    end = _NEXT_H2.search(body)
    if end:
        body = body[: end.start()]
    return body.strip()


def extract_high_intent_phrases(atp_text: str, *, limit: int = 12) -> list[str]:
    section = _section_after(atp_text, _HIGH_INTENT_START)
    if not section:
        return []
    out: list[str] = []
    for m in _RANKED_LINE.finditer(section):
        phrase = m.group(1).strip().rstrip("|").strip()
        if phrase:
            out.append(phrase)
        if len(out) >= limit:
            break
    return out


def extract_long_tail_keywords(atp_text: str, *, limit: int = 15) -> list[str]:
    section = _section_after(atp_text, _LONGTAIL_START)
    if not section:
        return []
    out: list[str] = []
    for m in _BULLET_PHRASE.finditer(section):
        phrase = m.group(1).strip().rstrip("|").strip()
        if phrase:
            out.append(phrase)
        if len(out) >= limit:
            break
    return out


def extract_supporting_titles(atp_text: str, *, limit: int = 5) -> list[str]:
    section = _section_after(atp_text, _SUPPORTING_START)
    if not section:
        return []
    titles = [t.strip() for t in _S_HEADING.findall(section) if t.strip()]
    return titles[:limit]


def extract_main_article_keywords(atp_text: str, *, limit: int = 10) -> list[str]:
    section = _section_after(atp_text, _MAIN_KW_START)
    if not section:
        return extract_long_tail_keywords(atp_text, limit=limit)
    out: list[str] = []
    for m in _NUMBERED_ITEM.finditer(section):
        phrase = m.group(1).strip()
        if phrase:
            out.append(phrase)
        if len(out) >= limit:
            break
    if out:
        return out
    return extract_long_tail_keywords(atp_text, limit=limit)


def format_atp_bank_for_prompt(atp_text: str) -> str:
    """Compact block for brief/outline/draft injection when the full artifact is large."""
    text = (atp_text or "").strip()
    if not text:
        return ""
    lines: list[str] = ["AnswerThePublic-style research (use for keywords + cluster):"]
    high = extract_high_intent_phrases(text)
    if high:
        lines.append("High-intent phrases:")
        for i, p in enumerate(high[:8], start=1):
            lines.append(f"  {i}. {p}")
    main_kw = extract_main_article_keywords(text)
    if main_kw:
        lines.append("Main-article long-tails (use naturally, at most once each):")
        for i, p in enumerate(main_kw[:8], start=1):
            lines.append(f"  {i}. {p}")
    titles = extract_supporting_titles(text)
    if titles:
        lines.append("Supporting posts to interlink (INTERNAL: Supporting: <title>):")
        for t in titles:
            lines.append(f"  - {t}")
    if "LOW SIGNAL TOPIC" in text:
        lines.append(
            "Respect LOW SIGNAL — do not invent extra supporting posts or keyword padding."
        )
    return "\n".join(lines)
