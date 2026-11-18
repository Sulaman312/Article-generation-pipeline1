from __future__ import annotations
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from backend import fact_check_contract as fc, french_language as fr, faq_schema, config, quality_execution
from backend import fact_check_sources as sources, draft_preflight, prompt_cache
from backend.job_control import JobCancelled

DRAFT = '# Titre\n\n## Preuves\n\nCette étude comprend deux groupes de 54 personnes.\n'
SOURCE_URL = 'https://pubmed.ncbi.nlm.nih.gov/12345/'
SOURCE = 'A total of 54 participants were assigned to two diets.'


def report(**updates):
    item = dict(section='Preuves', paragraph=1, sentence=1,
                anchor='Cette étude comprend deux groupes de', claim='deux groupes de 54 personnes',
                issue_type='unverifiable claim', action='flagged', fix='',
                explanation='La source doit être vérifiée.', source_url='', evidence_quote='')
    item.update(updates)
    return dict(assessment='MINOR ISSUES', company_review='Aucun point à vérifier.', issues=[item])


class ContractTests(unittest.TestCase):
    def test_schema_rejects_missing_keys_wrong_types_and_unknown_actions(self):
        for change in ({'action': 'publish'}, {'paragraph': True}, {'sentence': 0}, {'fix': 4}):
            with self.subTest(change=change), self.assertRaises(fc.FactCheckError):
                fc.parse_report(json.dumps(report(**change)))
        invalid = report()
        del invalid['issues'][0]['anchor']
        with self.assertRaises(fc.FactCheckError):
            fc.parse_report(json.dumps(invalid))

    def test_diagnostic_ellipsis_never_enters_french_publication_check(self):
        for quote in ('[...]', '[…]', '…'):
            data = report(explanation=f'La source {quote} nécessite une revue humaine.')
            generate = Mock(return_value=json.dumps(data))
            validated, article = fc.run_fact_check(generate, DRAFT, lang='fr')
            self.assertEqual(article, DRAFT)
            generate.assert_called_once()
            rendered, _ = fc.render_report(validated)
            self.assertNotIn('[…]', rendered)
            self.assertNotIn('[...]', rendered)

    def test_all_three_report_fixtures_reproduce_old_false_failure(self):
        for path in (Path(__file__).parent / 'fixtures/fact_check').glob('*.txt'):
            text = path.read_text(encoding='utf-8')
            self.assertTrue(any(i.code == 'fr_placeholder' for i in fr.scan_french(text, english=False, banned=False, spelling=False)), path)
            # The reports remain diagnostic inputs, not something to rewrite as article copy.
            data = report(explanation=text[:2000])
            generate = Mock(return_value=json.dumps(data))
            _, article = fc.run_fact_check(generate, DRAFT, lang='fr')
            self.assertEqual(article, DRAFT)
            self.assertEqual(generate.call_count, 1)

    def test_bad_claims_rejected_without_rewriting_evidence(self):
        for claim in ('deux groupes […] personnes', 'deux groupes [...] personnes',
                      'deux groupes … personnes', 'un groupe absent du brouillon',
                      'Cette étude comprend deux groupes de 54 personnes avec une autre phrase inventée'):
            with self.subTest(claim=claim), self.assertRaises(fc.FactCheckError):
                fc.validate_report(report(claim=claim, action='removed'), DRAFT, lang='fr')

    def test_flagged_claim_is_repaired_in_code_not_rejected(self):
        for claim in ('deux groupes […] personnes', 'deux groupes [...] personnes', 'deux groupes … personnes',
                      'un groupe absent du brouillon', 'Cette étude comprend deux groupes de 54 personnes avec une autre phrase'):
            with self.subTest(claim=claim):
                data, edits = fc.validate_report(report(claim=claim), DRAFT, lang='fr')
                self.assertEqual(edits, [])
                self.assertEqual(data['issues'][0]['claim'], 'Cette étude comprend deux groupes de 54 personnes.')
                self.assertNotRegex(data['issues'][0]['claim'], r'\[|…|\.\.\.')

    def test_real_placeholder_in_fix_still_blocks(self):
        for fix in ('[INSERT SOURCE]', '[…]', '[...]', '{{effectif}}'):
            with self.subTest(fix=fix), self.assertRaises(fc.FactCheckError):
                fc.validate_report(report(action='corrected', fix=fix), DRAFT, lang='fr')

    def test_real_article_placeholder_still_blocks(self):
        clean = json.dumps(dict(assessment='CLEAN', company_review='', issues=[]))
        with self.assertRaises(fc.FactCheckError):
            fc.run_fact_check(lambda _: clean, DRAFT + '\n[...]\n', lang='fr', retries=0)

    def test_numeric_fix_requires_supplied_source_and_exact_quote(self):
        data, edits = fc.validate_report(report(action='corrected', fix='54 personnes au total'), DRAFT, lang='fr')
        self.assertEqual((data['issues'][0]['action'], data['issues'][0]['fix'], edits), ('flagged', '', []))
        data, edits = fc.validate_report(report(action='corrected', fix='54 personnes au total',
                                              source_url=SOURCE_URL, evidence_quote='A total of 54 participants'),
                                         DRAFT, lang='fr', source_texts={SOURCE_URL: SOURCE})
        self.assertIn('comprend 54 personnes au total.', fc.apply_edits(DRAFT, edits))

    def test_location_selects_correct_duplicate_claim(self):
        draft = DRAFT + '\n## Autre section\n\nCette étude comprend deux groupes de 54 personnes.\n'
        data, edits = fc.validate_report(report(section='Autre section', paragraph=2, action='corrected',
                                               fix='un effectif à confirmer'), draft, lang='fr')
        article = fc.apply_edits(draft, edits)
        self.assertEqual(article.count('deux groupes de 54 personnes'), 1)
        self.assertIn('## Preuves\n\nCette étude comprend deux groupes de 54 personnes.', article)

    def test_bad_location_anchor_and_overlap_block(self):
        for fields in ({'paragraph': 3}, {'section': 'Inventé'}, {'sentence': 2}):
            with self.subTest(fields=fields), self.assertRaises(fc.FactCheckError):
                fc.validate_report(report(**fields), DRAFT, lang='fr')
        data = report(action='removed')
        data['issues'].append(copy.deepcopy(data['issues'][0]))
        with self.assertRaises(fc.FactCheckError):
            fc.validate_report(data, DRAFT, lang='fr')

    def test_anchor_is_derived_from_the_draft_not_trusted_from_the_model(self):
        data, _ = fc.validate_report(report(anchor='Cette étude'), DRAFT, lang='fr')
        self.assertEqual(data['issues'][0]['anchor'], 'Cette étude comprend deux groupes de')

    def test_bad_json_is_repaired_once_with_exact_feedback(self):
        bad = report(claim='deux groupes […] personnes', action='removed')
        generate = Mock(side_effect=[json.dumps(bad), json.dumps(report())])
        fc.run_fact_check(generate, DRAFT, lang='fr')
        self.assertEqual(generate.call_count, 2)
        self.assertIn('issues[0].claim', generate.call_args[0][0])
        self.assertIn('PREVIOUS JSON', generate.call_args[0][0])

    def test_bad_schema_is_bounded_to_two_retries(self):
        generate = Mock(return_value='{"issues":')
        with self.assertRaises(fc.FactCheckError) as cm:
            fc.run_fact_check(generate, DRAFT, lang='fr', retries=50)
        self.assertEqual(generate.call_count, 3)
        self.assertEqual(cm.exception.text, '{"issues":')

    def test_cancellation_never_retried(self):
        generate = Mock(side_effect=JobCancelled())
        with self.assertRaises(JobCancelled):
            fc.run_fact_check(generate, DRAFT, lang='fr')
        generate.assert_called_once()

    def test_number_evidence_is_not_invented(self):
        data, edits = fc.validate_report(report(action='corrected', fix='27 personnes par groupe', source_url=SOURCE_URL,
                                                evidence_quote='27 participants per group'), DRAFT, lang='fr', source_texts={SOURCE_URL: SOURCE})
        self.assertEqual((data['issues'][0]['action'], data['issues'][0]['evidence_quote'], edits), ('flagged', '', []))

    def test_evidence_match_ignores_case_spacing_quotes_and_wrong_url(self):
        data, edits = fc.validate_report(report(action='corrected', fix='54 personnes au total',
                                                source_url='https://autre.example/', evidence_quote='a  TOTAL of 54\u00a0participants'),
                                         DRAFT, lang='fr', source_texts={SOURCE_URL: SOURCE})
        self.assertEqual(data['issues'][0]['source_url'], SOURCE_URL)
        self.assertIn('comprend 54 personnes au total.', fc.apply_edits(DRAFT, edits))

    def test_unverifiable_evidence_is_dropped_not_fatal(self):
        data, _ = fc.validate_report(report(source_url=SOURCE_URL, evidence_quote='phrase inventée'), DRAFT, lang='fr',
                                     source_texts={SOURCE_URL: SOURCE})
        self.assertEqual(data['issues'][0]['evidence_quote'], '')
        self.assertIn('à vérifier', data['issues'][0]['explanation'])


