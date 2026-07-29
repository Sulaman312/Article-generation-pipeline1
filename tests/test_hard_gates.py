from __future__ import annotations

import unittest

from backend import hard_gates


GOOD_LEDE = (
    "Online vet visits let pet owners get clinical advice without a long clinic wait. "
    "This guide explains who telehealth works for, what to prepare beforehand, and when "
    "you still need an in-person exam so you can book the right option with confidence."
)

HERO = "![Pet owner on a laptop during an online vet visit](IMAGE: telehealth-hero)"


def _opening(title: str, summary: str) -> str:
    return f"# {title}\n\n## Summary\n\n{summary}\n\n{HERO}\n"


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

FAQ_ANSWER = (
    "Start in your clinic portal and pick a telehealth slot that fits your schedule. "
    "Upload recent photos or videos of the concern before the call begins. "
    "Join a few minutes early so audio and video work without scrambling. "
    "Have your pet's medication list ready for the clinician."
)


class HardGateUnitTests(unittest.TestCase):
    def test_good_lede_word_band(self):
        n = len(hard_gates._word_tokens(GOOD_LEDE))
        self.assertGreaterEqual(n, hard_gates.LEDE_MIN_WORDS)
        self.assertLessEqual(n, hard_gates.LEDE_MAX_WORDS)

    def test_lede_length_gate(self):
        short = _opening("Title", "Too short.") + "\n## Next\n\nBody.\n"
        issue = hard_gates.check_lede(short)
        self.assertIsNotNone(issue)
        self.assertEqual(issue.code, "lede_length")

        good = _opening("Title", GOOD_LEDE) + "\n## Next\n\nBody words here for section.\n"
        self.assertIsNone(hard_gates.check_lede(good))

    def test_summary_heading_and_image_required(self):
        plain = f"# Title\n\n{GOOD_LEDE}\n\n## Next\n\nBody.\n"
        issue = hard_gates.check_lede(plain)
        self.assertIsNotNone(issue)
        self.assertEqual(issue.code, "summary_heading")

        no_img = f"# Title\n\n## Summary\n\n{GOOD_LEDE}\n\n## Next\n\nBody.\n"
        issue = hard_gates.check_lede(no_img)
        self.assertIsNotNone(issue)
        self.assertEqual(issue.code, "summary_image")

    def test_keyword_once_in_first_100(self):
        lede = (
            "An online vet appointment helps busy owners skip waiting rooms for mild issues. "
            "You will learn prep steps, red flags, and how to choose a reputable provider "
            "without wasting time on the wrong option for your pet today."
        )
        pad = " ".join(["clinic"] * 90)
        art = (
            _opening("Guide", lede)
            + f"\n## Details\n\n{pad}\n"
            "More prose about clinics and scheduling without repeating the phrase.\n"
        )
        self.assertIsNone(hard_gates.check_primary_keyword(art, "online vet appointment"))

        bad = art + "\nAlso book an online vet appointment again later.\n"
        issue = hard_gates.check_primary_keyword(bad, "online vet appointment")
        self.assertIsNotNone(issue)
        self.assertEqual(issue.code, "keyword_repeat")

    def test_flagged_claim_detected(self):
        art = (
            _opening("T", GOOD_LEDE)
            + "\n## S\n\nAcmePets cut costs by 400% overnight somehow.\n"
        )
        claims = hard_gates.parse_audit_flagged_claims(SAMPLE_AUDIT)
        self.assertTrue(claims)
        issues = hard_gates.check_flagged_claims(art, claims)
        self.assertTrue(any(i.code == "flagged_claim" for i in issues))

    def test_fail_url_blocked(self):
        art = (
            _opening("T", GOOD_LEDE)
            + "\n## S\n\nSee the [pilot](https://example.com/dead) for detail.\n"
        )
        issues = hard_gates.check_case_study_urls(art, SAMPLE_AUDIT, "")
        self.assertTrue(any(i.code == "fail_url" for i in issues))

    def test_uncited_price_blocked(self):
        art = (
            _opening("T", GOOD_LEDE)
            + "\n## Pricing\n\nVisits usually cost $49 per consult with no source.\n"
        )
        issues = hard_gates.check_cited_numbers(art)
        self.assertTrue(any(i.code == "uncited_number" for i in issues))

        cited = (
            _opening("T", GOOD_LEDE)
            + "\n## Pricing\n\n"
            "Visits usually cost [$49](https://example.com/fees) per consult when booked online.\n"
        )
        self.assertEqual(hard_gates.check_cited_numbers(cited), [])

    def test_faq_answer_length(self):
        short = "One short line only."
        self.assertEqual(hard_gates._answer_sentence_count(short), 1)
        self.assertEqual(hard_gates._answer_sentence_count(FAQ_ANSWER), 4)

    def test_faq_unapproved(self):
        lede = (
            "An online vet appointment helps owners get advice without a long clinic wait. "
            "This guide explains who telehealth fits, what to prepare, and when an exam "
            "in person is still the safer choice for your animal."
        )
        art = (
            _opening("How to book telehealth care", lede)
            + "\n## When telehealth works\n\n"
            "Use remote care for mild issues and triage decisions carefully.\n\n"
            "## Frequently Asked Questions\n\n"
            f"### How do I book an online visit?\n\n{FAQ_ANSWER}\n\n"
            f"### What does an online visit cost?\n\n{FAQ_ANSWER}\n\n"
            f"### Is telehealth safe for cats?\n\n{FAQ_ANSWER}\n\n"
            f"### When should I go in person?\n\n{FAQ_ANSWER}\n\n"
            f"### What is the meaning of life?\n\n{FAQ_ANSWER}\n\n"
        )
        approved = hard_gates.parse_audit_approved_faq(SAMPLE_AUDIT)
        issues = hard_gates.check_faq(
            art, require_faq=True, approved_faq=approved, paa_bank=[]
        )
        self.assertTrue(any(i.code == "faq_unapproved" for i in issues))

    def test_evaluate_passes_clean_article(self):
        lede = (
            "An online vet appointment helps owners get advice without a long clinic wait time. "
            "This guide explains who telehealth fits best, what to prepare beforehand, and when "
            "an exam in person is still the safer choice for your animal today."
        )
        filler = " ".join(["detail"] * 80)
        art = (
            _opening("How to book telehealth care", lede)
            + "\n## When telehealth works\n\n"
            "Use remote care for mild issues and triage decisions carefully. "
            f"Keep emergencies at the clinic with your regular veterinarian. {filler}\n\n"
            "## Frequently Asked Questions\n\n"
            f"### How do I book an online visit?\n\n{FAQ_ANSWER}\n\n"
            f"### What does an online visit cost?\n\n{FAQ_ANSWER}\n\n"
            f"### Is telehealth safe for cats?\n\n{FAQ_ANSWER}\n\n"
            f"### When should I go in person?\n\n{FAQ_ANSWER}\n\n"
            f"### Can I get prescriptions online?\n\n{FAQ_ANSWER}\n\n"
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
