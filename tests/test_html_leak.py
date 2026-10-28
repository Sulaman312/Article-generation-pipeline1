from __future__ import annotations

import unittest

from backend import cta_html, editorial_input, html_leak

CTA_SHELL = """<div class="arsuno-cta">
  <h3>Want help putting this into practice?</h3>
  <p>Talk with our team about your situation and leave with a clear next step.</p>
  <a class="arsuno-cta__btn" href="https://arsuno.ai/contact">
    Talk to our team <span class="arsuno-cta__icon">↗</span>
  </a>
</div>

<style>
.arsuno-cta{ background-color:rgb(27, 28, 46); font-style:normal; }
.arsuno-cta h3{ margin:0 auto 10px !important; }
</style>"""

TABLE_DOC = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Onboarding table preview</title>
<style>
  body { margin: 0; padding: 24px 16px; background: #F4F5F7; }
  .roi-table th { font-weight: 700; }
</style>
</head>
<body>
<div class="tbl-wrap">
  <table class="roi-table">
    <thead><tr><th>Phase</th><th>Manual</th><th>Automated</th></tr></thead>
    <tbody>
      <tr><td>Intake</td><td>45-60 min</td><td>5-8 min</td></tr>
      <tr><td>Follow-ups</td><td>20-30 min</td><td>2-3 min</td></tr>
    </tbody>
  </table>
</div>
</body>
</html>"""

CONTEXT = f"""# CTA guidelines

### 1. CTA Philosophy

Invite readers to a conversation.

Primary CTA URL: https://arsuno.ai/contact

## HTML CTA Template
{CTA_SHELL}

## Phrases
Keep it short.
"""


class PromptSanitizeTests(unittest.TestCase):
    def test_context_html_removed_but_prose_kept(self):
        out = html_leak.strip_html_for_prompt(CONTEXT)
        self.assertNotIn("<div", out)
        self.assertNotIn("<style", out)
        self.assertNotIn("background-color", out)
        self.assertIn("Invite readers to a conversation.", out)
        self.assertIn("Keep it short.", out)
        self.assertIn("Primary CTA URL: https://arsuno.ai/contact", out)

    def test_doctype_page_and_table_removed(self):
        out = html_leak.strip_html_for_prompt("Use tables.\n\n" + TABLE_DOC)
        self.assertNotIn("<table", out)
        self.assertNotIn("roi-table", out)
        self.assertIn("Use tables.", out)

    def test_idempotent(self):
        once = html_leak.strip_html_for_prompt(CONTEXT)
        self.assertEqual(once, html_leak.strip_html_for_prompt(once))

    def test_template_still_extractable_from_raw_file(self):
        self.assertIsNotNone(cta_html.extract_cta_html_template(CONTEXT))


class LeakedArticleTests(unittest.TestCase):
    def test_leaked_table_doc_becomes_markdown_table(self):
        article = f"## Costs\n\nIntro sentence.\n\n{TABLE_DOC}\n\nAfter table."
        out = html_leak.strip_leaked_html(article)
        self.assertNotIn("<", out)
        self.assertNotIn("roi-table", out)
        self.assertIn("| Phase | Manual | Automated |", out)
        self.assertIn("| Intake | 45-60 min | 5-8 min |", out)
        self.assertIn("After table.", out)

    def test_orphan_cta_gets_link_and_shell_removed(self):
        article = (
            "## Six layers\n\nBody.\n\n"
            "**Map your current stack to this architecture**\n\n"
            "Not sure which layers you already have? A short conversation helps.\n\n"
            "HTML CTA Template\n"
            f"{CTA_SHELL}\n\n"
            "## Next section\n"
        )
        out = html_leak.strip_leaked_html(article, cta_href="https://arsuno.ai/contact")
        self.assertNotIn("<div", out)
        self.assertNotIn("<style", out)
        self.assertNotIn("HTML CTA Template", out)
        self.assertIn("[Talk to our team](https://arsuno.ai/contact)", out)
        found = cta_html.find_markdown_ctas(out, cta_href="https://arsuno.ai/contact")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].headline, "Map your current stack to this architecture")

    def test_shell_alone_becomes_full_markdown_cta(self):
        out = html_leak.strip_leaked_html(
            f"## A\n\nText.\n\n{CTA_SHELL}\n\n## B\n", cta_href="https://arsuno.ai/contact"
        )
        found = cta_html.find_markdown_ctas(out, cta_href="https://arsuno.ai/contact")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].headline, "Want help putting this into practice?")

    def test_complete_markdown_cta_not_duplicated(self):
        article = (
            "**Heading**\n\nShort body here.\n\n[Talk to us](https://arsuno.ai/contact)\n\n"
            f"{CTA_SHELL}\n"
        )
        out = html_leak.strip_leaked_html(article, cta_href="https://arsuno.ai/contact")
        self.assertEqual(out.count("https://arsuno.ai/contact"), 1)

    def test_rewrapped_after_strip(self):
        article = f"## A\n\nText.\n\n{CTA_SHELL}\n\n## B\n"
        md = html_leak.strip_leaked_html(article, cta_href="https://arsuno.ai/contact")
        wrapped = cta_html.inject_cta_html(
            md, CTA_SHELL, cta_href="https://arsuno.ai/contact"
        )
        self.assertEqual(wrapped.count('class="arsuno-cta"'), 1)

    def test_clean_article_untouched(self):
        article = "## Heading\n\nPlain text with a < b and [link](https://x.com).\n"
        self.assertEqual(html_leak.strip_leaked_html(article), article)


class FenceTests(unittest.TestCase):
    def test_unclosed_fence_before_shell_is_removed(self):
        article = f"## A\n\nText.\n\n```html\n{CTA_SHELL}\n\n## HR automation\n\nMore text.\n"
        out = html_leak.unwrap_html_fences(article)
        self.assertNotIn("```", out)
        self.assertIn("## HR automation", out)

    def test_closed_fence_around_shell_is_unwrapped(self):
        out = html_leak.unwrap_html_fences(f"Intro\n\n```html\n{CTA_SHELL}\n```\n\n## Next\n")
        self.assertNotIn("```", out)
        self.assertIn('class="arsuno-cta"', out)

    def test_real_code_fence_kept(self):
        article = "Example:\n\n```python\nprint('x')\n```\n"
        self.assertEqual(html_leak.unwrap_html_fences(article), article)

    def test_strip_leaked_html_handles_fenced_shell(self):
        out = html_leak.strip_leaked_html(
            f"## A\n\nText.\n\n```html\n{CTA_SHELL}\n```\n\n## B\n",
            cta_href="https://arsuno.ai/contact",
        )
        self.assertNotIn("```", out)
        self.assertNotIn("<div", out)
        self.assertEqual(
            len(cta_html.find_markdown_ctas(out, cta_href="https://arsuno.ai/contact")), 1
        )


class TemplateExtractionTests(unittest.TestCase):
    def test_spaced_fence_label_and_prose_do_not_leak_into_template(self):
        guide = (
            "## HTML CTA Template\n\nPaste below:\n\n``` html\n"
            f"{CTA_SHELL}\n```\n\nNote: keep it short.\n"
        )
        tpl = cta_html.extract_cta_html_template(guide)
        self.assertIsNotNone(tpl)
        self.assertNotIn("```", tpl)
        self.assertNotIn("Paste below", tpl)
        self.assertNotIn("Note:", tpl)
        self.assertTrue(tpl.startswith("<div"))

    def test_applied_cta_has_no_fences(self):
        guide = f"## HTML CTA Template\n\n```html\n{CTA_SHELL}\n```\n"
        tpl = cta_html.extract_cta_html_template(guide)
        article = (
            "## A\n\nText.\n\n**Heading here**\n\nShort body.\n\n"
            "[Talk to us](https://arsuno.ai/contact)\n\n## B\n\nMore.\n"
        )
        out = cta_html.inject_cta_html(article, tpl, cta_href="https://arsuno.ai/contact")
        self.assertNotIn("```", out)
        self.assertIn("## B", out)


class WordCountTests(unittest.TestCase):
    def test_css_and_tags_do_not_count(self):
        prose = "word " * 100
        plain = editorial_input.count_article_words(prose)
        with_html = editorial_input.count_article_words(
            prose + "\n\n" + CTA_SHELL + "\n\n" + TABLE_DOC
        )
        self.assertEqual(plain, 100)
        # Visible text inside the shells still counts, CSS and tag names do not.
        self.assertLess(with_html - plain, 40)


if __name__ == "__main__":
    unittest.main()
