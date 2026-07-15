"""Structure-preserving article length control (section budgets + section trim)."""

from __future__ import annotations

import logging

from . import editorial_input
from .integrations import anthropic as claude

logger = logging.getLogger(__name__)


def _max_tokens_for_target(target: int | None) -> int:
    if not target:
        return 4096
    return min(8192, max(2048, int(target * 2.2) + 800))


def trim_section_body(
    *,
    heading: str,
    body: str,
    cap_words: int,
    system_msg: str,
    step_label: str,
) -> str:
    """Tighten one H2 body to a word cap without dropping the section."""
    current = editorial_input.count_article_words(body)
    if current <= cap_words:
        return body
    trim_user = (
        f"Shorten ONLY this article section. Keep the H2 heading line unchanged.\n"
        f"- Current section words: {current:,}\n"
        f"- Target for THIS section: about {cap_words:,} words (hard max {cap_words:,})\n"
        f"Rules:\n"
        f"- Keep the same H2 heading and any H3s inside it.\n"
        f"- Remove redundancy and filler; keep the section complete and useful.\n"
        f"- Preserve markdown links in this section.\n"
        f"- Output ONLY the section starting with the H2 line, then its body.\n\n"
        f"---SECTION---\n{heading.strip()}\n{body.strip()}\n"
    )
    trimmed = claude.chat_complete(
        system_msg,
        trim_user,
        step_label=step_label,
        max_tokens=min(4096, _max_tokens_for_target(cap_words * 2)),
        temperature=0.3,
    ).strip()
    if trimmed.startswith("## "):
        parts = trimmed.split("\n", 1)
        return parts[1].strip() if len(parts) > 1 else ""
    return trimmed


def trim_article_by_sections(
    article: str,
    target: int,
    *,
    system_msg: str | None = None,
    outline: str = "",
    step_label: str = "section trim",
    max_passes: int = 3,
) -> str:
    """Shrink overweight H2s only; never drop FAQ or H2 headings."""
    _low, high = editorial_input.word_count_bounds(target)
    text = (article or "").strip()
    current = editorial_input.count_article_words(text)
    if current <= high:
        return text

    sys = system_msg or (
        "You are a publishing editor. Tighten prose section-by-section "
        "without removing headings or making the article incomplete."
    )

    for pass_i in range(max_passes):
        sections = editorial_input.split_article_h2_sections(text)
        if not sections:
            break
        caps = editorial_input.allocate_section_word_caps(
            sections, target, outline=outline
        )
        over = [
            (i, sections[i]["words"] - caps[i])
            for i in range(len(sections))
            if not sections[i].get("is_faq")
            and sections[i]["words"] > caps[i] + 25
        ]
        over.sort(key=lambda x: x[1], reverse=True)
        if not over:
            break
        changed = False
        for i, _overage in over[:3]:
            sec = sections[i]
            if not sec.get("heading"):
                continue
            new_body = trim_section_body(
                heading=sec["heading"],
                body=sec.get("body") or "",
                cap_words=caps[i],
                system_msg=sys,
                step_label=f"{step_label} pass {pass_i + 1}",
            )
            if new_body.strip() and new_body.strip() != (sec.get("body") or "").strip():
                sections[i]["body"] = new_body
                sections[i]["words"] = editorial_input.count_article_words(new_body)
                changed = True
        if not changed:
            break
        text = editorial_input.reassemble_h2_sections(sections)
        current = editorial_input.count_article_words(text)
        logger.info(
            "section trim pass %s: %s words (target %s, max %s)",
            pass_i + 1,
            current,
            target,
            high,
        )
        if current <= high:
            break

    if current > high:
        logger.warning(
            "article still over after section trim: %s words (max %s, target %s)",
            current,
            high,
            target,
        )
    return text
