from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend import context_extractor


class CtaHrefTests(unittest.TestCase):
    def test_resolve_uses_website_plus_contact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = root / "apna" / "context"
            ctx.mkdir(parents=True)
            (ctx / "context.md").write_text(
                "## 1. Company Overview\n\n"
                "| Field | Detail |\n|---|---|\n"
                "| Company Name | Méthode APNA |\n"
                "| Website | https://methodeapna.fr |\n",
                encoding="utf-8",
            )
            (ctx / "cta_guidelines.md").write_text(
                "# CTA Guidelines\n\n"
                "### 1. CTA Philosophy\n\n"
                "Invite readers to a conversation, not a hard sell.\n",
                encoding="utf-8",
            )
            with mock.patch.object(context_extractor.config, "CLIENTS_DIR", root):
                href = context_extractor.resolve_cta_href("apna")
                self.assertEqual(href, "https://methodeapna.fr/contact")

    def test_explicit_guidelines_path_joins_website(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = root / "client" / "context"
            ctx.mkdir(parents=True)
            (ctx / "context.md").write_text(
                "Website: https://arsuno.ai\n",
                encoding="utf-8",
            )
            (ctx / "cta_guidelines.md").write_text(
                "Primary CTA URL: /book-a-demo/\n",
                encoding="utf-8",
            )
            with mock.patch.object(context_extractor.config, "CLIENTS_DIR", root):
                href = context_extractor.resolve_cta_href("client")
                self.assertEqual(href, "https://arsuno.ai/book-a-demo")


if __name__ == "__main__":
    unittest.main()
