from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import artifacts, auth_store, config, job_control
from backend.app import create_app


class SecurityApiTests(unittest.TestCase):
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
            "/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        self.token = login.get_json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self):
        config.CLIENTS_DIR = self.original_dir
        config.MONGODB_URI = self.original_mongo_uri
        auth_store.reset_memory_store_for_tests()
        self.temp.cleanup()

    def test_rejects_path_traversal_client_and_step(self):
        client = self.app.test_client()
        r1 = client.get(
            "/clients/bad..client/runs",
            headers=self.headers,
        )
        self.assertEqual(r1.status_code, 400)

        artifacts.save_run_manifest(
            "client-a",
            "run-1",
            "Topic",
            {"topic_card": "done"},
            pipeline_id="article",
        )
        r2 = client.get(
            "/clients/client-a/runs/run-1/artifacts/..evil",
            headers=self.headers,
        )
        self.assertEqual(r2.status_code, 400)

        with self.assertRaises(ValueError):
            artifacts.save_artifact("client-a", "run-1", "../evil", "x")

    def test_rejects_out_of_order_step(self):
        artifacts.save_run_manifest(
            "client-a",
            "run-order",
            "Topic",
            {"topic_card": "pending"},
            pipeline_id="article",
        )
        pipeline = type(
            "Pipeline",
            (),
            {
                "pipeline_id": "article",
                "step_order": ["topic_card", "outline"],
                "step_runners": {
                    "topic_card": lambda *a, **k: None,
                    "outline": lambda *a, **k: None,
                },
            },
        )()
        with patch("backend.api.routes.runs.get_pipeline", return_value=pipeline):
            response = self.app.test_client().post(
                "/clients/client-a/runs/run-order/steps/outline",
                json={},
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 409)
        self.assertIn("prerequisites", response.get_json()["detail"].lower())

    def test_cancel_aborts_bound_job_control(self):
        artifacts.save_run_manifest(
            "client-a",
            "run-cancel",
            "Topic",
            {"topic_card": "pending"},
            pipeline_id="article",
        )
        started = threading.Event()
        cancelled = threading.Event()

        def slow_runner(client_id, run_id, previous_artifact):
            started.set()
            for _ in range(40):
                try:
                    job_control.raise_if_cancelled()
                except job_control.JobCancelled:
                    cancelled.set()
                    raise
                time.sleep(0.05)

        pipeline = type(
            "Pipeline",
            (),
            {
                "pipeline_id": "article",
                "step_order": ["topic_card"],
                "step_runners": {"topic_card": slow_runner},
            },
        )()

        with patch("backend.api.routes.runs.get_pipeline", return_value=pipeline):
            client = self.app.test_client()
            start = client.post(
                "/clients/client-a/runs/run-cancel/steps/topic_card",
                json={"previous_artifact": "Topic"},
                headers=self.headers,
            )
            self.assertEqual(start.status_code, 202)
            self.assertTrue(started.wait(timeout=2))
            stop = client.post(
                "/clients/client-a/runs/run-cancel/steps/topic_card/cancel",
                headers=self.headers,
            )
            self.assertEqual(stop.status_code, 200)
            self.assertTrue(cancelled.wait(timeout=3))
            time.sleep(0.2)
            manifest = artifacts.ensure_run_manifest("client-a", "run-cancel")
            self.assertEqual(
                (manifest.get("statuses") or {}).get("topic_card"), "pending"
            )


if __name__ == "__main__":
    unittest.main()
