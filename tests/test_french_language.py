from __future__ import annotations

import unittest
from unittest import mock

from backend import editorial_input, french_language, publish_check
from backend.french_language import FrenchQualityError, Glossary


CLEAN = (
    "# Idées de repas équilibrés\n\n"
    "## À retenir\n\n"
    "- Préparez vos repas à l'avance pour gagner du temps en semaine.\n\n"
    "## La formule Énergie\n\n"
    "La formule Énergie propose un bol de céréales, des fruits et une collation.\n\n"
    "| Moment | Idée |\n|---|---|\n| Matin | Bol de flocons d'avoine |\n"
)


class ScanFrenchTests(unittest.TestCase):
    def test_clean_french_has_no_issues(self):
        self.assertEqual(french_language.scan_french(CLEAN, spelling=False), [])

    def test_banned_words_have_french_replacements(self):
        found = french_language.scan_french(
            "Un bowl, un wrap et un snack.", spelling=False
        )
        by_term = {i.term: i.suggestion for i in found}
        self.assertEqual(by_term.get("bowl"), "bol")
        self.assertEqual(by_term.get("wrap"), "galette roulée")
        self.assertEqual(by_term.get("snack"), "collation")

    def test_batch_cooking_and_coaching_are_replaced(self):
        found = french_language.scan_french(
            "Le batch cooking et le coaching sont utiles.", spelling=False
        )
        suggestions = {i.suggestion for i in found}
        self.assertIn("préparation des repas à l'avance", " ".join(suggestions).replace("’", "'"))
        self.assertIn("accompagnement", suggestions)

    def test_pack_must_be_formule_brand_term(self):
        found = french_language.scan_french(
            "Choisissez le pack Découverte pour commencer.", spelling=False
        )
        self.assertTrue(
            [i for i in found if i.code in {"fr_banned_word", "fr_brand_term"}], msg=found
        )

    def test_headings_tables_and_faq_are_scanned(self):
        text = (
            "## Healthy ideas\n\n| Snack | Idée |\n|---|---|\n| Matin | Oui |\n\n"
            "## Questions fréquentes\n\n### Que choisir ?\n\nPrenez un bowl.\n"
        )
        terms = {i.term for i in french_language.scan_french(text, spelling=False)}
        self.assertTrue({"snack", "bowl"} <= terms, msg=terms)

    def test_urls_and_link_targets_are_ignored(self):
        text = "Lisez [le guide](https://example.com/healthy-snack-bowl) pour en savoir plus."
        self.assertEqual(french_language.scan_french(text, spelling=False), [])

    def test_placeholders_and_default_filler_are_caught(self):
        for filler in (
            "It depends on the task, the tools already in place.",
            "[INSERT STAT HERE]",
            "Lorem ipsum dolor sit amet.",
            "Cela dépend de votre situation, de vos contraintes et de ce que vous pouvez préparer d'abord.",
        ):
            found = french_language.scan_french(f"Texte. {filler}", spelling=False)
            self.assertTrue(
                any(i.code == "fr_placeholder" for i in found), msg=(filler, found)
            )

    def test_english_date_abbreviation(self):
        found = french_language.scan_french("Publié le 12 Sep. 2026.", spelling=False)
        self.assertTrue(any(i.code == "fr_english_word" for i in found), msg=found)
        self.assertEqual(french_language.scan_french("Publié le 12 sept. 2026.", spelling=False), [])

    @unittest.skipUnless(french_language.spellcheck_available(), "pyspellchecker missing")
    def test_spelling_error_is_reported_with_correction(self):
        found = french_language.scan_french(
            "Cette recette est très equilibrée et facile.", spelling=True
        )
        self.assertTrue(
            any(i.code == "fr_spelling" and i.suggestion for i in found), msg=found
        )

    @unittest.skipUnless(french_language.spellcheck_available(), "pyspellchecker missing")
    def test_elisions_are_not_misspellings(self):
        text = "Jusqu'à demain, lorsqu’il pleut, puisqu'on part aujourd'hui."
        self.assertEqual(french_language.scan_french(text, spelling=True), [])

    @unittest.skipUnless(french_language.spellcheck_available(), "pyspellchecker missing")
    def test_correct_text_has_no_spelling_issue(self):
        self.assertEqual(french_language.scan_french(CLEAN, spelling=True), [])


