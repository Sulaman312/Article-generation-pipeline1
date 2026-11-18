from __future__ import annotations

import unittest
from unittest import mock

from backend import final_output_enforce as fo
from backend.context_extractor import _cluster_titles

HREF = "https://methodeapna.fr/contact"

ARTICLE = """# Title

## Intro section

Paragraph one is long enough to count as body text for the article.

## Second section

Paragraph two is long enough to count as body text for the article.

## Third section

Paragraph three is long enough to count as body text for the article.

## Fourth section

Paragraph four is long enough to count as body text for the article.

## Questions fréquentes

### Q?

Answer.

## Conclusion

Done.
"""


class EnsureMinCtasTests(unittest.TestCase):
    def test_inserts_two_ctas_when_model_wrote_none(self):
        out, n = fo.ensure_min_ctas(ARTICLE, cta_href=HREF, lang="fr")
        self.assertEqual(n, 2)
        self.assertEqual(out.count(f"]({HREF})"), 2)
        self.assertIn("Besoin d'aide", out)
        # Never placed in or after FAQ / conclusion.
        self.assertLess(out.rfind(f"]({HREF})"), out.index("## Questions fréquentes"))

    def test_noop_when_enough_ctas_exist(self):
        art = ARTICLE.replace(
            "## Third section",
            f"**Need help?**\n\nWe can help you today.\n\n[Talk to us]({HREF})\n\n## Third section",
        ).replace(
            "## Fourth section",
            f"**Ready?**\n\nReach out to the team.\n\n[Contact us]({HREF})\n\n## Fourth section",
        )
        out, n = fo.ensure_min_ctas(art, cta_href=HREF)
        self.assertEqual(n, 0)
        self.assertEqual(out, art)

    def test_tops_up_when_only_one_exists(self):
        art = ARTICLE.replace(
            "## Third section",
            f"**Need help?**\n\nWe can help you today.\n\n[Talk to us]({HREF})\n\n## Third section",
        )
        out, n = fo.ensure_min_ctas(art, cta_href=HREF)
        self.assertEqual(n, 1)
        self.assertEqual(fo.count_cta_blocks(out, HREF), 2)


class ClusterTitleTests(unittest.TestCase):
    def test_original_format_still_parses(self):
        text = "## CLUSTER 1\n\n### Nutrition \u2014 Pillar\n\n## CLUSTER 2\n\n### Sommeil \u2014 Pilier\n"
        self.assertEqual(_cluster_titles(text), ["Nutrition", "Sommeil"])

    def test_colon_and_hyphen_formats_parse(self):
        text = "## Cluster 1: Nutrition\n\n| URL | Anchor |\n\n### Cluster 2 - Sommeil\n"
        self.assertEqual(_cluster_titles(text), ["Nutrition", "Sommeil"])

    def test_title_on_following_line(self):
        text = "## Cluster 1\n\n### Nutrition - Pillar\n"
        self.assertEqual(_cluster_titles(text), ["Nutrition"])


class FaqInjectTests(unittest.TestCase):
    def test_injects_faq_block_without_replacing_the_article(self):
        faq_md = (
            "## Frequently Asked Questions\n\n"
            "### How do I start?\n\n"
            "Open the portal and pick a slot. Join a few minutes early.\n\n"
            "### What does it cost?\n\n"
            "Fees vary by provider. Check the clinic page before you book.\n"
        )
        with mock.patch.object(
            fo.claude, "chat_complete", return_value=faq_md
        ) as mocked:
            out = fo.inject_faq_template(
                ARTICLE.replace("## Questions fréquentes\n\n### Q?\n\nAnswer.\n\n", ""),
                topic="batch cooking",
                manual={"Language": "en"},
            )
        mocked.assert_called_once()
        self.assertIn("## Frequently Asked Questions", out)
        self.assertIn("How do I start?", out)
        self.assertIn("Paragraph one is long enough", out)
        # The model was not asked to return the full article.
        user = mocked.call_args.args[1] if mocked.call_args.args else mocked.call_args.kwargs.get("user")
        if user is None:
            user = mocked.call_args[0][1]
        self.assertIn("ARTICLE EXCERPT", user)
        self.assertNotIn("Return ONLY the full article", mocked.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
