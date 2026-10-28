from __future__ import annotations

import unittest

from backend import content_to_cms, cta_html, hard_gates, image_alt
from backend import final_output_enforce as fo

HREF = "/contact"

CTA = "**Besoin d'aide ?**\n\nParlez à l'équipe de votre projet.\n\n[Parler à l'équipe](/contact)\n"

ARTICLE = f"""# Idées de repas

## À retenir

- Préparez vos repas à l'avance.

![Un bol de céréales avec des fruits sur une table en bois](IMAGE: bol-cereales)

## Première section

Texte de la première section.

## Deuxième section

Texte de la deuxième section.

## Troisième section

Texte de la troisième section.

## Questions fréquentes

### Combien de temps ?

Trois jours au frais. Au delà, congelez.

## Conclusion

Fin.
"""


def _cta_positions(article: str) -> list[int]:
    return [c.start for c in cta_html.find_markdown_ctas(article, cta_href=HREF)]


class CtaPolicyTests(unittest.TestCase):
    def test_exactly_two_added_none_in_opening(self):
        out, n = fo.ensure_min_ctas(ARTICLE, cta_href=HREF, lang="fr")
        self.assertEqual(n, 2)
        pos = _cta_positions(out)
        self.assertEqual(len(pos), 2)
        self.assertGreater(min(pos), out.index("## Première section") + 40)
        # One in between, one at the end (before the FAQ).
        self.assertLess(pos[0], pos[1])
        self.assertLess(pos[1], out.index("## Questions fréquentes"))
        self.assertGreater(pos[1], out.index("## Deuxième section"))

    def test_cta_in_opening_is_removed(self):
        art = ARTICLE.replace(
            "## Première section", f"{CTA}\n## Première section", 1
        )
        self.assertEqual(len(_cta_positions(art)), 1)
        out, _ = fo.ensure_min_ctas(art, cta_href=HREF, lang="fr")
        pos = _cta_positions(out)
        self.assertEqual(len(pos), 2)
        self.assertGreater(min(pos), out.index("## Première section"))

    def test_never_more_than_two(self):
        art = ARTICLE
        for heading in ("Deuxième section", "Troisième section", "Questions fréquentes"):
            art = art.replace(f"## {heading}", f"{CTA}\n## {heading}", 1)
        self.assertEqual(len(_cta_positions(art)), 3)
        out, n = fo.ensure_min_ctas(art, cta_href=HREF, lang="fr")
        self.assertEqual(n, 0)
        self.assertEqual(len(_cta_positions(out)), 2)
        self.assertEqual(fo.count_cta_blocks(out, HREF), 2)
        # The article text around them is intact.
        for heading in ("Première section", "Deuxième section", "Troisième section"):
            self.assertIn(f"## {heading}", out)

    def test_two_good_ctas_are_untouched(self):
        art = ARTICLE.replace("## Troisième section", f"{CTA}\n## Troisième section", 1).replace(
            "## Questions fréquentes", f"{CTA}\n## Questions fréquentes", 1
        )
        out, n = fo.ensure_min_ctas(art, cta_href=HREF, lang="fr")
        self.assertEqual(n, 0)
        self.assertEqual(out, art)

    def test_idempotent(self):
        once, _ = fo.ensure_min_ctas(ARTICLE, cta_href=HREF, lang="fr")
        twice, n = fo.ensure_min_ctas(once, cta_href=HREF, lang="fr")
        self.assertEqual(n, 0)
        self.assertEqual(once, twice)


TEMPLATE = """    <div class="cta-card">
        <h3>{{headline}}</h3>

        <p>{{body}}</p>

        <a class="cta-btn" href="{{href}}">{{button}}</a>
    </div>

    <style>
    .cta-card { padding: 24px; }

        .cta-btn { color: #fff; }
    </style>"""