class GlossaryTests(unittest.TestCase):
    def test_defaults_contain_brand_terms(self):
        g = Glossary()
        for term in ("formule Découverte", "formule Énergie", "formule Gagnant"):
            self.assertIn(term, g.brand_terms)

    def test_file_extends_defaults(self):
        g = french_language.parse_glossary(
            "## Termes de la marque\n- formule Sérénité\n\n"
            "## Mots interdits\n- smoothie -> boisson mixée\n\n"
            "## Mots autorisés\n- Nutri-Score\n"
        )
        # Brand terms in the file replace the defaults; banned words are merged.
        self.assertEqual(g.brand_terms, ["formule Sérénité"])
        self.assertEqual(g.banned.get("smoothie"), "boisson mixée")
        self.assertEqual(g.banned.get("bowl"), "bol")

    def test_system_block_carries_the_rule_and_brand_terms(self):
        block = french_language.system_block(Glossary())
        self.assertIn(french_language.FRENCH_RULE, block)
        self.assertIn("formule Énergie", block)
        self.assertIn("bowl", block)

    def test_rule_text_is_exact(self):
        self.assertEqual(
            french_language.FRENCH_RULE,
            "Tout en français, aucun mot anglais, y compris titres, FAQ, tableaux et méta.",
        )


class EnforceArtifactTests(unittest.TestCase):
    def test_clean_text_is_returned_without_model_call(self):
        repair = mock.Mock()
        out = french_language.enforce_french_artifact(
            CLEAN, step_label="t", structural=False, repair=repair
        )
        self.assertEqual(out, CLEAN)
        repair.assert_not_called()

    def test_dirty_text_is_repaired(self):
        repair = mock.Mock(return_value="Un bol et une collation.")
        out = french_language.enforce_french_artifact(
            "Un bowl et un snack.", step_label="t", structural=False, repair=repair
        )
        self.assertEqual(out, "Un bol et une collation.")
        self.assertEqual(repair.call_count, 1)

    def test_still_dirty_raises_instead_of_inserting_default_text(self):
        repair = mock.Mock(return_value="Toujours un bowl.")
        with self.assertRaises(FrenchQualityError):
            french_language.enforce_french_artifact(
                "Un bowl.", step_label="t", structural=False, attempts=2, repair=repair
            )
        self.assertEqual(repair.call_count, 2)


class LanguageDetectionTests(unittest.TestCase):
    def test_language_field(self):
        self.assertEqual(editorial_input.article_language_from_manual({"Language": "Français"}), "fr")
        self.assertEqual(editorial_input.article_language_from_manual({"Language": "English"}), "en")

    def test_french_topic_is_detected(self):
        manual = {"Topic": "Comment préparer ses repas de la semaine à l'avance"}
        self.assertEqual(editorial_input.article_language_from_manual(manual), "fr")

    def test_english_topic_stays_english(self):
        manual = {"Topic": "How to prepare weekly meals in advance"}
        self.assertEqual(editorial_input.article_language_from_manual(manual), "en")

    def test_notes_still_win(self):
        manual = {"Topic": "Weekly meals", "Notes": "Write the article in French."}
        self.assertEqual(editorial_input.article_language_from_manual(manual), "fr")


class PublishCheckTests(unittest.TestCase):
    def _check(self, **kw):
        defaults = dict(
            client_id="c",
            run_id="r",
            article_md=CLEAN,
            title="Idées de repas équilibrés",
            meta_title="Repas équilibrés : nos idées",
            meta_description="Découvrez nos idées de repas équilibrés pour toute la semaine.",
            lang="fr",
        )
        defaults.update(kw)
        with mock.patch.object(
            french_language, "load_glossary", return_value=Glossary()
        ):
            return publish_check.check_publishable(**defaults)

    def test_clean_french_passes(self):
        self.assertTrue(self._check().ok)

    def test_english_word_in_article_blocks(self):
        report = self._check(article_md=CLEAN + "\nPrenez un bowl.\n")
        self.assertFalse(report.ok)
        self.assertIn("Article", report.message())

    def test_english_in_meta_blocks(self):
        report = self._check(meta_title="Healthy snack ideas")
        self.assertFalse(report.ok)
        self.assertTrue(any(where == "Meta title" for where, _ in report.issues))

    def test_placeholder_blocks_any_language(self):
        report = self._check(
            lang="en", article_md="# Title\n\nIt depends on the task, the tools already in place."
        )
        self.assertFalse(report.ok)

    def test_ensure_publishable_raises(self):
        with mock.patch.object(french_language, "load_glossary", return_value=Glossary()):
            with self.assertRaises(publish_check.PublishCheckError):
                publish_check.ensure_publishable(
                    client_id="c",
                    run_id="r",
                    article_md="Un snack.",
                    title="Titre",
                    lang="fr",
                )


if __name__ == "__main__":
    unittest.main()
