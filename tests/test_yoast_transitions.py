"""Yoast transition-word scoring (esp. French pitfalls)."""

from __future__ import annotations

import unittest

from backend import writing_format_lint
from backend import yoast_transitions


class YoastTransitionTests(unittest.TestCase):
    def test_de_plus_does_not_count_in_french(self):
        """Yoast FR ignores « de plus » — our scorer must too."""
        # Avoid other Yoast phrases (e.g. "pendant que") in the negative case.
        self.assertFalse(
            yoast_transitions.sentence_has_transition(
                "De plus, le four tourne sans interruption ce dimanche.",
                "fr",
            )
        )
        self.assertTrue(
            yoast_transitions.sentence_has_transition(
                "En outre, le four tourne sans interruption ce dimanche.",
                "fr",
            )
        )
        self.assertTrue(
            yoast_transitions.sentence_has_transition(
                "En plus, le four tourne sans interruption ce dimanche.",
                "fr",
            )
        )

    def test_common_french_connectors_count(self):
        for sent in (
            "Par exemple, une session express dure deux heures.",
            "Donc vous gagnez du temps le dimanche.",
            "Ensuite, rangez les boîtes au froid.",
            "Selon un reportage TF1, l'anticipation change la semaine.",
            "C'est pourquoi ce rituel reste efficace.",
        ):
            self.assertTrue(
                yoast_transitions.sentence_has_transition(sent, "fr"),
                msg=sent,
            )

    def test_choppy_french_body_fails_lint(self):
        # Short unlinked stacks like the Yoast 13% failure case.
        body = (
            "# Comment organiser deux heures\n\n"
            "## Points clés\n\n"
            "La session cuisine structure votre semaine.\n\n"
            "## Le rituel\n\n"
            "La durée varie selon le nombre de personnes. "
            "Ce qui fait la différence, c'est de travailler en parallèle. "
            "Le four tourne. Vous préparez les éléments froids. "
            "Les sauces attendent sur le plan de travail. "
            "Chacun trouve son rythme. La cuisine reste propre.\n\n"
            "Une session express dure deux heures. "
            "Les boîtes partent au frigo. "
            "Les soirs de semaine deviennent simples. "
            "Le stress diminue. "
            "Les repas restent maison.\n"
        )
        report = writing_format_lint.lint(body, stage="draft", lang="fr")
        codes = [v.code for v in report.violations]
        self.assertIn("TRANSITION_WORDS", codes)

    def test_french_body_with_connectors_passes(self):
        body = (
            "# Comment organiser deux heures\n\n"
            "## Points clés\n\n"
            "La session cuisine structure votre semaine.\n\n"
            "## Le rituel\n\n"
            "D'abord, fixez deux heures le dimanche. "
            "Ensuite, découpez les tâches par poste. "
            "Par exemple, une personne gère le four. "
            "En parallèle, une autre prépare les sauces. "
            "Ainsi, rien n'attend inutilement.\n\n"
            "En outre, rangez chaque plat en boîte. "
            "Puis étiquetez les portions pour la semaine. "
            "Enfin, laissez refroidir avant le frigo. "
            "C'est pourquoi les soirs restent simples. "
            "En effet, le stress diminue nettement.\n"
        )
        report = writing_format_lint.lint(body, stage="draft", lang="fr")
        codes = [v.code for v in report.violations]
        self.assertNotIn("TRANSITION_WORDS", codes)


if __name__ == "__main__":
    unittest.main()
