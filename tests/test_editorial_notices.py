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

    def test_french_faq_notice_uses_localized_heading(self):
        notice = editorial_input.faq_editorial_notice(
            {"Notes": "Write the article in French."}
        )
        self.assertIn("## Questions fréquentes", notice)
        self.assertIn("exactly one", notice.lower())
        self.assertIn("French", notice)

    def test_article_language_from_notes(self):
        self.assertEqual(
            editorial_input.article_language_from_manual(
                {"Notes": "Rédiger en français pour le marché belge."}
            ),
            "fr",
        )
        self.assertEqual(
            editorial_input.article_language_from_manual({"Notes": "English only."}),
            "en",
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

    def test_build_meta_seo_context_fills_prompts(self):
        topic_card = (
            "---TOPIC CARD START---\n"
            "TOPIC: How to measure dogs for sweaters\n"
            "PRIMARY KEYWORD: measure dogs for sweaters\n"
            "CONTENT TYPE: blog\n"
            "---TOPIC CARD END---"
        )
        brief = (
            "---BRIEF START---\n"
            "ARTICLE TITLE: How to measure your dog for a sweater\n"
            "PRIMARY KEYWORD: measure dogs for sweaters\n"
            "---BRIEF END---"
        )
        ctx = editorial_input.build_meta_seo_context(
            topic_card=topic_card,
            assignment_brief=brief,
            final_output="",
            manual=None,
        )
        self.assertEqual(ctx["keyword"], "measure dogs for sweaters")
        self.assertIn("blog page", ctx["page_type"])
        self.assertIn("measure dogs for sweaters", ctx["meta_title_prompt"])
        self.assertIn("50 and 60 characters", ctx["meta_title_prompt"])
        self.assertIn("step-by-step guide", ctx["meta_title_prompt"])
        self.assertIn("120 and 155 characters", ctx["meta_description_prompt"])
        self.assertIn("5 options", ctx["meta_description_prompt"])

    def test_finalize_meta_seo_output_keeps_step_markers(self):
        sample = (
            "---META SEO START---\n"
            "PAGE TYPE: blog page\n"
            "TARGET KEYWORD: test keyword\n"
            "META TITLE OPTIONS (50–60 characters):\n"
            "  1. Example title here (52 characters)\n"
            "---META SEO END---\n"
        )
        out = editorial_input.finalize_meta_seo_output(sample)
        self.assertIn("META SEO START", out)
        self.assertIn("META SEO END", out)
        self.assertIn("PAGE TYPE:", out)
        self.assertIn("META TITLE OPTIONS", out)

    def test_parse_and_inject_meta_seo_into_publishing_metadata(self):
        meta = (
            "PAGE TYPE: how-to guide page\n"
            "TARGET KEYWORD: paperless veterinary clinic\n\n"
            "META TITLE OPTIONS (50–60 characters):\n"
            "  1. Paperless veterinary clinic guide (38 characters)\n"
            "  2. Go paperless in your vet clinic (34 characters)\n\n"
            "META DESCRIPTION OPTIONS (120–155 characters):\n"
            "  1. Ready to run a paperless veterinary clinic? Start here. (57 characters)\n"
            "  2. Learn how to migrate your vet clinic to paperless records. (60 characters)\n"
        )
        parsed = editorial_input.parse_meta_seo_artifact(meta)
        self.assertEqual(len(parsed["title_options"]), 2)
        self.assertEqual(len(parsed["description_options"]), 2)

        final = (
            "---PUBLISHING METADATA START---\n"
            "H1 TITLE: How to Go Paperless\n"
            "H1 CHARACTER COUNT: 24\n"
            "H1 WORD COUNT: 5\n"
            "META DESCRIPTION: old value\n"
            "PRIMARY KEYWORD: paperless veterinary clinic\n"
            "STATUS: READY FOR CMS\n"
            "---PUBLISHING METADATA END---\n"
        )
        merged = editorial_input.inject_meta_seo_into_publishing_metadata(final, meta)
        self.assertIn("META TITLE: Paperless veterinary clinic guide", merged)
        self.assertIn("META TITLE OPTIONS:", merged)
        self.assertIn("META DESCRIPTION OPTIONS:", merged)
        self.assertNotIn("META DESCRIPTION: old value", merged)


if __name__ == "__main__":
    unittest.main()