class DraftTests(unittest.TestCase):
    def test_initials_are_not_sentence_boundaries(self):
        text = 'Cette approche vient de Herbert M. Shelton. Elle doit être examinée.'
        self.assertEqual(faq_schema.split_faq_sentences(text), ['Cette approche vient de Herbert M. Shelton.', 'Elle doit être examinée.'])

    def test_faq_never_cuts_name_at_fourth_sentence(self):
        text = 'Un repas suffit. Une méthode existe. La prudence importe. Cette approche vient de Herbert M. Shelton. Une autre phrase.'
        result = faq_schema.trim_faq_answer(text)
        self.assertTrue(result.endswith('Herbert M. Shelton.'))

    def test_long_two_sentence_answer_is_never_clipped_mid_sentence(self):
        first = 'Une phrase ' + 'utile ' * 40 + 'se termine ici.'
        second = 'Une autre ' + 'précision ' * 40 + 'concerne Herbert M. Shelton.'
        result = faq_schema.trim_faq_answer(first + ' ' + second)
        self.assertTrue(result.endswith('Herbert M. Shelton.'))
        self.assertEqual(len(faq_schema.split_faq_sentences(result)), 2)

    def test_preflight_flags_dangling_name_missing_subject_and_numeric_mismatch(self):
        draft = '# Titre\n\nCette approche a été formalisée par Herbert M.\n\nPublié dans une revue, a comparé les régimes.\n\nDeux groupes de 54 personnes ont participé [à cet essai](https://pubmed.ncbi.nlm.nih.gov/12345/).\n'
        findings = draft_preflight.check_draft(draft, {SOURCE_URL:'A total of 27 participants.'})
        self.assertTrue({'dangling_initial', 'possible_missing_subject', 'numeric_source_mismatch'} <= {i['code'] for i in findings})
        self.assertTrue(all(i['severity'] == 'warning' for i in findings))

    def test_french_fact_check_input_keeps_draft_verbatim(self):
        from backend import prompts
        cached = prompt_cache.build_cached_prompt(client_id='c', run_id='r', step_prompt=prompts.FACT_CHECK_PROMPT,
                                                   unique_suffix='Le terme hero est cité exactement.', lang='fr', step_name='fact_check', step_label='t')
        self.assertIn('Le terme hero est cité exactement.', cached.unique_text)


