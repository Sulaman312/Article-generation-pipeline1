"""Enforce writing-format guidelines: lint → deterministic fix → targeted LLM repair."""

from __future__ import annotations

import logging

from . import prompts
from . import writing_format_lint as lint_mod
from .integrations import anthropic as claude

logger = logging.getLogger(__name__)

_MAX_REPAIR_ROUNDS = 2

_REPAIR_SYSTEM = (
    "You are a copy editor enforcing house style. Fix ONLY the listed violations.\n"
    "Do not rewrite unaffected sections, change facts, or alter valid URLs except "
    "to correct banned demo paths.\n"
    "Never remove or shorten the FAQ section; keep every H3 Q&A from the input.\n"
    "Preserve H1/H2 structure unless a violation requires a heading change.\n"
    "Output ONLY the full markdown document with the same delimiters/wrappers as input.\n\n"
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

    current, fix_log = lint_mod.apply_deterministic_fixes(text, cta_href=cta_href)
    for entry in fix_log:
        logger.info("writing_format deterministic: %s", entry)

    report = lint_mod.lint(current, stage=stage, cta_href=cta_href, lang=lang)
    if report.ok:
        return current

    logger.info(
        "writing_format lint (%s): %s violation(s)",
        stage,
        len(report.violations),
    )

    if not allow_llm_repair:
        logger.warning("writing_format violations (repair disabled): %s", report.summary())
        return current

    for round_i in range(_MAX_REPAIR_ROUNDS):
        report = lint_mod.lint(current, stage=stage, cta_href=cta_href, lang=lang)
        if report.ok:
            break
        try:
            current = _repair_llm(
                current,
                report,
                stage=stage,
                round_i=round_i + 1,
                cta_href=cta_href,
                lang=lang,
            )
        except Exception:
            logger.exception("writing_format LLM repair failed (stage=%s)", stage)
            break
        current, _ = lint_mod.apply_deterministic_fixes(current, cta_href=cta_href)

    final = lint_mod.lint(current, stage=stage, cta_href=cta_href, lang=lang)
    if not final.ok:
        logger.warning(
            "writing_format still has %s violation(s) after repair: %s",
            len(final.violations),
            final.summary(max_items=8),
        )
    return current


def _repair_llm(
    markdown: str,
    report: lint_mod.LintReport,
    *,
    stage: lint_mod.Stage,
    round_i: int,
    cta_href: str | None = None,
    lang: str | None = None,
) -> str:
    preferred = (cta_href or lint_mod.DEFAULT_CTA_HREF).strip()
    article_lang = lint_mod.detect_article_lang(markdown, hint=lang)
    fr_note = ""
    if article_lang == "fr" and any(
        v.code == "TRANSITION_WORDS" for v in report.violations
    ):
        fr_note = (
            "\nFrench Yoast transition fix: use recognized connectors only "
            "(en effet, par exemple, donc, ainsi, ensuite, enfin, cependant, "
            "toutefois, en revanche, par ailleurs, en outre, en plus, car, "
            "parce que, c'est pourquoi). Never use \"de plus\" — Yoast ignores it.\n"
        )
    if any(v.code == "REPEATED_SENTENCE_START" for v in report.violations):
        fr_note += (
            "\nSentence openings: never start three sentences in a row with the same "
            "word. Reorder the clause, merge two sentences, or open with a connector"
            + (
                " (ainsi, en effet, par ailleurs, en revanche, donc, toutefois)."
                if article_lang == "fr"
                else "."
            )
            + "\n"
        )
    user = (
        f"Stage: {stage}\n"
        f"Repair round: {round_i}\n"
        f"Preferred CTA href for this client: {preferred}\n"
        f"Article language: {article_lang}\n"
        f"{fr_note}\n"
        f"Fix these format violations only:\n{report.summary()}\n\n"
        f"---DOCUMENT---\n{markdown.strip()}\n"
    )
    return claude.chat_complete(
        _REPAIR_SYSTEM,
        user,
        step_label=f"Writing format repair ({stage})",
        max_tokens=8192,
        temperature=0.3,
    ).strip()
