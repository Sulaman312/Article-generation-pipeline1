from __future__ import annotations

import unittest

from backend import faq_schema


def _sample_with_faqs(n: int) -> str:
    lines = ["## Intro", "Body text.", "", "## Frequently Asked Questions", ""]
    for i in range(1, n + 1):
        lines.extend([f"### Question {i}?", "", f"Answer {i} here.", ""])
    lines.extend(["## Next steps", "Closing prose."])
    return "\n".join(lines)


class FaqSchemaTests(unittest.TestCase):
    def test_extract_faq_pairs_counts_h3s(self):
        text = _sample_with_faqs(6)
        self.assertEqual(len(faq_schema.extract_faq_pairs(text)), 6)

    def test_extract_french_faq_heading(self):
        text = (
            "## Intro\n\nBody.\n\n"
            "## Questions fréquentes\n\n"
            "### Puis-je numériser des dossiers très anciens?\n\n"
            "Oui, avec précautions.\n\n"
            "### Comment gérer la résistance?\n\n"
            "Par la formation.\n"
        )
        pairs = faq_schema.extract_faq_pairs(text)
        self.assertEqual(len(pairs), 2)
        self.assertIn("numériser", pairs[0][0])

    def test_extract_bold_questions_under_faq(self):
        text = (
            "## FAQ\n\n"
            "**Can I digitize old records?**\n\n"
            "Yes, with care.\n\n"
            "**How to train the team?**\n\n"
            "Use phased training.\n"
        )
        pairs = faq_schema.extract_faq_pairs(text)
        self.assertEqual(len(pairs), 2)

    def test_ensure_faq_from_reference_restores_dropped_items(self):
        reference = _sample_with_faqs(6)
        reduced = _sample_with_faqs(2)
        restored = faq_schema.ensure_faq_from_reference(reduced, reference)
        self.assertEqual(len(faq_schema.extract_faq_pairs(restored)), 6)

    def test_consolidate_faq_sections_keeps_french_only(self):
        bilingual = (
            "## Intro\n\nBody.\n\n"
            "## Questions fréquentes\n\n"
            "### Combien coûte la numérisation?\n\n"
            "Les tarifs varient selon le volume.\n\n"
            "### Faut-il former le personnel?\n\n"
            "Oui, une courte formation suffit.\n\n"
            "## Frequently Asked Questions\n\n"
            "### How much does digitization cost?\n\n"
            "Pricing depends on volume.\n\n"
            "### Do staff need training?\n\n"
            "Yes, a short training is enough.\n"
        )
        consolidated = faq_schema.consolidate_faq_sections(
            bilingual,
            heading="## Questions fréquentes",
            lang="fr",
        )
        self.assertIn("## Questions fréquentes", consolidated)
        self.assertNotIn("Frequently Asked Questions", consolidated)
        pairs = faq_schema.extract_faq_pairs(consolidated)
        self.assertEqual(len(pairs), 2)
        self.assertIn("numérisation", pairs[0][0])

    def test_trim_faq_answer_caps_sentences_and_words(self):
        long = (
            "First sentence adds a lot of extra detail about the process and timeline. "
            "Second sentence keeps going with more background the reader does not need here. "
            "Third sentence is still useful for a direct answer. "
            "Fourth sentence wraps the point. "
            "Fifth sentence must be dropped. "
            "Sixth sentence is also extra."
        )
        trimmed = faq_schema.trim_faq_answer(long)
        sentences = faq_schema.split_faq_sentences(trimmed)
        self.assertLessEqual(len(sentences), faq_schema.FAQ_ANSWER_MAX_SENTENCES)
        self.assertLessEqual(
            faq_schema.faq_answer_word_count(trimmed),
            faq_schema.FAQ_ANSWER_MAX_WORDS,
        )
        self.assertNotIn("\n", trimmed)

    def test_trim_faq_answer_flattens_bullets_into_prose(self):
        listed = (
            "- Start in the clinic portal and pick a telehealth slot.\n"
            "- Upload recent photos before the call begins.\n"
            "- Join a few minutes early so audio works.\n"
            "1. Have the medication list ready for the clinician."
        )
        trimmed = faq_schema.trim_faq_answer(listed)
        self.assertNotIn("\n", trimmed)
        self.assertFalse(trimmed.startswith("-"))
        self.assertNotIn("- Start", trimmed)
        self.assertGreaterEqual(
            len(faq_schema.split_faq_sentences(trimmed)),
            faq_schema.FAQ_ANSWER_MIN_SENTENCES,
        )

    def test_enforce_faq_answer_length_keeps_body_word_count(self):
        body = (
            "# Title\n\n## Key takeaways\n\n"
            "Useful takeaway one for the reader today.\n\n"
            "## Main section\n\n"
            "This body section holds the article length with several sentences of substance. "
            "Another sentence keeps the section useful for the reader.\n\n"
            "## Frequently Asked Questions\n\n"
            "### What is this?\n\n"
            "One long answer sentence that goes on with unnecessary extra words about the topic. "
            "Two continues the same idea with even more padding the reader does not need. "
            "Three is still here. Four stays. Five should go. Six should also go.\n"
        )
        before = faq_schema.markdown_for_word_count(body)
        out = faq_schema.enforce_faq_answer_length(body)
        after = faq_schema.markdown_for_word_count(out)
        self.assertEqual(before, after)
        pairs = faq_schema.extract_faq_pairs(out)
        self.assertEqual(len(pairs), 1)
        self.assertLessEqual(
            faq_schema.faq_answer_word_count(pairs[0][1]),
            faq_schema.FAQ_ANSWER_MAX_WORDS,
        )

    def test_format_faq_block_uses_localized_heading(self):
        block = faq_schema.format_faq_block(
            [("Question?", "Answer.")],
            heading="## Questions fréquentes",
        )
        self.assertTrue(block.startswith("## Questions fréquentes"))


