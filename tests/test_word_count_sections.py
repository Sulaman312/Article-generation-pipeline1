from __future__ import annotations

import unittest

from backend import editorial_input


class WordCountSectionTests(unittest.TestCase):
    def test_split_and_reassemble_preserves_h2s(self):
        md = (
            "# Title\n\nIntro.\n\n"
            "## One\n\nAlpha beta gamma.\n\n"
            "## Questions fréquentes\n\n"
            "### Q?\n\nA.\n\n"
            "## Two\n\nDelta epsilon.\n"
        )
        sections = editorial_input.split_article_h2_sections(md)
        self.assertGreaterEqual(len(sections), 3)
        faq = [s for s in sections if s["is_faq"]]
        self.assertEqual(len(faq), 1)
        self.assertEqual(faq[0]["words"], 0)
        rebuilt = editorial_input.reassemble_h2_sections(sections)
        self.assertIn("## One", rebuilt)
        self.assertIn("## Two", rebuilt)
        self.assertIn("Questions fréquentes", rebuilt)

    def test_allocate_caps_sum_near_high(self):
        md = (
            "## A\n\n" + ("word " * 400) + "\n\n"
            "## B\n\n" + ("word " * 400) + "\n"
        )
        sections = editorial_input.split_article_h2_sections(md)
        caps = editorial_input.allocate_section_word_caps(sections, 800)
        _low, high = editorial_input.word_count_bounds(800)
        self.assertLessEqual(sum(caps), high + 5)
        self.assertTrue(all(c >= 50 for c in caps if c))

    def test_outline_budget_guidance_includes_h2s(self):
        outline = (
            "---OUTLINE START---\n"
            "H2: Setup\n"
            "  WORD COUNT: 200–250 words\n"
            "H2: Steps\n"
            "  WORD COUNT: 400–450 words\n"
            "---OUTLINE END---\n"
        )
        text = editorial_input.draft_section_budget_guidance(outline, 2200)
        self.assertIn("Setup", text)
        self.assertIn("Steps", text)
        self.assertIn("2,100", text)


if __name__ == "__main__":
    unittest.main()
