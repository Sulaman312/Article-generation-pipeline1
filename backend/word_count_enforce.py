"""Structure-preserving article length control (section budgets + section trim)."""

from __future__ import annotations

import logging
import re
from typing import Any

from . import config
from . import editorial_input
from .integrations import anthropic as claude

logger = logging.getLogger(__name__)


def _section_repair_cap() -> int:
    try:
        return int(getattr(config, "SECTION_REPAIR_MAX_TOKENS", 2200) or 2200)
    except (TypeError, ValueError):
        return 2200


def _max_tokens_for_target(target: int | None) -> int:
    cap = _section_repair_cap()
    if not target:
        return cap
    return min(cap, max(512, int(target * 2.2) + 400))


def _claude_trim_call(
    system_msg: Any,
    trim_user: str,
    *,
    step_label: str,
    max_tokens: int,
) -> str:
    from .prompt_cache import CachedPrompt

    if isinstance(system_msg, CachedPrompt):
        return claude.chat_complete(
            system_msg.with_unique(trim_user, step_label=step_label),
            max_tokens=max_tokens,
            temperature=0.3,
        ).strip()
    return claude.chat_complete(
        system_msg,
        trim_user,
        step_label=step_label,
        max_tokens=max_tokens,
        temperature=0.3,
    ).strip()


def trim_section_body(
    *,
    heading: str,
    body: str,
    cap_words: int,
    system_msg: Any,
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
    trimmed = _claude_trim_call(
        system_msg,
        trim_user,
        step_label=step_label,
        max_tokens=_max_tokens_for_target(cap_words),
    )
    if trimmed.startswith("## "):
        parts = trimmed.split("\n", 1)
        return parts[1].strip() if len(parts) > 1 else ""
    return trimmed


def trim_article_by_sections(
    article: str,
    target: int,
    *,
    system_msg: Any = None,
    outline: str = "",
    step_label: str = "section trim",
    max_passes: int = 1,
) -> str:
    """Shrink only the longest overweight H2; never drop FAQ or rewrite the article."""
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
        i, _overage = over[0]
        sec = sections[i]
        if not sec.get("heading"):
            break
        new_body = trim_section_body(
            heading=sec["heading"],
            body=sec.get("body") or "",
            cap_words=caps[i],
            system_msg=sys,
            step_label=f"{step_label} longest section",
        )
        if not new_body.strip() or new_body.strip() == (sec.get("body") or "").strip():
            break
        sections[i]["body"] = new_body
        sections[i]["words"] = editorial_input.count_article_words(new_body)
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


def expand_section_body(
    *,
    heading: str,
    body: str,
    add_words: int,
    system_msg: Any,
    step_label: str,
) -> str:
    """Add substance to one H2 body only."""
    current = editorial_input.count_article_words(body)
    target = current + max(40, int(add_words))
    expand_user = (
        f"Expand ONLY this article section. Keep the H2 heading line unchanged.\n"
        f"- Current section words: {current:,}\n"
        f"- Add about {add_words:,} words of useful detail (target ~{target:,}).\n"
        "Rules:\n"
        "- Keep the same H2 heading and any H3s inside it.\n"
        "- Add examples, steps, or concrete detail. No filler or repetition.\n"
        "- Preserve markdown links in this section.\n"
        "- Output ONLY the section starting with the H2 line, then its body.\n\n"
        f"---SECTION---\n{heading.strip()}\n{body.strip()}\n"
    )
    expanded = _claude_trim_call(
        system_msg,
        expand_user,
        step_label=step_label,
        max_tokens=_max_tokens_for_target(target)
    )
    if expanded.startswith("## "):
        parts = expanded.split("\n", 1)
        return parts[1].strip() if len(parts) > 1 else ""
    return expanded


def expand_shortest_section(
    article: str,
    target: int,
    *,
    system_msg: Any = None,
    outline: str = "",
    step_label: str = "section expand",
) -> str:
    """Grow only the shortest body H2. Never regenerates the full article."""
    low, _high = editorial_input.word_count_bounds(target)
    text = (article or "").strip()
    current = editorial_input.count_article_words(text)
    if current >= low:
        return text
    shortage = low - current
    sections = editorial_input.split_article_h2_sections(text)
    candidates = [
        (i, sec)
        for i, sec in enumerate(sections)
        if not sec.get("is_faq") and (sec.get("heading") or "").startswith("## ")
        and editorial_input.count_article_words(sec.get("body") or "") >= 20
    ]
    if not candidates:
        return text
    # Skip opening takeaways; prefer a content H2.
    content = [
        (i, sec)
        for i, sec in candidates
        if not re.search(
            r"key\s+takeaways?|[àa]\s+retenir",
            sec.get("heading") or "",
            re.I,
        )
    ]
    pool = content or candidates
    i, sec = min(
        pool,
        key=lambda item: editorial_input.count_article_words(item[1].get("body") or ""),
    )
    sys = system_msg or (
        "You are a publishing editor. Expand one section with useful detail "
        "without changing the rest of the article."
    )
    new_body = expand_section_body(
        heading=sec["heading"],
        body=sec.get("body") or "",
        add_words=shortage,
        system_msg=sys,
        step_label=step_label,
    )
    if not new_body.strip() or new_body.strip() == (sec.get("body") or "").strip():
        return text
    sections[i]["body"] = new_body
    sections[i]["words"] = editorial_input.count_article_words(new_body)
    result = editorial_input.reassemble_h2_sections(sections)
    logger.info(
        "section expand: %s words -> %s (target %s)",
        current,
        editorial_input.count_article_words(result),
        target,
    )
    return result
