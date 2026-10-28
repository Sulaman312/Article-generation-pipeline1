from __future__ import annotations

import re
import unittest
from pathlib import Path

from backend.pipeline_metadata import article_pipeline_steps
from backend.pipeline_steps import ARTICLE_STEP_ORDER

REPO_ROOT = Path(__file__).resolve().parent.parent
PIPELINE_JS = REPO_ROOT / "atlas-ui" / "src" / "constants" / "pipeline.js"


def _fallback_keys_from_pipeline_js() -> list[str]:
    text = PIPELINE_JS.read_text(encoding="utf-8")
    return re.findall(r'key:\s*"([^"]+)"', text)


class PipelineSyncTests(unittest.TestCase):
    def test_api_metadata_matches_canonical_order(self):
        keys = [step["key"] for step in article_pipeline_steps()]
        self.assertEqual(keys, ARTICLE_STEP_ORDER)

    def test_frontend_fallback_matches_canonical_order(self):
        self.assertTrue(PIPELINE_JS.is_file(), "atlas-ui pipeline fallback missing")
        self.assertEqual(_fallback_keys_from_pipeline_js(), list(ARTICLE_STEP_ORDER))

    def test_every_step_has_ui_metadata(self):
        rows = article_pipeline_steps()
        self.assertEqual(len(rows), len(ARTICLE_STEP_ORDER))
        for row in rows:
            self.assertIn("label", row)
            self.assertIn("matrixLabel", row)
            self.assertIn("matrixCol", row)


if __name__ == "__main__":
    unittest.main()
