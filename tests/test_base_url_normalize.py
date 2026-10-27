from __future__ import annotations

import unittest

from backend.config import normalize_base_url


class NormalizeBaseUrlTests(unittest.TestCase):
    def test_adds_https_when_scheme_missing(self):
        self.assertEqual(normalize_base_url("openrouter.ai/api"), "https://openrouter.ai/api")

    def test_keeps_existing_scheme(self):
        self.assertEqual(normalize_base_url("https://openrouter.ai/api"), "https://openrouter.ai/api")
        self.assertEqual(normalize_base_url("http://localhost:4000"), "http://localhost:4000")

    def test_strips_quotes_spaces_and_trailing_slash(self):
        self.assertEqual(normalize_base_url('  "https://openrouter.ai/api/" '), "https://openrouter.ai/api")

    def test_empty_means_direct_anthropic(self):
        self.assertIsNone(normalize_base_url(""))
        self.assertIsNone(normalize_base_url("   "))
        self.assertIsNone(normalize_base_url(None))


if __name__ == "__main__":
    unittest.main()
