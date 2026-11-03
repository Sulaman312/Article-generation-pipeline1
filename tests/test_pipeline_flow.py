"""Pipeline input resolution — meta SEO is not final_output article input."""

import unittest

from backend.pipeline_flow import can_run_step, input_source_for_step
from backend.pipeline_steps import ARTICLE_STEP_ORDER


class PipelineFlowTests(unittest.TestCase):
    def test_final_output_skips_meta_seo(self):
        statuses = {name: "done" for name in ARTICLE_STEP_ORDER}
        statuses["final_output"] = "pending"
        src, kind = input_source_for_step(
            "final_output", statuses, step_order=list(ARTICLE_STEP_ORDER)
        )
        self.assertEqual(kind, "artifact")
        self.assertEqual(src, "fact_check")

    def test_final_output_when_meta_pending(self):
        statuses = {name: "done" for name in ARTICLE_STEP_ORDER}
        statuses["meta_seo"] = "pending"
        statuses["final_output"] = "pending"
        src, kind = input_source_for_step(
            "final_output", statuses, step_order=list(ARTICLE_STEP_ORDER)
        )
        self.assertEqual(kind, "artifact")
        self.assertEqual(src, "fact_check")
        self.assertTrue(
            can_run_step(
                "final_output",
                statuses,
                has_topic=True,
                step_order=list(ARTICLE_STEP_ORDER),
            )
        )

    def test_meta_seo_still_uses_fact_check(self):
        statuses = {name: "done" for name in ARTICLE_STEP_ORDER}
        statuses["meta_seo"] = "pending"
        statuses["final_output"] = "pending"
        src, kind = input_source_for_step(
            "meta_seo", statuses, step_order=list(ARTICLE_STEP_ORDER)
        )
        self.assertEqual(kind, "artifact")
        self.assertEqual(src, "fact_check")


if __name__ == "__main__":
    unittest.main()
