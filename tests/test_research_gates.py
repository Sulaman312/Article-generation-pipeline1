from __future__ import annotations

import unittest
from backend import url_verify
from backend.pipeline import STEP_ORDER, STEP_RUNNERS
from backend.pipeline_flow import input_source_for_step
from backend.pipeline_steps import ARTICLE_STEP_ORDER


class UrlVerifyTests(unittest.TestCase):
    def test_extract_http_urls_dedupes(self):
        text = "See https://example.com/a and also https://example.com/a again https://other.test/x."
        urls = url_verify.extract_http_urls(text)
        self.assertEqual(urls, ["https://example.com/a", "https://other.test/x"])

    def test_format_verification_section(self):
        results = [
            url_verify.UrlCheckResult(
                url="https://ok.example", ok=True, status=200, detail="GET ok"
            ),
            url_verify.UrlCheckResult(
                url="https://bad.example", ok=False, status=404, detail="GET HTTP 404"
            ),
        ]
        section = url_verify.format_url_verification_section(results)
        self.assertIn("[OK]", section)
        self.assertIn("[FAIL]", section)
        self.assertIn("https://bad.example", section)


class NewPipelineStepsTests(unittest.TestCase):
    def test_order_combines_source_research_and_folds_supporting(self):
        self.assertEqual(
            ARTICLE_STEP_ORDER.index("source_research"),
            ARTICLE_STEP_ORDER.index("research") + 1,
        )
        self.assertEqual(
            ARTICLE_STEP_ORDER.index("assignment_brief"),
            ARTICLE_STEP_ORDER.index("source_research") + 1,
        )
        self.assertEqual(
            ARTICLE_STEP_ORDER.index("fact_check"),
            ARTICLE_STEP_ORDER.index("draft") + 1,
        )
        self.assertIn("source_research", STEP_RUNNERS)
        for key in (
            "atp_topic_research",
            "paa_faq_research",
            "case_study_research",
            "research_audit",
            "supporting_posts",
        ):
            self.assertNotIn(key, ARTICLE_STEP_ORDER)
            self.assertNotIn(key, STEP_RUNNERS)
        self.assertEqual(STEP_ORDER, ARTICLE_STEP_ORDER)
        self.assertEqual(len(ARTICLE_STEP_ORDER), 10)

    def test_fact_check_uses_draft(self):
        statuses = {name: "done" for name in ARTICLE_STEP_ORDER}
        prev, kind = input_source_for_step(
            "fact_check", statuses, step_order=list(ARTICLE_STEP_ORDER)
        )
        self.assertEqual(kind, "artifact")
        self.assertEqual(prev, "draft")


class CaseStudyMessageTests(unittest.TestCase):
    def test_build_case_study_user_message(self):
        from backend.integrations import perplexity as ppx

        msg = ppx.build_case_study_user_message(
            "TOPIC: vet booking",
            atp_doc="ATP notes",
            research_doc="Gaps",
            serp_digest="SERP",
            keyword_data="vol,0",
            notes="French",
        )
        self.assertIn("TOPIC: vet booking", msg)
        self.assertIn("ATP notes", msg)
        self.assertIn("vol,0", msg)


if __name__ == "__main__":
    unittest.main()
