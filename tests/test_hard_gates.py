from __future__ import annotations

import unittest

from backend import hard_gates


GOOD_LEDE = (
    "Online vet visits let pet owners get clinical advice without a long clinic wait. "
    "This guide explains who telehealth works for, what to prepare beforehand, and when "
    "you still need an in-person exam so you can book the right option with confidence."
)

SAMPLE_AUDIT = """
---RESEARCH AUDIT START---
## Approved case study (for draft E-E-A-T)
- STATUS: APPROVED
- TITLE: Clinic X telehealth pilot
- SOURCE URL: https://example.com/case-ok
- URL CHECK: OK
- DO NOT CLAIM: 400% ROI

## Flagged / reject list (do not put in draft)
- CLAIM: AcmePets cut costs by 400% overnight | WHY: invented stat

## Approved FAQ questions
1. How do I book an online visit?
2. What does an online visit cost?
3. Is telehealth safe for cats?
4. When should I go in person?
5. Can I get prescriptions online?

## URL verification (pipeline)
- [OK] `https://example.com/case-ok` — HTTP 200 — GET ok
- [FAIL] `https://example.com/dead` — HTTP 404 — GET HTTP 404
---RESEARCH AUDIT END---
"""


class HardGateUnitTests(unittest.TestCase):
    def test_good_lede_word_band(self):
        n = len(hard_gates._word_tokens(GOOD_LEDE))
        self.assertGreaterEqual(n, hard_gates.LEDE_MIN_WORDS)
        self.assertLessEqual(n, hard_gates.LEDE_MAX_WORDS)

    def test_lede_length_gate(self):
        short = "# Title\n\nToo short.\n\n## Next\n\nBody.\n"
        issue = hard_gates.check_lede(short)
        self.assertIsNotNone(issue)
        self.assertEqual(issue.code, "lede_length")

        good = f"# Title\n\n{GOOD_LEDE}\n\n## Next\n\nBody words here for section.\n"
        self.assertIsNone(hard_gates.check_lede(good))

    def test_keyword_once_in_first_100(self):
        lede = (
            "An online vet appointment helps busy owners skip waiting rooms for mild issues. "
            "You will learn prep steps, red flags, and how to choose a reputable provider "
            "without wasting time on the wrong option for your pet today."
        )
        pad = " ".join(["clinic"] * 90)
        art = (
            f"# Guide\n\n{lede}\n\n## Details\n\n"
            f"{pad}\n"
            "More prose about clinics and scheduling without repeating the phrase.\n"
        )
        self.assertIsNone(hard_gates.check_primary_keyword(art, "online vet appointment"))

        bad = art + "\nAlso book an online vet appointment again later.\n"
        issue = hard_gates.check_primary_keyword(bad, "online vet appointment")
        self.assertIsNotNone(issue)
        self.assertEqual(issue.code, "keyword_repeat")

    def test_flagged_claim_detected(self):
        art = (
            "# T\n\n"
            + GOOD_LEDE
            + "\n\n## S\n\nAcmePets cut costs by 400% overnight somehow.\n"
        )
        claims = hard_gates.parse_audit_flagged_claims(SAMPLE_AUDIT)
        self.assertTrue(claims)
        issues = hard_gates.check_flagged_claims(art, claims)
        self.assertTrue(any(i.code == "flagged_claim" for i in issues))

    def test_fail_url_blocked(self):
        art = (
            f"# T\n\n{GOOD_LEDE}\n\n## S\n\n"
            "See the [pilot](https://example.com/dead) for detail.\n"
        )
        issues = hard_gates.check_case_study_urls(art, SAMPLE_AUDIT, "")
        self.assertTrue(any(i.code == "fail_url" for i in issues))

    def test_faq_unapproved(self):
        lede = (
            "An online vet appointment helps owners get advice without a long clinic wait. "
            "This guide explains who telehealth fits, what to prepare, and when an exam "
            "in person is still the safer choice for your animal."
        )
        art = (
            "# How to book telehealth care\n\n"
            f"{lede}\n\n"
            "## When telehealth works\n\n"
            "Use remote care for mild issues and triage decisions carefully.\n\n"
            "## Frequently Asked Questions\n\n"
            "### How do I book an online visit?\n\nA.\n\n"
            "### What does an online visit cost?\n\nA.\n\n"
            "### Is telehealth safe for cats?\n\nA.\n\n"
            "### When should I go in person?\n\nA.\n\n"
            "### What is the meaning of life?\n\nA.\n\n"
        )
        approved = hard_gates.parse_audit_approved_faq(SAMPLE_AUDIT)
        issues = hard_gates.check_faq(
            art, require_faq=True, approved_faq=approved, paa_bank=[]
        )
        self.assertTrue(any(i.code == "faq_unapproved" for i in issues))

    def test_evaluate_passes_clean_article(self):
        # 40+ word lede that includes the primary keyword once
        lede = (
            "An online vet appointment helps owners get advice without a long clinic wait time. "
            "This guide explains who telehealth fits best, what to prepare beforehand, and when "
            "an exam in person is still the safer choice for your animal today."
        )
        filler = " ".join(["detail"] * 80)
        art = (
            "# How to book telehealth care\n\n"
            f"{lede}\n\n"
            "## When telehealth works\n\n"
            "Use remote care for mild issues and triage decisions carefully. "
            f"Keep emergencies at the clinic with your regular veterinarian. {filler}\n\n"
            "## Frequently Asked Questions\n\n"
            "### How do I book an online visit?\n\nBook through the clinic portal.\n\n"
            "### What does an online visit cost?\n\nFees vary by clinic.\n\n"
            "### Is telehealth safe for cats?\n\nOften yes for mild issues.\n\n"
            "### When should I go in person?\n\nGo in for emergencies.\n\n"
            "### Can I get prescriptions online?\n\nSometimes after evaluation.\n\n"
        )
        report = hard_gates.evaluate_article_gates(
            art,
            primary_keyword="online vet appointment",
            word_target=150,
            research_audit=SAMPLE_AUDIT,
            require_faq=True,
            stage="draft",
        )
        self.assertTrue(report.ok, msg=report.failure_message())


if __name__ == "__main__":
    unittest.main()