class CtaHtmlDoesNotBreakArticleTests(unittest.TestCase):
    def _article(self) -> str:
        out, _ = fo.ensure_min_ctas(ARTICLE, cta_href=HREF, lang="fr")
        return cta_html.inject_cta_html(out, TEMPLATE, cta_href=HREF)

    def test_html_is_one_compact_block_between_blank_lines(self):
        out = self._article()
        self.assertEqual(out.count('<div class="cta-card">'), 2)
        self.assertEqual(out.count("<style>"), 1)
        for block in out.split("\n\n"):
            if "cta-card" in block and "<div" in block:
                self.assertNotIn("\n\n", block)
                self.assertTrue(all(not ln.startswith(" ") for ln in block.splitlines()))

    def test_markdown_after_the_cta_is_converted_normally(self):
        html = content_to_cms._markdown_to_html(content_to_cms._clean_markdown(self._article()))
        self.assertNotIn("<pre>", html)
        self.assertNotIn("<code>", html)
        self.assertNotIn("##", html)
        self.assertIn("<h2>Troisième section</h2>", html)
        self.assertIn("<h2>Questions fréquentes</h2>", html)
        self.assertEqual(html.count('<div class="cta-card">'), 2)

    def test_unbalanced_template_falls_back_to_markdown_cta(self):
        broken = '<div class="cta-card"><h3>{{headline}}</h3><a href="{{href}}">{{button}}</a>'
        out, _ = fo.ensure_min_ctas(ARTICLE, cta_href=HREF, lang="fr")
        injected = cta_html.inject_cta_html(out, broken, cta_href=HREF)
        self.assertEqual(injected, out)

    def test_unclosed_html_in_markdown_does_not_swallow_the_article(self):
        text = "Avant.\n\n<div class=\"x\">\ntexte\n\n## Titre\n\nSuite.\n"
        html = content_to_cms._markdown_to_html(text)
        self.assertIn("<h2>Titre</h2>", html)


class ImageAltTests(unittest.TestCase):
    def test_slug_alt_becomes_readable_without_hyphen(self):
        out = image_alt.normalize_image_alts(
            "![ai-resume-screening-recruiter-review](IMAGE: ai-resume-screening-recruiter-review)"
        )
        alt = out[2 : out.index("]")]
        self.assertNotIn("-", alt)
        self.assertEqual(alt, "Ai resume screening recruiter review")
        # The image slug itself is untouched.
        self.assertIn("(IMAGE: ai-resume-screening-recruiter-review)", out)

    def test_hyphens_in_a_real_sentence_are_removed(self):
        out = image_alt.normalize_image_alts(
            "![Une femme prépare un repas à l'avance — c'est-à-dire en une heure](IMAGE: x)"
        )
        alt = out[2 : out.index("](")]
        for ch in "-\u2014\u2013":
            self.assertNotIn(ch, alt)
        self.assertIn("femme prépare un repas", alt)

    def test_empty_or_generic_alt_is_rebuilt(self):
        out = image_alt.normalize_image_alts(
            "## Préparer ses repas\n\n![image](IMAGE: bol-cereales-fruits)\n"
        )
        self.assertIn("![Bol cereales fruits](IMAGE: bol-cereales-fruits)", out)
        out = image_alt.normalize_image_alts("## Préparer ses repas\n\n![](IMAGE: bol)\n")
        self.assertIn("Préparer ses repas", out)

    def test_good_alt_is_kept(self):
        md = "![Un bol de céréales avec des fruits sur une table](IMAGE: bol)"
        self.assertEqual(image_alt.normalize_image_alts(md), md)

    def test_gate_reports_leftover_problems(self):
        self.assertTrue(hard_gates.check_image_alt("![a-b](IMAGE: x)"))
        self.assertEqual(
            hard_gates.check_image_alt("![Un bol de céréales avec des fruits](IMAGE: x)"), []
        )

    def test_real_urls_are_not_changed_only_alt(self):
        out = image_alt.normalize_image_alts(
            "![Un repas équilibré sur la table](https://cdn.example.com/a-b-c.jpg)"
        )
        self.assertIn("(https://cdn.example.com/a-b-c.jpg)", out)


if __name__ == "__main__":
    unittest.main()
