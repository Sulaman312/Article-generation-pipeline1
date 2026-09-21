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
        self.assertEqual(trimmed.count("\n") + 1, len(sentences))

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


if __name__ == "__main__":
    unittest.main()
