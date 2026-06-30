from __future__ import annotations

import unittest

from backend import editorial_input, prompts


class EditorialNoticeTests(unittest.TestCase):
    def test_notes_are_preserved_as_mandatory_constraints(self):
        notice = editorial_input.notes_editorial_notice(
            {"Notes": "Write the article in French and use a restrained CTA."}
        )
        self.assertIn("MANDATORY", notice)
        self.assertIn("Write the article in French", notice)
        self.assertIn("restrained CTA", notice)

    def test_empty_notes_do_not_add_noise(self):
        self.assertEqual(editorial_input.notes_editorial_notice({}), "")
        self.assertEqual(editorial_input.notes_editorial_notice(None), "")

    def test_keyword_contract_is_consistent(self):
        notice = editorial_input.seo_readability_notice()
        self.assertIn("once in the first 100 body words", notice)
        self.assertIn("do not repeat that exact phrase", notice)
        self.assertNotIn("once in H1 only", notice)

        combined_prompts = "\n".join(
            (
                prompts.TOPIC_CARD_PROMPT,
                prompts.ASSIGNMENT_BRIEF_PROMPT,
                prompts.DRAFT_PROMPT,
                prompts.FINAL_OUTPUT_PROMPT,
            )
        )
        self.assertNotIn("once in H1 only", combined_prompts)
        self.assertNotIn("at most once in the full article", combined_prompts)

    def test_with_writing_format_guidelines_appends_canonical_block(self):
        base = "You are an editor."
        combined = prompts.with_writing_format_guidelines(base)
        self.assertIn("WRITING FORMAT GUIDELINES (canonical", combined)
        self.assertIn("No em dashes", combined)
        self.assertEqual(
            prompts.with_writing_format_guidelines(combined).rstrip(),
            combined.rstrip(),
        )

    def test_writing_format_guidelines_notice(self):
        notice = editorial_input.writing_format_guidelines_notice()
        self.assertIn("system prompt", notice.lower())
        self.assertIn("automatically lints", notice.lower())

    def test_outline_format_notice_emphasizes_headings(self):
        notice = editorial_input.outline_format_guidelines_notice()
        self.assertIn("sentence case", notice.lower())
        self.assertIn("Conclusion", notice)

    def test_cta_format_notice(self):
        notice = editorial_input.cta_format_guidelines_notice()
        self.assertIn("/book-a-demo/", notice)
        self.assertIn("auto-checked", notice.lower())


if __name__ == "__main__":
    unittest.main()
