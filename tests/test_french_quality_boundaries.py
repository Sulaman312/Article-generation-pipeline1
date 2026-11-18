import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend import config, french_language as fr, quality_execution, prompt_cache, prompts


class ProtectionTests(unittest.TestCase):
    def test_names_units_and_acronyms_are_preserved(self):
        text = 'Nature et Wiley citent International Journal of Obesity : E-E-A-T, H1, H2, FAQ, kcal, yo-yo.'
        self.assertEqual(fr.scan_french(text, spelling=False), [])
        self.assertEqual(fr.apply_glossary_replacements(text), text)

    def test_custom_multiword_proper_name(self):
        glossary = fr.parse_glossary('## Mots autorisés\n- The Healthy Bowl Company\n')
        text = 'The Healthy Bowl Company propose un repas.'
        self.assertEqual(fr.apply_glossary_replacements(text, glossary), text)
        self.assertEqual(fr.scan_french(text, glossary=glossary, spelling=False), [])

    def test_all_protected_zones_skip_scanning_and_replacement(self):
        zones = ['`healthy bowl`', '```python\nhealthy bowl\n```',
                 '[healthy bowl](https://example.org/bowl)',
                 '<a href="https://example.org">healthy bowl</a>',
                 '« healthy bowl »', '“healthy bowl”', '"healthy bowl"',
                 'https://example.org/healthy-bowl']
        for zone in zones:
            with self.subTest(zone=zone):
                self.assertEqual(fr.scan_french('Texte. '+zone, spelling=False), [])
                self.assertEqual(fr.apply_glossary_replacements(zone), zone)

    def test_whole_word_boundaries(self):
        self.assertEqual(fr.scan_french('Une offre de formation.', spelling=False), [])
        self.assertEqual(fr.apply_glossary_replacements('bulletin et heron'), 'bulletin et heron')

    def test_isolated_ambiguity_warns_but_phrase_blocks(self):
        found = fr.scan_french('Le terme best apparaît ici.', spelling=False)
        self.assertTrue(found)
        self.assertEqual(fr.blocking_issues(found), [])
        self.assertTrue(fr.blocking_issues(fr.scan_french('This is the best choice.', spelling=False)))
        self.assertTrue(fr.blocking_issues(fr.scan_french('THIS IS THE BEST CHOICE.', spelling=False)))

    def test_acronym_exemption_is_case_sensitive(self):
        g = fr.parse_glossary('## Mots autorisés\n- BEST\n')
        self.assertEqual(fr.scan_french('BEST', glossary=g, spelling=False), [])
        self.assertTrue(fr.scan_french('best', glossary=g, spelling=False))

    def test_known_replacements_are_free(self):
        repair = mock.Mock()
        out = fr.enforce_french_artifact('Une hero et une bullet.', step_label='t', repair=repair)
        self.assertEqual(out, 'Une image principale et une puce.')
        repair.assert_not_called()

    def test_repair_count_is_bounded_and_failure_retains_text(self):
        repair = mock.Mock(side_effect=lambda text, issues: text)
        with self.assertRaises(fr.FrenchQualityError) as cm:
            fr.enforce_french_artifact('This is the best choice.', step_label='t', repair=repair, attempts=20)
        self.assertEqual(repair.call_count, 2)
        self.assertEqual(cm.exception.text, 'This is the best choice.')

    def test_one_exact_snippet_repair(self):
        original = 'Une phrase. This is the best choice. Une autre phrase.'
        def respond(system, user, **kwargs):
            import json
            excerpts = json.loads(user.split('Extraits :\n')[1])
            old = excerpts[0]
            self.assertIn(old, original)
            return json.dumps([{'old': old, 'new': old.replace('This is the best choice.', 'Ce choix convient.')}])
        with mock.patch('backend.integrations.anthropic.chat_complete', side_effect=respond):
            out = fr.enforce_french_artifact(original, step_label='t', attempts=1)
        self.assertEqual(out, 'Une phrase. Ce choix convient. Une autre phrase.')


