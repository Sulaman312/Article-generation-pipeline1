from __future__ import annotations

import unittest

from backend import atp_research
from backend.integrations import perplexity as ppx
from backend.pipeline import STEP_ORDER, STEP_RUNNERS
from backend.pipeline_steps import ARTICLE_STEP_ORDER


SAMPLE_ATP = """
---ATP TOPIC RESEARCH START---

## Seed & demand snapshot
- SEED TOPIC / PRIMARY KEYWORD: online vet appointment
- DEMAND NOTE: Solid how-to demand.

## High-intent shortlist (use in main article + cluster)
1. PHRASE: book online vet appointment | INTENT: transactional | WHY HIGH INTENT: booking | USE IN: main
2. PHRASE: online vet cost | INTENT: commercial | WHY HIGH INTENT: pricing | USE IN: both

## Long-tail keyword bank
- how to schedule a telehealth vet visit | USE IN: main | SOURCE: related search
- best online vet for cats | USE IN: supporting | SOURCE: PAA

## Supporting blog cluster (topical authority plan)

### S1: How much does an online vet visit cost?
- TARGET KEYWORD / ANGLE: cost transparency
- INTERLINK TO MAIN: [vet visit] → main article
- PRIORITY: high

### S2: Online vet vs in-clinic visit
- TARGET KEYWORD / ANGLE: comparison
- PRIORITY: medium

## Keywords to weave into the main article
1. book online vet appointment
2. schedule a telehealth vet visit

LOW SIGNAL TOPIC — limited verifiable question/demand evidence; keep cluster small.

---ATP TOPIC RESEARCH END---
"""


class AtpTopicResearchTests(unittest.TestCase):
    def test_step_is_registered_between_research_and_paa(self):
        self.assertIn("atp_topic_research", ARTICLE_STEP_ORDER)
        self.assertEqual(
            ARTICLE_STEP_ORDER.index("atp_topic_research"),
            ARTICLE_STEP_ORDER.index("research") + 1,
        )
        self.assertEqual(
            ARTICLE_STEP_ORDER.index("atp_topic_research") + 1,
            ARTICLE_STEP_ORDER.index("paa_faq_research"),
        )
        self.assertIn("atp_topic_research", STEP_RUNNERS)
        self.assertEqual(STEP_ORDER, ARTICLE_STEP_ORDER)

    def test_extract_high_intent_and_supporting(self):
        high = atp_research.extract_high_intent_phrases(SAMPLE_ATP)
        self.assertEqual(len(high), 2)
        self.assertIn("book online vet", high[0])
        titles = atp_research.extract_supporting_titles(SAMPLE_ATP)
        self.assertEqual(len(titles), 2)
        self.assertIn("online vet visit cost", titles[0].lower())

    def test_format_bank_mentions_low_signal(self):
        block = atp_research.format_atp_bank_for_prompt(SAMPLE_ATP)
        self.assertIn("High-intent phrases", block)
        self.assertIn("Supporting posts", block)
        self.assertIn("LOW SIGNAL", block)

    def test_build_atp_user_message_includes_blocks(self):
        msg = ppx.build_atp_topic_user_message(
            "TOPIC: online vet",
            serp_digest="SERP notes",
            research_doc="Gaps",
            keyword_data="query,volume\nonline vet,100",
            notes="Write in French",
        )
        self.assertIn("---TOPIC CARD---", msg)
        self.assertIn("SERP notes", msg)
        self.assertIn("Gaps", msg)
        self.assertIn("online vet,100", msg)
        self.assertIn("Write in French", msg)
        self.assertIn("AnswerThePublic-style", msg)


if __name__ == "__main__":
    unittest.main()