class SourceTests(unittest.TestCase):
    def test_only_pubmed_hosts_and_ids_are_eligible(self):
        value = 'https://pubmed.ncbi.nlm.nih.gov/123/ https://www.ncbi.nlm.nih.gov/pubmed/456 https://example.org/789 https://pubmed.ncbi.nlm.nih.gov.evil.org/999/'
        self.assertEqual(sources.pubmed_ids(value), ['123', '456'])

    def test_abstract_is_fetched_from_fixed_ncbi_endpoint(self):
        xml = b'<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article><ArticleTitle>A study</ArticleTitle><Abstract><AbstractText Label="RESULTS">54 subjects</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>'
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = xml
        with patch.object(sources, 'urlopen', return_value=response) as request:
            result = sources.fetch_pubmed(['123'])
        self.assertEqual(result['https://pubmed.ncbi.nlm.nih.gov/123/'], 'A study\nRESULTS: 54 subjects')
        self.assertTrue(request.call_args[0][0].full_url.startswith('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?'))

class StepIntegrationTests(unittest.TestCase):
    def test_step_skips_report_language_gate_but_checks_article_and_saves_json(self):
        import tempfile
        from backend import artifacts, steps
        with tempfile.TemporaryDirectory() as root, patch.object(config, 'CLIENTS_DIR', Path(root)), patch.object(config, 'PERPLEXITY_API_KEY', None):
            artifacts.save_run_manifest('c', 'r', 'Sujet', {'draft':'done'}, manual_inputs={'Language':'Français'})
            artifacts.save_artifact('c', 'r', 'draft', DRAFT)
            actual_draft = artifacts.load_artifact('c', 'r', 'draft')
            with patch('backend.fact_check_sources.source_pack', return_value=('PRIMARY SOURCE TEXT', {SOURCE_URL: SOURCE})) as evidence, patch('backend.integrations.anthropic.chat_complete', return_value=json.dumps(report(explanation='La source […] nécessite une revue.'))) as model:
                result = steps.run_step_6('c', 'r')
            evidence.assert_called_once()
            model.assert_called_once()
            self.assertIn('PRIMARY SOURCE TEXT', model.call_args[0][0].unique_text)
            self.assertEqual(faq_schema.extract_corrected_article_body(result), DRAFT.strip())
            self.assertTrue((Path(root)/'c/runs/r/fact_check_report.json').exists())
            self.assertTrue((Path(root)/'c/runs/r/draft_preflight.json').exists())

    def test_source_pack_caches_success_and_marks_missing_abstract(self):
        import tempfile
        from backend import artifacts
        draft = DRAFT + '\n' + SOURCE_URL
        with tempfile.TemporaryDirectory() as root, patch.object(config, 'CLIENTS_DIR', Path(root)), patch.object(sources, 'fetch_pubmed', return_value={SOURCE_URL: SOURCE}) as fetch:
            first, _ = sources.source_pack('c', 'r', draft)
            second, _ = sources.source_pack('c', 'r', draft)
            fetch.assert_called_once()
            self.assertIn(SOURCE, second)
        with tempfile.TemporaryDirectory() as root, patch.object(config, 'CLIENTS_DIR', Path(root)), patch.object(sources, 'fetch_pubmed', side_effect=OSError('unavailable')):
            text, mapping = sources.source_pack('c', 'r', draft)
            self.assertEqual(mapping, {})
            self.assertIn('SOURCE TEXT UNAVAILABLE', text)