class BoundaryTests(unittest.TestCase):
    def test_all_templates_have_french_versions(self):
        root = Path(prompts.__file__).parent
        for path in (root/'steps').glob('*.md'):
            localized = fr.localize_step_prompt(path.read_text(encoding="utf-8"))
            self.assertIn('Vous êtes un rédacteur', localized)
            self.assertNotIn('You are', localized)

    def test_shared_data_and_suffix_localized(self):
        with mock.patch.object(prompt_cache, 'build_shared_documents_block', return_value='---ATP TOPIC RESEARCH---\n## Snapshot\nTexte.'):
            cached = prompt_cache.build_cached_prompt(client_id='c', run_id='r', lang='fr', step_name='draft', step_prompt=prompts.DRAFT_PROMPT, unique_suffix='main article only', step_label='t')
        self.assertNotIn('ATP TOPIC RESEARCH', cached.shared_docs_text)
        self.assertNotIn('main article only', cached.unique_text)

    def test_failed_output_is_sidecar_and_never_approved_artifact(self):
        from backend import artifacts
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(config, 'CLIENTS_DIR', Path(tmp)):
            with mock.patch.object(artifacts, 'read_run_manifest', return_value={'manual_inputs': {'Language':'Français'}}):
                def runner(*args):
                    self.assertEqual(quality_execution.active_language.get(), 'fr')
                    raise fr.FrenchQualityError('t', [fr.FrenchIssue('fr_english_word', 'this')], 'This is bad.')
                with self.assertRaises(fr.FrenchQualityError):
                    quality_execution.execute_step(runner, 'c', 'r', 'outline')
            report = quality_execution.load_diagnostic('c', 'r', 'outline')
            self.assertEqual(report['content'], 'This is bad.')
            self.assertFalse((Path(tmp)/'c/runs/r/outline.md').exists())
            self.assertEqual(quality_execution.active_language.get(), 'en')

    def test_preflight_runs_before_model(self):
        from backend import artifacts
        order = []
        with mock.patch.object(artifacts, 'read_run_manifest', return_value={'manual_inputs': {'Language':'Français'}}), mock.patch.object(quality_execution, 'preflight', side_effect=lambda *a: order.append('preflight')):
            quality_execution.execute_step(lambda *a: order.append('model'), 'c', 'r', 'topic_card')
        self.assertEqual(order, ['preflight','model'])

class RepairSafetyTests(unittest.TestCase):
    def test_repair_preserves_numbers_and_protected_terms(self):
        text = 'This is the best choice for Nature avec 12 résultats.'
        with mock.patch('backend.integrations.anthropic.chat_complete', return_value='[{"old":"12 résultats", "new":"99 résultats"}]'):
            repaired = fr.repair_french_llm(text, [fr.FrenchIssue('fr_english_word', 'this', context=text)], step_label='t', glossary=fr.Glossary())
        self.assertEqual(repaired, text)

    def test_research_canonicalization_keeps_article_headings_french(self):
        self.assertEqual(fr.canonicalize_research_headings('## À retenir\n## Questions fréquentes'), '## À retenir\n## Questions fréquentes')
        self.assertEqual(fr.canonicalize_research_headings('## Vue d’ensemble'), '## Snapshot')

    def test_display_field_replaces_reference_metadata_only(self):
        text = 'SOURCE DISPLAY: une revue scientifique\nJOURNAL NAME: International Journal of Obesity\nTexte français.'
        result = fr.prepare_model_data(text)
        self.assertNotIn('International Journal', result)
        self.assertIn('PUBLICATION : une revue scientifique', result)

    def test_paid_repair_budget_is_shared_between_checks_in_one_step(self):
        from backend import artifacts
        order = []
        def runner(*args):
            for _ in range(2):
                try:
                    fr.enforce_french_artifact('This is the best choice.', step_label='t', attempts=2,
                                              repair=lambda body, issues: order.append('repair') or body)
                except fr.FrenchQualityError:
                    pass
            return 'Texte.'
        with mock.patch.object(artifacts, 'read_run_manifest', return_value={'manual_inputs': {'Language':'Français'}}), mock.patch.object(quality_execution, 'save_diagnostic'):
            quality_execution.execute_step(runner, 'c', 'r', 'outline')
        self.assertEqual(len(order), 2)
