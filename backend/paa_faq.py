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


def extract_recommended_faq_questions(paa_text: str) -> list[str]:
    """Return Recommended FAQ bank question texts (without Qn: prefix)."""
    text = (paa_text or "").strip()
    if not text:
        return []
    start = _BANK_START.search(text)
    if not start:
        return _Q_HEADING.findall(text)
    body = text[start.end() :]
    end = _BANK_END.search(body)
    if end:
        body = body[: end.start()]
    return [q.strip() for q in _Q_HEADING.findall(body) if q.strip()]


def format_faq_bank_for_prompt(paa_text: str, *, max_questions: int = 8) -> str:
    """Compact block of recommended questions for FAQ inject / repair prompts."""
    qs = extract_recommended_faq_questions(paa_text)[:max_questions]
    if not qs:
        return ""
    lines = ["Use these FAQ questions (preferred wording):"]
    for i, q in enumerate(qs, start=1):
        lines.append(f"{i}. {q}")
    low = "LOW SIGNAL TOPIC" in (paa_text or "")
    demand = "KEYWORD DATA SHOWS LOW/NO DEMAND" in (paa_text or "")
    if low or demand:
        lines.append(
            "Respect LOW SIGNAL / low-demand flags — do not invent extra questions to pad."
        )
    return "\n".join(lines)
