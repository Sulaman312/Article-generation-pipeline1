from __future__ import annotations

import unittest

from backend import paa_faq
from backend.integrations import perplexity as ppx
from backend.pipeline import STEP_ORDER, STEP_RUNNERS
from backend.pipeline_steps import ARTICLE_STEP_ORDER


SAMPLE_PAA = """
---PAA FAQ RESEARCH START---

## Recommended FAQ bank (use these in the article)
LOW SIGNAL TOPIC — only 3 questions had verifiable demand evidence.

### Q1: How do I book an online vet appointment?
- INTENT CLUSTER: how-to
- SOURCE SIGNAL: PAA
- CITATION: https://example.com/book

### Q2: Combien coûte une consultation en ligne?
- INTENT CLUSTER: cost
- SOURCE SIGNAL: INFERRED
- CITATION:

### Q3: Is telehealth available on weekends?
- INTENT CLUSTER: timeline
- SOURCE SIGNAL: related_questions API
- CITATION: Is telehealth available on weekends?

## Questions to skip (or fold into body, not FAQ)
- What is a vet?

## Language
- FAQ LANGUAGE: en

---PAA FAQ RESEARCH END---
"""


class PaaFaqTests(unittest.TestCase):
    def test_step_is_registered_after_research(self):
        self.assertIn("paa_faq_research", ARTICLE_STEP_ORDER)
        self.assertEqual(
            ARTICLE_STEP_ORDER.index("paa_faq_research"),
            ARTICLE_STEP_ORDER.index("atp_topic_research") + 1,
        )
        self.assertEqual(
            ARTICLE_STEP_ORDER.index("paa_faq_research") + 1,
            ARTICLE_STEP_ORDER.index("case_study_research"),
        )
        self.assertIn("paa_faq_research", STEP_RUNNERS)
        self.assertEqual(STEP_ORDER, ARTICLE_STEP_ORDER)

    def test_extract_recommended_questions(self):
        qs = paa_faq.extract_recommended_faq_questions(SAMPLE_PAA)
        self.assertEqual(len(qs), 3)
        self.assertIn("book an online vet", qs[0])
        self.assertIn("consultation", qs[1])

    def test_format_faq_bank_mentions_low_signal(self):
        block = paa_faq.format_faq_bank_for_prompt(SAMPLE_PAA)
        self.assertIn("1. How do I book", block)
        self.assertIn("LOW SIGNAL", block)

    def test_related_questions_api_section_replaced(self):
        body = (
            "## Recommended FAQ bank\n\n"
            "### Q1: Demo?\n\n"
            "## Related questions (API)\n"
            "- fake invented\n\n"
            "## Language\n"
            "- FAQ LANGUAGE: en\n"
        )
        out = ppx._ensure_related_questions_api_section(
            body, ["Real API question one?", "Real API question two?"]
        )
        self.assertIn("- Real API question one?", out)
        self.assertIn("- Real API question two?", out)
        self.assertNotIn("fake invented", out)

    def test_build_paa_user_message_includes_blocks(self):
        msg = ppx.build_paa_faq_user_message(
            "TOPIC: vet booking",
            serp_digest="SERP notes",
            research_doc="Gaps",
            keyword_data="query,volume\nonline vet,0",
            notes="Write in French",
        )
        self.assertIn("---TOPIC CARD---", msg)
        self.assertIn("SERP notes", msg)
        self.assertIn("Gaps", msg)
        self.assertIn("online vet,0", msg)
        self.assertIn("Write in French", msg)


if __name__ == "__main__":
    unittest.main()
