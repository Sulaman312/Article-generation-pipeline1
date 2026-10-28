from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend import cta_html


SAMPLE_TEMPLATE = """
<div class="arsuno-cta">
  <h3>Build a recruitment workflow that holds up under scrutiny</h3>
  <p><strong>arsuno.ai</strong> builds custom AI-assisted recruitment workflows.</p>
  <a class="arsuno-cta__btn" href="https://arsuno.ai/contact">
    Talk to the team about your workflow <span class="arsuno-cta__icon">↗</span>
  </a>
</div>

<style>
.arsuno-cta{ color:#fff; }
</style>
""".strip()

PLACEHOLDER_TEMPLATE = """
<div class="ws-cta">
  <h3>{{headline}}</h3>
  <p>{{body}}</p>
  <a href="{{href}}">{{button}}</a>
</div>
""".strip()


class CtaHtmlExtractTests(unittest.TestCase):
    def test_extract_from_fenced_section(self):
        md = (
            "# CTA\n\n### 1. CTA Philosophy\n\nBe helpful.\n\n"
            "### HTML CTA Template\n\n"
            "```html\n"
            f"{PLACEHOLDER_TEMPLATE}\n"
            "```\n"
        )
        tpl = cta_html.extract_cta_html_template(md)
        self.assertIsNotNone(tpl)
        self.assertIn("{{headline}}", tpl)
        self.assertIn("ws-cta", tpl)

    def test_extract_bare_example_html(self):
        md = "# CTA\n\n### HTML CTA Template\n\n" + SAMPLE_TEMPLATE
        tpl = cta_html.extract_cta_html_template(md)
        self.assertIsNotNone(tpl)
        self.assertIn("arsuno-cta", tpl)
        self.assertIn("<style>", tpl)

    def test_no_template_returns_none(self):
        self.assertIsNone(
            cta_html.extract_cta_html_template(
                "### 1. CTA Philosophy\n\nInvite a conversation.\n"
            )
        )


class CtaHtmlRenderTests(unittest.TestCase):
    def test_placeholder_fill(self):
        out = cta_html.render_cta_html(
            PLACEHOLDER_TEMPLATE,
            headline="Hire faster with audit trails",
            body="**Brand** helps agencies ship compliant workflows.",
            button="Talk to us",
            href="https://arsuno.ai/contact",
        )
        self.assertIn("<h3>Hire faster with audit trails</h3>", out)
        self.assertIn("<strong>Brand</strong> helps agencies", out)
        self.assertIn('href="https://arsuno.ai/contact"', out)
        self.assertIn(">Talk to us</a>", out)
        self.assertNotIn("{{", out)

    def test_structural_fill_keeps_icon_span(self):
        out = cta_html.render_cta_html(
            SAMPLE_TEMPLATE,
            headline="New headline for this article",
            body="Fresh body copy for the CTA.",
            button="Book a call",
            href="https://arsuno.ai/contact",
            include_style=True,
        )
        self.assertIn("<h3>New headline for this article</h3>", out)
        self.assertIn("Fresh body copy for the CTA.", out)
        self.assertIn("Book a call", out)
        self.assertIn('<span class="arsuno-cta__icon">↗</span>', out)
        self.assertIn("<style>", out)
        self.assertNotIn("Build a recruitment workflow", out)

    def test_style_stripped_on_repeat(self):
        out = cta_html.render_cta_html(
            SAMPLE_TEMPLATE,
            headline="H",
            body="B",
            button="Go",
            href="https://arsuno.ai/contact",
            include_style=False,
        )
        self.assertNotIn("<style>", out)


class CtaHtmlInjectTests(unittest.TestCase):
    def test_replaces_markdown_ctas(self):
        article = (
            "# Title\n\n"
            "## First section\n\n"
            "Prose here.\n\n"
            "**Build a recruitment workflow that holds up**\n\n"
            "**arsuno.ai** builds custom AI-assisted recruitment workflows for agencies.\n\n"
            "[Talk to the team](https://arsuno.ai/contact)\n\n"
            "## Second section\n\n"
            "More prose.\n\n"
            "**Ship audit-ready screening**\n\n"
            "Keep humans in the loop at every stage.\n\n"
            "[Get in touch](https://arsuno.ai/contact)\n\n"
            "## Closing\n"
        )
        out = cta_html.inject_cta_html(
            article, SAMPLE_TEMPLATE, cta_href="https://arsuno.ai/contact"
        )
        self.assertIn('class="arsuno-cta"', out)
        self.assertIn("Build a recruitment workflow that holds up", out)
        self.assertIn("Ship audit-ready screening", out)
        self.assertEqual(out.count("<style>"), 1)
        self.assertNotIn("**Build a recruitment workflow that holds up**", out)
        self.assertNotIn("[Talk to the team](https://arsuno.ai/contact)", out)
        self.assertIn("## Second section", out)

    def test_apply_workspace_loads_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = root / "arsuno" / "context"
            ctx.mkdir(parents=True)
            (ctx / "cta_guidelines.md").write_text(
                "# CTA\n\nPrimary CTA URL: https://arsuno.ai/contact\n\n"
                "### HTML CTA Template\n\n"
                f"```html\n{PLACEHOLDER_TEMPLATE}\n```\n",
                encoding="utf-8",
            )
            article = (
                "**Headline one**\n\n"
                "Body one for the card.\n\n"
                "[Click here](https://arsuno.ai/contact)\n"
            )
            with mock.patch("backend.config.CLIENTS_DIR", root):
                out = cta_html.apply_workspace_cta_html(
                    article,
                    client_id="arsuno",
                    cta_href="https://arsuno.ai/contact",
                )
            self.assertIn("<h3>Headline one</h3>", out)
            self.assertIn("Body one for the card.", out)
            self.assertIn(">Click here</a>", out)

    def test_finds_cta_when_body_has_brand_bold(self):
        article = (
            "**Not sure where your MVP stack should start?**\n\n"
            "**arsuno.ai** designs AI customer support workflows for your team.\n\n"
            "[Let's talk through your stack](https://arsuno.ai/contact)\n"
        )
        found = cta_html.find_markdown_ctas(
            article, cta_href="https://arsuno.ai/contact"
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].headline, "Not sure where your MVP stack should start?")
        self.assertIn("arsuno.ai", found[0].body)


if __name__ == "__main__":
    unittest.main()
