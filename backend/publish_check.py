"""Pre-publish check: nothing reaches the CMS if the copy still has defects.

Scans the article, the title and the meta title / description for:
  - English words (French articles),
  - banned words and wrong brand terms (``french_glossary.md``),
  - placeholders and default filler text (any language),
  - French spelling mistakes.

``run_content_to_cms`` calls :func:`ensure_publishable`, which raises
:class:`PublishCheckError` with a full report instead of sending the draft.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from . import artifacts
from . import config
from . import editorial_input
from . import french_language

logger = logging.getLogger(__name__)


@dataclass
class PublishReport:
    language: str = "en"
    # (where, issue) pairs, where = "Article" | "Titre" | "Meta title" | "Meta description"
    issues: list[tuple[str, french_language.FrenchIssue]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def message(self) -> str:
        if self.ok:
            return "Pre-publish check passed."
        lines = [
            "Publication bloquée : le contrôle avant publication a trouvé "
            f"{len(self.issues)} problème(s). Corrigez-les, puis relancez l'étape.",
        ]
        for where, issue in self.issues[:40]:
            lines.append(f"- [{where}] {issue.message()}")
        if len(self.issues) > 40:
            lines.append(f"- … et {len(self.issues) - 40} autre(s) problème(s).")
        return "\n".join(lines)


class PublishCheckError(RuntimeError):
    def __init__(self, report: PublishReport):
        self.report = report
        super().__init__(report.message())


def _article_language(client_id: str, run_id: str) -> str:
    manifest = artifacts.read_run_manifest(client_id, run_id) or {}
    manual = manifest.get("manual_inputs")
    if not isinstance(manual, dict):
        manual = {}
    return editorial_input.article_language_from_manual(manual)


def check_publishable(
    *,
    client_id: str,
    run_id: str,
    article_md: str,
    title: str = "",
    meta_title: str = "",
    meta_description: str = "",
    lang: str | None = None,
) -> PublishReport:
    """Scan everything that would be published. Never calls a model."""
    language = (lang or _article_language(client_id, run_id) or "en").lower()
    report = PublishReport(language=language)
    parts = (
        ("Article", article_md),
        ("Titre", title),
        ("Meta title", meta_title),
        ("Meta description", meta_description),
    )

    if language == "fr":
        if not config.FRENCH_QA_ENABLED:
            return report
        glossary = french_language.load_glossary(client_id)
        for where, text in parts:
            for issue in french_language.scan_french(
                text,
                glossary=glossary,
                spelling=config.FRENCH_SPELLCHECK_ENABLED,
                structural=(where == "Article"),
            ):
                report.issues.append((where, issue))
        return report

    # Other languages: only default filler / placeholders are language independent.
    for where, text in parts:
        for issue in french_language.scan_french(
            text, spelling=False, english=False, banned=False, placeholders=True
        ):
            report.issues.append((where, issue))
    return report


def ensure_publishable(**kwargs) -> PublishReport:
    """Raise :class:`PublishCheckError` when the check finds anything."""
    report = check_publishable(**kwargs)
    if not report.ok:
        logger.warning("pre-publish check blocked publishing: %s", report.message())
        raise PublishCheckError(report)
    return report
