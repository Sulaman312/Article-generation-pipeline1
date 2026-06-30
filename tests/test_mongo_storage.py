from __future__ import annotations

import io
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend import config, mongo_storage


class FakeFilesCollection:
    def __init__(self):
        self.docs: dict[str, dict] = {}

    def create_index(self, *args, **kwargs):
        return "path_1"

    def count_documents(self, query):
        return len(self.docs)

    def find(self, query=None, projection=None):
        return [dict(doc) for doc in self.docs.values()]

    def find_one_and_update(self, query, update, *, upsert=False):
        path = query["path"]
        previous = dict(self.docs[path]) if path in self.docs else None
        current = dict(self.docs.get(path) or {"path": path})
        current.update(update["$set"])
        self.docs[path] = current
        return previous

    def find_one_and_delete(self, query):
        return self.docs.pop(query["path"], None)


class FakeBucket:
    def __init__(self):
        self.blobs: dict[str, bytes] = {}
        self.counter = 0

    def upload_from_stream(self, filename, source, metadata=None):
        self.counter += 1
        blob_id = f"blob-{self.counter}"
        self.blobs[blob_id] = source.read()
        return blob_id

    def open_download_stream(self, blob_id):
        return io.BytesIO(self.blobs[blob_id])

    def delete(self, blob_id):
        self.blobs.pop(blob_id, None)


class MongoStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_uri = config.MONGODB_URI
        self.original_dir = config.CLIENTS_DIR
        config.MONGODB_URI = "mongodb://test.invalid"
        config.CLIENTS_DIR = Path(self.temp.name) / "cache"
        self.files = FakeFilesCollection()
        self.bucket = FakeBucket()
        mongo_storage._client = object()
        mongo_storage._files = self.files
        mongo_storage._bucket = self.bucket
        mongo_storage._snapshot = {}
        mongo_storage._known_paths = set()

    def tearDown(self):
        config.MONGODB_URI = self.original_uri
        config.CLIENTS_DIR = self.original_dir
        mongo_storage._client = None
        mongo_storage._db = None
        mongo_storage._files = None
        mongo_storage._bucket = None
        mongo_storage._snapshot = {}
        mongo_storage._known_paths = set()
        self.temp.cleanup()

    def test_sync_replaces_and_deletes_binary_file(self):
        image = config.CLIENTS_DIR / "client-a/runs/run-a/images/generated/image.png"
        image.parent.mkdir(parents=True)
        image.write_bytes(b"first-image")

        result = mongo_storage.sync_cache()
        self.assertEqual(result["uploaded"], 1)
        first_id = self.files.docs[
            "client-a/runs/run-a/images/generated/image.png"
        ]["gridfs_id"]
        self.assertEqual(self.bucket.blobs[first_id], b"first-image")

        image.write_bytes(b"second-image-content")
        result = mongo_storage.sync_cache()
        self.assertEqual(result["uploaded"], 1)
        second_id = self.files.docs[
            "client-a/runs/run-a/images/generated/image.png"
        ]["gridfs_id"]
        self.assertNotEqual(first_id, second_id)
        self.assertNotIn(first_id, self.bucket.blobs)
        self.assertEqual(self.bucket.blobs[second_id], b"second-image-content")

        image.unlink()
        result = mongo_storage.sync_cache()
        self.assertEqual(result["deleted"], 1)
        self.assertFalse(self.files.docs)
        self.assertFalse(self.bucket.blobs)

    def test_seed_and_hydrate_complete_tree(self):
        source = Path(self.temp.name) / "source"
        (source / "client-a/context").mkdir(parents=True)
        (source / "client-a/context/context.md").write_text(
            "Client context", encoding="utf-8"
        )
        (source / "client-a/logo.png").write_bytes(b"png-data")

        result = mongo_storage.seed_from_directory(source)
        self.assertEqual(result["uploaded"], 2)

        hydrated = mongo_storage.hydrate_cache(clear=True)
        self.assertEqual(hydrated, 2)
        self.assertEqual(
            (config.CLIENTS_DIR / "client-a/context/context.md").read_text(
                encoding="utf-8"
            ),
            "Client context",
        )
        self.assertEqual(
            (config.CLIENTS_DIR / "client-a/logo.png").read_bytes(), b"png-data"
        )

    def test_startup_hydration_retries_transient_connection_failure(self):
        with (
            patch(
                "backend.mongo_storage.hydrate_cache",
                side_effect=[RuntimeError("temporary TLS failure"), 12],
            ) as hydrate,
            patch("backend.mongo_storage._reset_connection") as reset,
            patch("backend.mongo_storage.time.sleep") as sleep,
            patch.dict(
                "os.environ",
                {
                    "MONGODB_STARTUP_ATTEMPTS": "2",
                    "MONGODB_RETRY_DELAY_SECONDS": "0.25",
                },
            ),
        ):
            hydrated = mongo_storage.initialize_runtime_cache()

        self.assertEqual(hydrated, 12)
        self.assertEqual(hydrate.call_count, 2)
        reset.assert_called_once_with()
        sleep.assert_called_once_with(0.25)

    def test_flask_mutations_are_written_through(self):
        from backend.app import create_app

        app = create_app()
        client = app.test_client()
        response = client.post(
            "/clients/client-a", json={"display_name": "Client A"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("client-a/workspace.json", self.files.docs)

        response = client.delete("/clients/client-a")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("client-a/workspace.json", self.files.docs)

    def test_pipeline_step_returns_202_then_persists_background_result(self):
        from backend import artifacts
        from backend.app import create_app

        app = create_app()
        artifacts.save_run_manifest(
            "client-a",
            "run-a",
            "Test topic",
            {"topic_card": "pending"},
            pipeline_id="article",
        )
        started = threading.Event()
        release = threading.Event()

        def runner(client_id, run_id, previous_artifact):
            started.set()
            release.wait(timeout=2)
            return artifacts.save_artifact(
                client_id, run_id, "topic_card", "Generated topic card"
            )

        pipeline = SimpleNamespace(
            pipeline_id="article",
            step_order=["topic_card"],
            step_runners={"topic_card": runner},
        )
        with patch("backend.api.routes.runs.get_pipeline", return_value=pipeline):
            response = app.test_client().post(
                "/clients/client-a/runs/run-a/steps/topic_card",
                json={"previous_artifact": "Test topic"},
            )
            self.assertEqual(response.status_code, 202)
            self.assertTrue(response.get_json()["accepted"])
            self.assertTrue(started.wait(timeout=1))

            running = artifacts.read_run_manifest("client-a", "run-a")
            self.assertEqual(running["statuses"]["topic_card"], "running")
            release.set()

            deadline = time.time() + 3
            while time.time() < deadline:
                completed = artifacts.read_run_manifest("client-a", "run-a")
                if completed["statuses"]["topic_card"] == "done":
                    break
                time.sleep(0.02)
            self.assertEqual(completed["statuses"]["topic_card"], "done")
            self.assertIn("client-a/runs/run-a/topic_card.md", self.files.docs)

    def test_background_step_error_is_available_to_polling_client(self):
        from backend import artifacts
        from backend.app import create_app

        app = create_app()
        artifacts.save_run_manifest(
            "client-a",
            "run-error",
            "Test topic",
            {"topic_card": "pending"},
            pipeline_id="article",
        )

        def runner(*args):
            raise RuntimeError("provider unavailable")

        pipeline = SimpleNamespace(
            pipeline_id="article",
            step_order=["topic_card"],
            step_runners={"topic_card": runner},
        )
        with patch("backend.api.routes.runs.get_pipeline", return_value=pipeline):
            response = app.test_client().post(
                "/clients/client-a/runs/run-error/steps/topic_card",
                json={"previous_artifact": "Test topic"},
            )
            self.assertEqual(response.status_code, 202)

            deadline = time.time() + 3
            while time.time() < deadline:
                failed = artifacts.read_run_manifest("client-a", "run-error")
                if failed["statuses"]["topic_card"] == "error":
                    break
                time.sleep(0.02)
            self.assertEqual(failed["statuses"]["topic_card"], "error")
            self.assertIn("provider unavailable", failed["step_errors"]["topic_card"])

    def test_template_metadata_supports_mongo_cache_outside_repo(self):
        import json

        from backend import image_templates

        source = (
            config.CLIENTS_DIR
            / "Simonetti/templates/Simonetti_template/template.json"
        )
        source.parent.mkdir(parents=True)
        source.write_text(
            json.dumps(
                {
                    "name": "Simonetti_template",
                    "formats": {"instagram": {"width": 1080, "height": 1350}},
                }
            ),
            encoding="utf-8",
        )

        template = image_templates.ensure_run_template(
            "Simonetti",
            "run-a",
            template_id="Simonetti_template",
        )

        self.assertEqual(
            template["source_template"],
            "clients/Simonetti/templates/Simonetti_template/template.json",
        )


if __name__ == "__main__":
    unittest.main()
