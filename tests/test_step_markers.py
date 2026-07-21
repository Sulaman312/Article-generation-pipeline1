import unittest

from backend.pipeline_steps import ARTICLE_STEP_ORDER
from backend.step_markers import (
    STEP_MARKER_LABELS,
    ensure_step_markers,
    extract_step_body,
    step_markers,
    wrap_step_artifact,
)


class StepMarkersTests(unittest.TestCase):
    def test_every_pipeline_step_has_markers(self):
        for key in ARTICLE_STEP_ORDER:
            self.assertIn(key, STEP_MARKER_LABELS)
            start, end = step_markers(key)
            self.assertTrue(start.startswith("---"))
            self.assertTrue(start.endswith(" START---"))
            self.assertTrue(end.endswith(" END---"))

    def test_research_uses_serp_analysis_markers(self):
        start, end = step_markers("research")
        self.assertEqual(start, "---SERP ANALYSIS START---")
        self.assertEqual(end, "---SERP ANALYSIS END---")

    def test_wrap_collapses_nested_start_markers(self):
        raw = (
            "---PAA FAQ RESEARCH START---\n"
            "---PAA FAQ RESEARCH START---\n"
            "## Primary keyword & intent\n"
            "- PRIMARY KEYWORD: test\n"
            "---PAA FAQ RESEARCH END---\n"
        )
        wrapped = wrap_step_artifact("paa_faq_research", raw)
        self.assertEqual(wrapped.count("---PAA FAQ RESEARCH START---"), 1)
        self.assertEqual(wrapped.count("---PAA FAQ RESEARCH END---"), 1)
        self.assertIn("PRIMARY KEYWORD", wrapped)

    def test_wrap_peels_orphan_start_without_end(self):
        raw = (
            "---PAA FAQ RESEARCH START---\n"
            "## Primary keyword & intent\n"
            "- PRIMARY KEYWORD: test\n"
        )
        wrapped = wrap_step_artifact("paa_faq_research", raw)
        self.assertEqual(wrapped.count("---PAA FAQ RESEARCH START---"), 1)
        self.assertTrue(wrapped.strip().endswith("---PAA FAQ RESEARCH END---"))

    def test_wrap_normalizes_legacy_research_markers(self):
        raw = (
            "---RESEARCH START---\n"
            "## Snapshot\n"
            "- Example gap\n"
            "---RESEARCH END---"
        )
        wrapped = wrap_step_artifact("research", raw)
        self.assertIn("---SERP ANALYSIS START---", wrapped)
        self.assertIn("---SERP ANALYSIS END---", wrapped)
        self.assertNotIn("---RESEARCH START---", wrapped)
        body = extract_step_body("research", wrapped)
        self.assertIn("## Snapshot", body)
        self.assertIn("Example gap", body)

    def test_wrap_adds_markers_when_missing(self):
        wrapped = wrap_step_artifact("outline", "## Section\nContent")
        self.assertTrue(wrapped.startswith("---OUTLINE START---"))
        self.assertTrue(wrapped.rstrip().endswith("---OUTLINE END---"))

    def test_ensure_preserves_fact_check_prefix(self):
        raw = (
            "---PERPLEXITY WEB FACT-CHECK (raw audit trail)---\n"
            "signals\n\n"
            "---FACT CHECK START---\n"
            "body\n"
            "---FACT CHECK END---\n"
        )
        out = ensure_step_markers("fact_check", raw)
        self.assertIn("PERPLEXITY WEB FACT-CHECK", out)
        self.assertIn("---FACT CHECK START---", out)
        self.assertIn("---FACT CHECK END---", out)


if __name__ == "__main__":
    unittest.main()
