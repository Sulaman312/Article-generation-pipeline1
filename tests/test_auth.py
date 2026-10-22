from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import auth_store, config
from backend.app import create_app


class AuthApiTests(unittest.TestCase):
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
        self.client = self.app.test_client()

    def tearDown(self):
        config.CLIENTS_DIR = self.original_dir
        config.MONGODB_URI = self.original_mongo_uri
        auth_store.reset_memory_store_for_tests()
        self.temp.cleanup()

    def test_clients_requires_auth(self):
        response = self.client.get("/clients")
        self.assertEqual(response.status_code, 401)

    def test_login_and_access(self):
        bad = self.client.post(
            "/auth/login",
            json={"username": "admin", "password": "wrong"},
        )
        self.assertEqual(bad.status_code, 401)

        ok = self.client.post(
            "/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        self.assertEqual(ok.status_code, 200)
        token = ok.get_json()["token"]
        self.assertTrue(token)

        me = self.client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.get_json()["username"], "admin")

        clients = self.client.get(
            "/clients",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(clients.status_code, 200)
        self.assertEqual(clients.get_json()["clients"], [])

    def test_spa_shell_deep_links_are_public_html(self):
        """Deep links like /w/Client/overview must serve index.html, not 401 JSON."""
        ui_index = (
            Path(__file__).resolve().parent.parent / "atlas-ui" / "build" / "index.html"
        )
        if not ui_index.is_file():
            self.skipTest("atlas-ui/build/index.html missing — run npm run build")

        for path in (
            "/w/Digimidi.ch/overview",
            "/w/Digimidi.ch/matrix",
            "/w/Acme/artifacts",
            "/w/Acme/runs/run_abc",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, path)
                self.assertIn("text/html", response.content_type, path)
                self.assertIn(b"<!DOCTYPE html>", response.data[:200], path)

        # API routes stay protected
        api = self.client.get("/clients")
        self.assertEqual(api.status_code, 401)

    def test_logout_revokes_token(self):
        ok = self.client.post(
            "/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        token = ok.get_json()["token"]
        out = self.client.post(
            "/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(out.status_code, 204)
        clients = self.client.get(
            "/clients",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(clients.status_code, 401)


if __name__ == "__main__":
    unittest.main()
