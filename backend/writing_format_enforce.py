"""Enforce writing-format guidelines: lint → deterministic fix → sentence-only LLM."""

from __future__ import annotations

import json
import logging
import re

from . import config
from . import prompts
from . import writing_format_lint as lint_mod
from .integrations import anthropic as claude

logger = logging.getLogger(__name__)

_MAX_REPAIR_ROUNDS = 1

_SENTENCE_REPAIR_SYSTEM = (
    "You are a copy editor. Fix ONLY the listed sentences. "
    "Return a JSON array of objects {\"old\": \"...\", \"new\": \"...\"} and nothing else. "
    "Do not rewrite the rest of the article. Keep facts, URLs, and markdown links.\n\n"
    "--- WRITING FORMAT GUIDELINES ---\n"
    f"{prompts.WRITING_FORMAT_GUIDELINES.strip()}\n"
    "--- END GUIDELINES ---\n"
)


def enforce_outline(
    outline: str,
    *,
    allow_llm_repair: bool = True,
    cta_href: str | None = None,
    lang: str | None = None,
) -> str:
    """Lint and repair outline artifacts."""
    return _enforce(
        outline,
        stage="outline",
        allow_llm_repair=allow_llm_repair,
        cta_href=cta_href,
        lang=lang,
    )


def enforce_brief(
    brief: str,
    *,
    allow_llm_repair: bool = True,
    cta_href: str | None = None,
    lang: str | None = None,
) -> str:
    """Lint and repair assignment brief artifacts."""
    return _enforce(
        brief,
        stage="brief",
        allow_llm_repair=allow_llm_repair,
        cta_href=cta_href,
        lang=lang,
    )


def enforce_article(
    article: str,
    *,
    stage: lint_mod.Stage = "draft",
    allow_llm_repair: bool = True,
    cta_href: str | None = None,
    lang: str | None = None,
) -> str:
    """Lint and repair draft or final article markdown."""
    return _enforce(
        article,
        stage=stage,
        allow_llm_repair=allow_llm_repair,
        cta_href=cta_href,
        lang=lang,
    )


def _enforce(
    text: str,
    *,
    stage: lint_mod.Stage,
    allow_llm_repair: bool,
    cta_href: str | None = None,
    lang: str | None = None,
) -> str:
    if not (text or "").strip():
        return text

    from . import html_leak

    if html_leak.has_leaked_html(text):
        text = html_leak.strip_leaked_html(text, cta_href=cta_href)
        logger.warning("writing_format: removed leaked HTML/CSS template (%s)", stage)

    current, fix_log = lint_mod.apply_deterministic_fixes(
        text, cta_href=cta_href, lang=lang
    )
    for entry in fix_log:
        logger.info("writing_format deterministic: %s", entry)

    report = lint_mod.lint(current, stage=stage, cta_href=cta_href, lang=lang)
    if report.ok:
        return current

    logger.info(
        "writing_format lint (%s): %s violation(s) after mechanical fixes",
        stage,
        len(report.violations),
    )

    if not allow_llm_repair or stage in ("outline", "brief"):
        if not report.ok:
            logger.warning(
                "writing_format violations (no full rewrite): %s", report.summary()
            )
        return current

    for round_i in range(_MAX_REPAIR_ROUNDS):
        report = lint_mod.lint(current, stage=stage, cta_href=cta_href, lang=lang)
        if report.ok:
            break
        excerpts = [
            (v.excerpt or v.message)
            for v in report.violations
            if v.code in {"SENTENCE_TOO_LONG", "PARAGRAPH_TOO_LONG", "REPEATED_SENTENCE_START"}
            and (v.excerpt or "").strip()
        ]
        if not excerpts:
            break
        try:
            current = _repair_sentences_llm(
                current,
                excerpts,
                stage=stage,
                round_i=round_i + 1,
                lang=lang,
            )
        except Exception:
            logger.exception("writing_format sentence LLM repair failed (stage=%s)", stage)
            break
        current, _ = lint_mod.apply_deterministic_fixes(
            current, cta_href=cta_href, lang=lang
        )

    final = lint_mod.lint(current, stage=stage, cta_href=cta_href, lang=lang)
    if not final.ok:
        logger.warning(
            "writing_format still has %s violation(s) after local repair: %s",
            len(final.violations),
            final.summary(max_items=8),
        )
    return current


def _repair_sentences_llm(
    markdown: str,
    excerpts: list[str],
    *,
    stage: lint_mod.Stage,
    round_i: int,
    lang: str | None = None,
) -> str:
    """Rewrite only the listed sentences; splice them back into the original."""
    unique = []
    seen: set[str] = set()
    for ex in excerpts:
        key = (ex or "").strip()
        if len(key) < 12 or key in seen:
            continue
        seen.add(key)
        unique.append(key[:240])
        if len(unique) >= 8:
            break
    if not unique:
        return markdown
    article_lang = lint_mod.detect_article_lang(markdown, hint=lang)
    user = (
        f"Stage: {stage}\nRepair round: {round_i}\nLanguage: {article_lang}\n"
        "Rewrite each excerpt so it no longer violates house style "
        "(max 30 words/sentence, vary openings, keep meaning).\n\n"
        "Excerpts:\n"
        + json.dumps(unique, ensure_ascii=False, indent=2)
    )
    raw = claude.chat_complete(
        _SENTENCE_REPAIR_SYSTEM,
        user,
        step_label=f"Writing format sentence repair ({stage})",
        max_tokens=int(getattr(config, "REPAIR_MAX_TOKENS", 1500) or 1500),
        temperature=0.2,
    ).strip()
    payload = _parse_json_array(raw)
    current = markdown
    for item in payload:
        if not isinstance(item, dict):
            continue
        old = str(item.get("old") or "").strip()
        new = str(item.get("new") or "").strip()
        if old and new and old in current:
            current = current.replace(old, new, 1)
    return current


def _parse_json_array(raw: str) -> list:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []
