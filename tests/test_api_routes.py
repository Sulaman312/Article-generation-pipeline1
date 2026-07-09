from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import artifacts, config
from backend.app import create_app


class ApiRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.original_dir = config.CLIENTS_DIR
        self.original_mongo_uri = config.MONGODB_URI
        config.MONGODB_URI = None
        config.CLIENTS_DIR = Path(self.temp.name) / "clients"
        config.CLIENTS_DIR.mkdir(parents=True, exist_ok=True)
        with patch("backend.mongo_storage.initialize_runtime_cache", return_value=0):
            self.app = create_app()

    def tearDown(self):
        config.CLIENTS_DIR = self.original_dir
        config.MONGODB_URI = self.original_mongo_uri
        self.temp.cleanup()

    def test_health_returns_ok(self):
        response = self.app.test_client().get("/health")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["service"], "ContentFlow API")

    def test_list_clients_empty_workspace(self):
        response = self.app.test_client().get("/clients")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["clients"], [])

    def test_pipeline_steps_endpoint(self):
        response = self.app.test_client().get("/pipeline/steps")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["pipeline_id"], "article")
        keys = [step["key"] for step in payload["steps"]]
        self.assertIn("meta_seo", keys)
        self.assertLess(keys.index("meta_seo"), keys.index("final_output"))

    def test_stale_running_step_can_restart_after_crash(self):
        artifacts.save_run_manifest(
            "client-a",
            "run-stale",
            "Test topic",
            {"topic_card": "running"},
            pipeline_id="article",
        )

        started = threading.Event()
        done = threading.Event()

        def runner_with_signal(client_id, run_id, previous_artifact):
            started.set()
            try:
                return "topic card output"
            finally:
                done.set()

        pipeline = type(
            "Pipeline",
            (),
            {
                "pipeline_id": "article",
                "step_order": ["topic_card"],
                "step_runners": {"topic_card": runner_with_signal},
            },
        )()

        with patch("backend.api.routes.runs.get_pipeline", return_value=pipeline):
            response = self.app.test_client().post(
                "/clients/client-a/runs/run-stale/steps/topic_card",
                json={"previous_artifact": "Test topic"},
            )
            self.assertEqual(response.status_code, 202)
            self.assertTrue(started.wait(timeout=1))
            self.assertTrue(done.wait(timeout=3))


if __name__ == "__main__":
    unittest.main()