class AdditionalSourceTests(unittest.TestCase):
    def test_group_count_vs_total_is_flagged_even_when_number_matches_source(self):
        text = 'Deux groupes de 54 personnes ont participé [à cet essai](https://pubmed.ncbi.nlm.nih.gov/12345/).'
        findings = draft_preflight.check_draft(text, {SOURCE_URL: SOURCE})
        self.assertIn('group_total_scope', [f['code'] for f in findings])

    def test_provided_non_pubmed_primary_text_is_available_for_numeric_evidence(self):
        import tempfile
        from backend import artifacts
        supplied = 'SOURCE URL: https://agency.example/study\nA total of 54 participants were assigned to two diets.'
        with tempfile.TemporaryDirectory() as root, patch.object(config, 'CLIENTS_DIR', Path(root)), patch.object(artifacts, 'read_context_file', return_value=supplied):
            text, mapping = sources.source_pack('c', 'r', DRAFT)
            self.assertEqual(mapping['https://agency.example/study'], SOURCE)

class NumberFormattingTests(unittest.TestCase):
    def test_french_decimal_is_not_converted_to_a_larger_integer(self):
        self.assertEqual(fc.numbers('1,5 kg'), {'1.5'})
        self.assertEqual(fc.numbers('1 100 kcal and 1,100 kcal'), {'1100'})

class EditBoundaryTests(unittest.TestCase):
    def test_partial_words_and_article_rewrites_are_rejected(self):
        for update in ({'claim':'person', 'action':'removed'},
                       {'claim':'.', 'action':'removed'},
                       {'action':'corrected', 'fix':'## Nouvelle section\n\nUn autre article.'}):
            with self.subTest(update=update), self.assertRaises(fc.FactCheckError):
                fc.validate_report(report(**update), DRAFT, lang='fr')
