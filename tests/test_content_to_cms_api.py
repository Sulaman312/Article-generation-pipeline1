"""Run the Content to CMS step through the real HTTP route and job wrapper."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import artifacts, auth_store, config
from backend.app import create_app
from backend.integrations import webflow
from backend.pipeline_steps import ARTICLE_STEP_ORDER

FINAL_OUTPUT = "---FINAL OUTPUT START---\n# My Title\n\n## Intro\nHello world.\n---FINAL OUTPUT END---\n"


class ContentToCmsApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.original_dir = config.CLIENTS_DIR
        self.original_mongo_uri = config.MONGODB_URI
        config.MONGODB_URI = None
        config.CLIENTS_DIR = Path(self.temp.name) / "clients"
        config.CLIENTS_DIR.mkdir(parents=True, exist_ok=True)
        auth_store.reset_memory_store_for_tests()
        with patch("backend.mongo_storage.initialize_runtime_cache", return_value=0):
            self.app = create_app()
        login = self.app.test_client().post(
            "/auth/login", json={"username": "admin", "password": "admin123"}
        )
        self.headers = {"Authorization": f"Bearer {login.get_json()['token']}"}

    def tearDown(self):
        config.CLIENTS_DIR = self.original_dir
        config.MONGODB_URI = self.original_mongo_uri
        auth_store.reset_memory_store_for_tests()
        self.temp.cleanup()

    def _make_run(self, final_output_status: str):
        statuses = {name: "done" for name in ARTICLE_STEP_ORDER}
        statuses["content_to_cms"] = "pending"
        statuses["final_output"] = final_output_status
        artifacts.save_run_manifest("c", "r", "Topic", statuses, pipeline_id="article")
        artifacts.save_artifact("c", "r", "final_output", FINAL_OUTPUT)

    def _run_step(self):
        return self.app.test_client().post(
            "/clients/c/runs/r/steps/content_to_cms", json={}, headers=self.headers
        )

    def _wait_for_status(self, wanted: str) -> dict:
        for _ in range(60):
            manifest = artifacts.read_run_manifest("c", "r") or {}
            if (manifest.get("statuses") or {}).get("content_to_cms") == wanted:
                return manifest
            time.sleep(0.1)
        self.fail(f"content_to_cms never reached {wanted!r}")

    def test_step_appears_in_pipeline_steps_after_final_output(self):
        resp = self.app.test_client().get("/pipeline/steps", headers=self.headers)
        keys = [s["key"] for s in resp.get_json()["steps"]]
        self.assertEqual(keys[-2:], ["final_output", "content_to_cms"])

    def test_step_runs_and_marks_done(self):
        self._make_run("done")
        with patch.dict(
            "os.environ", {"WEBFLOW_TOKEN": "t", "WEBFLOW_COLLECTION_ID": "col"}
        ), patch.object(webflow, "create_draft_item", return_value="item-7"):
            self.assertEqual(self._run_step().status_code, 202)
            self._wait_for_status("done")
        self.assertIn(
            "Webflow item ID: item-7",
            artifacts.load_artifact("c", "r", "content_to_cms"),
        )

    def test_blocked_until_final_output_is_done(self):
        self._make_run("pending")
        self.assertEqual(self._run_step().status_code, 409)

    def test_missing_credentials_show_a_readable_error(self):
        self._make_run("done")
        artifacts.write_workspace_meta(
            "c",
            {
                "display_name": "C",
                "cms": {"provider": "webflow"},
            },
        )
        with patch.dict("os.environ", {"WEBFLOW_TOKEN": "", "WEBFLOW_COLLECTION_ID": ""}):
            self.assertEqual(self._run_step().status_code, 202)
            manifest = self._wait_for_status("error")
        self.assertIn("WEBFLOW_TOKEN", manifest["step_errors"]["content_to_cms"])


if __name__ == "__main__":
    unittest.main()
