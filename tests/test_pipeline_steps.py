from __future__ import annotations

import unittest

from backend.pipeline import STEP_ORDER, STEP_RUNNERS
from backend.pipeline_steps import ARTICLE_STEP_ORDER
from backend import steps


class PipelineStepRegistryTests(unittest.TestCase):
    def test_canonical_order_matches_pipeline_module(self):
        self.assertEqual(STEP_ORDER, ARTICLE_STEP_ORDER)

    def test_every_step_has_a_runner(self):
        self.assertEqual(set(STEP_RUNNERS.keys()), set(ARTICLE_STEP_ORDER))

    def test_steps_module_numbering_matches_order(self):
        for index, name in enumerate(ARTICLE_STEP_ORDER, start=1):
            self.assertEqual(steps._PIPELINE_STEP_NUM[name], index)

    def test_meta_seo_runs_before_final_output(self):
        self.assertLess(
            ARTICLE_STEP_ORDER.index("meta_seo"),
            ARTICLE_STEP_ORDER.index("final_output"),
        )


if __name__ == "__main__":
    unittest.main()
