from __future__ import annotations

import unittest

from backend import faq_schema


def _sample_with_faqs(n: int) -> str:
    lines = ["## Intro", "Body text.", "", "## Frequently Asked Questions", ""]
    for i in range(1, n + 1):
        lines.extend([f"### Question {i}?", "", f"Answer {i} here.", ""])
    lines.extend(["## Next steps", "Closing prose."])
    return "\n".join(lines)


class FaqSchemaTests(unittest.TestCase):
    def test_extract_faq_pairs_counts_h3s(self):
        text = _sample_with_faqs(6)
        self.assertEqual(len(faq_schema.extract_faq_pairs(text)), 6)

    def test_ensure_faq_from_reference_restores_dropped_items(self):
        reference = _sample_with_faqs(6)
        reduced = _sample_with_faqs(2)
        restored = faq_schema.ensure_faq_from_reference(reduced, reference)
        self.assertEqual(len(faq_schema.extract_faq_pairs(restored)), 6)

    def test_ensure_faq_from_reference_noop_when_complete(self):
        reference = _sample_with_faqs(6)
        current = _sample_with_faqs(6)
        self.assertIs(
            faq_schema.ensure_faq_from_reference(current, reference),
            current,
        )


if __name__ == "__main__":
    unittest.main()
