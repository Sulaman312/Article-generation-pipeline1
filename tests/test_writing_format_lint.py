from __future__ import annotations

import unittest

from backend import writing_format_lint as lint


class WritingFormatLintTests(unittest.TestCase):
    def test_detects_em_dash(self):
        text = "## Why teams struggle\n\nAI adoption is hard — most teams stall."
        report = lint.lint(text, stage="draft")
        codes = {v.code for v in report.violations}
        self.assertIn("EM_DASH", codes)

    def test_detects_banned_closing_heading(self):
        text = "## How to start\n\nBody.\n\n## Conclusion\n\nWrap up."
        report = lint.lint(text, stage="draft")
        self.assertTrue(any(v.code == "BANNED_CLOSING_HEADING" for v in report.violations))

    def test_detects_long_sentence(self):
        words = " ".join(f"word{i}" for i in range(35))
        text = f"## Section\n\n{words}."
        report = lint.lint(text, stage="draft")
        self.assertTrue(any(v.code == "SENTENCE_TOO_LONG" for v in report.violations))

    def test_detects_h2_h3_bridge_violation(self):
        text = "## Section title\n### Subhead without bridge\n\nContent."
        report = lint.lint(text, stage="draft")
        self.assertTrue(any(v.code == "H2_H3_NO_BRIDGE" for v in report.violations))

    def test_detects_wrong_demo_slug(self):
        text = "## Section\n\n**Try it**\n\nSee the product.\n\n[Book](/demo/)"
        report = lint.lint(text, stage="final")
        self.assertTrue(any(v.code == "CTA_DEMO_SLUG" for v in report.violations))

    def test_deterministic_demo_slug_fix(self):
        text = "## Section\n\n[Book a demo](/request-demo/)"
        fixed, log = lint.apply_deterministic_fixes(text)
        self.assertIn("/book-a-demo/", fixed)
        self.assertTrue(log)

    def test_outline_title_case_flag(self):
        text = "---OUTLINE START---\nH1: Good title\nH2: How To Build AI Pipelines\n---OUTLINE END---"
        report = lint.lint(text, stage="outline")
        self.assertTrue(any(v.code == "HEADING_TITLE_CASE" for v in report.violations))

    def test_clean_article_passes_basic_checks(self):
        text = (
            "## Why shadow AI matters\n\n"
            "Teams deploy AI tools without oversight. "
            "That gap creates compliance risk you can fix today.\n\n"
            "## What to do next\n\n"
            "Start with an inventory of every AI tool in use. "
            "Document owners and data flows before you scale."
        )
        report = lint.lint(text, stage="draft")
        self.assertTrue(report.ok, report.summary())

    def test_brief_em_dash_detected(self):
        text = (
            "---BRIEF START---\n"
            "ARTICLE TITLE: Test title\n"
            "SUGGESTED STRUCTURE:\n"
            "  - H2: Section one — does something\n"
            "---BRIEF END---\n"
        )
        report = lint.lint(text, stage="brief")
        self.assertTrue(any(v.code == "EM_DASH" for v in report.violations))

    def test_strip_em_dashes_in_brief(self):
        text = "---BRIEF START---\nH2: Foo — bar\n---BRIEF END---"
        fixed, changed = lint.strip_em_dashes(text)
        self.assertTrue(changed)
        self.assertNotIn("\u2014", fixed)
        self.assertIn("Foo: bar", fixed)


if __name__ == "__main__":
    unittest.main()