class FactCorrectionTests(unittest.TestCase):
    def test_parse_and_apply_targeted_edit(self):
        draft = (
            "# Title\n\n"
            "Many clinics report faster intake after switching tools.\n"
            "73% of marketers say automation doubles revenue overnight.\n"
            "Training still matters for the front desk.\n"
        )
        model_out = (
            "---FACT CHECK START---\n"
            "---FACT CHECK REPORT START---\n"
            "OVERALL ASSESSMENT: MINOR ISSUES\n"
            "---FACT CHECK REPORT END---\n"
            "---CORRECTIONS START---\n"
            "[\n"
            "  {\n"
            '    "claim": "73% of marketers say automation doubles revenue overnight.",\n'
            '    "issue": "fabricated statistic",\n'
            '    "fix": "Some teams report faster follow-up after they automate intake.",\n'
            '    "action": "corrected"\n'
            "  }\n"
            "]\n"
            "---CORRECTIONS END---\n"
            "---FACT CHECK END---\n"
        )
        patched, corrections = faq_schema.resolve_fact_checked_article(draft, model_out)
        self.assertEqual(len(corrections), 1)
        self.assertIn("Some teams report faster follow-up", patched)
        self.assertNotIn("73%", patched)
        self.assertIn("Training still matters", patched)

    def test_flagged_items_are_not_applied(self):
        draft = "Clinics in Lyon processed 12,000 files last year without extra staff.\n"
        model_out = (
            "---CORRECTIONS START---\n"
            '[{"claim": "Clinics in Lyon processed 12,000 files last year without extra staff.",'
            ' "issue": "unverifiable claim", "fix": "", "action": "flagged"}]\n'
            "---CORRECTIONS END---\n"
        )
        patched, corrections = faq_schema.resolve_fact_checked_article(draft, model_out)
        self.assertEqual(len(corrections), 1)
        self.assertEqual(patched.strip(), draft.strip())

    def test_removed_claim_is_deleted(self):
        draft = (
            "Opening sentence stays in the article for readers.\n"
            "73% of marketers say automation doubles revenue overnight.\n"
            "Closing sentence also stays.\n"
        )
        corrections = [
            {
                "claim": "73% of marketers say automation doubles revenue overnight.",
                "issue": "fabricated statistic",
                "fix": "",
                "action": "removed",
            }
        ]
        patched = faq_schema.apply_fact_corrections(draft, corrections)
        self.assertNotIn("73%", patched)
        self.assertIn("Opening sentence stays", patched)
        self.assertIn("Closing sentence also stays", patched)

    def test_empty_corrections_keep_draft(self):
        draft = "# Title\n\nBody sentence remains untouched here.\n"
        model_out = (
            "---CORRECTIONS START---\n[]\n---CORRECTIONS END---\n"
        )
        patched, corrections = faq_schema.resolve_fact_checked_article(draft, model_out)
        self.assertEqual(corrections, [])
        self.assertEqual(patched, draft.strip())

    def test_legacy_corrected_article_fallback(self):
        draft = "# Old\n\nOriginal sentence in the draft body.\n"
        rewritten = "# New\n\nReplacement sentence from an older fact-check rewrite.\n"
        model_out = (
            f"{faq_schema.CORRECTED_ARTICLE_START}\n{rewritten}"
            f"{faq_schema.CORRECTED_ARTICLE_END}\n"
        )
        patched, corrections = faq_schema.resolve_fact_checked_article(draft, model_out)
        self.assertEqual(corrections, [])
        self.assertIn("Replacement sentence", patched)

    def test_embed_keeps_report_and_patched_draft(self):
        report = (
            "---FACT CHECK START---\n"
            "OVERALL ASSESSMENT: CLEAN\n"
            "---FACT CHECK END---\n"
        )
        article = "# Title\n\nPatched body sentence for later steps.\n"
        out = faq_schema.embed_corrected_article(report, article, [])
        self.assertIn("OVERALL ASSESSMENT: CLEAN", out)
        self.assertIn(faq_schema.CORRECTIONS_START, out)
        self.assertEqual(
            faq_schema.extract_corrected_article_body(out),
            article.strip(),
        )


if __name__ == "__main__":
    unittest.main()
