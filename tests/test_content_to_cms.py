from __future__ import annotations

import json
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from backend import artifacts, config, content_to_cms, pipeline_flow, runner
from backend.integrations import webflow
from backend.pipeline import STEP_ORDER, STEP_RUNNERS
from backend.pipeline_steps import MANUAL_ONLY_STEPS

FINAL_OUTPUT = """---FINAL OUTPUT START---
# AI resume screening: accuracy, bias, and what to automate

## Key takeaways
- **AI resume screening** is a reliable prioritization tool when confined to parsing.
- Run a role-specific accuracy test on your own candidate data.
- Bias exposure is both technical and legal.

![Recruiter reviewing a ranking list](IMAGE: ai-resume-screening-recruiter-review-workflow)

## What AI can and cannot do
AI handles ingestion, as described in [screening workflow stages](https://example.com/stages), well.
See our guide to [ai for recruitment agencies](INTERNAL:/blog/ai-for-recruitment-agencies).

**Checkpoint 1: Job-requirement approval.** A lead signs off the criteria.

## Frequently Asked Questions

### How accurate is AI resume screening?

Accuracy varies by role.

## Hard gate report (non-strict)
Hard gates failed:
- [word_count] Body word count is 2,042; required 1,700-1,900.
---FINAL OUTPUT END---
"""


class BuildPostTests(unittest.TestCase):
    def setUp(self):
        self.post = content_to_cms.build_post(FINAL_OUTPUT, "run-1")

    def test_title_and_slug(self):
        self.assertEqual(
            self.post["title"], "AI resume screening: accuracy, bias, and what to automate"
        )
        self.assertEqual(
            self.post["slug"], "ai-resume-screening-accuracy-bias-and-what-to-automate"
        )

    def test_title_not_repeated_in_body(self):
        self.assertNotIn("<h1>", self.post["html"])
        self.assertNotIn("what to automate", self.post["html"])

    def test_hard_gate_report_removed(self):
        self.assertNotIn("Hard gate", self.post["html"])
        self.assertNotIn("word_count", self.post["html"])

    def test_key_takeaways_become_a_clean_list(self):
        html = self.post["html"]
        self.assertIn(
            "<h2>Key takeaways</h2><ul><li>AI resume screening is a reliable", html
        )
        self.assertEqual(html.count("<li>"), 3)
        list_block = html[html.index("<ul>") : html.index("</ul>")]
        self.assertNotIn("\n", list_block)

    def test_image_placeholder_removed(self):
        self.assertNotIn("IMAGE:", self.post["html"])
        self.assertNotIn("<img", self.post["html"])

    def test_internal_link_is_plain_text_external_stays_a_link(self):
        html = self.post["html"]
        self.assertIn("ai for recruitment agencies", html)
        self.assertNotIn("INTERNAL", html)
        self.assertIn('<a href="https://example.com/stages">screening workflow stages</a>', html)

    def test_headings_and_bold_survive(self):
        html = self.post["html"]
        self.assertIn("<h2>Frequently Asked Questions</h2>", html)
        self.assertIn("<h3>How accurate is AI resume screening?</h3>", html)
        self.assertIn("<strong>Checkpoint 1: Job-requirement approval.</strong>", html)


class RegistrationTests(unittest.TestCase):
    def test_step_is_last_registered_and_manual_only(self):
        self.assertEqual(STEP_ORDER[-1], "content_to_cms")
        self.assertIn("content_to_cms", STEP_RUNNERS)
        self.assertIn("content_to_cms", MANUAL_ONLY_STEPS)


class RunStepTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        patcher = mock.patch.object(config, "CLIENTS_DIR", self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        env = mock.patch.dict(
            "os.environ",
            {"WEBFLOW_TOKEN": "tok", "WEBFLOW_COLLECTION_ID": "col-1"},
        )
        env.start()
        self.addCleanup(env.stop)
        artifacts.save_artifact("c", "r", "final_output", FINAL_OUTPUT)

    def test_creates_draft_with_expected_fields(self):
        with mock.patch.object(webflow, "create_draft_item", return_value="item-1") as create:
            out = content_to_cms.run_content_to_cms("c", "r")
        fields = create.call_args.args[0]
        self.assertEqual(fields["name"], "AI resume screening: accuracy, bias, and what to automate")
        self.assertIn("post-body", fields)
        self.assertEqual(fields["contentflow-run-id-2"], "r")
        self.assertIn("Webflow item ID: item-1", out)
        saved = artifacts.load_artifact("c", "r", "content_to_cms")
        self.assertIn("Webflow item ID: item-1", saved)

    def test_rerun_updates_same_draft_not_a_duplicate(self):
        with mock.patch.object(webflow, "create_draft_item", return_value="item-1"):
            content_to_cms.run_content_to_cms("c", "r")
        with mock.patch.object(webflow, "create_draft_item") as create, mock.patch.object(
            webflow, "update_item", return_value="item-1"
        ) as update:
            out = content_to_cms.run_content_to_cms("c", "r")
        create.assert_not_called()
        update.assert_called_once()
        self.assertIn("Result: updated", out)

    def test_deleted_draft_in_webflow_creates_a_new_one(self):
        with mock.patch.object(webflow, "create_draft_item", return_value="item-1"):
            content_to_cms.run_content_to_cms("c", "r")
        gone = webflow.WebflowError("Webflow 404", status=404)
        with mock.patch.object(webflow, "update_item", side_effect=gone), mock.patch.object(
            webflow, "create_draft_item", return_value="item-2"
        ):
            out = content_to_cms.run_content_to_cms("c", "r")
        self.assertIn("Webflow item ID: item-2", out)
        self.assertIn("Result: created", out)

    def test_other_webflow_errors_are_not_hidden(self):
        with mock.patch.object(webflow, "create_draft_item", return_value="item-1"):
            content_to_cms.run_content_to_cms("c", "r")
        bad = webflow.WebflowError("Webflow 400: bad field", status=400)
        with mock.patch.object(webflow, "update_item", side_effect=bad):
            with self.assertRaises(webflow.WebflowError):
                content_to_cms.run_content_to_cms("c", "r")

    def test_run_id_field_can_be_skipped(self):
        with mock.patch.dict("os.environ", {"WEBFLOW_FIELD_RUN_ID": ""}), mock.patch.object(
            webflow, "create_draft_item", return_value="item-1"
        ) as create:
            content_to_cms.run_content_to_cms("c", "r")
        self.assertNotIn("contentflow-run-id-2", create.call_args.args[0])

    def test_body_field_slug_is_configurable(self):
        with mock.patch.dict("os.environ", {"WEBFLOW_FIELD_BODY": "article-body"}), mock.patch.object(
            webflow, "create_draft_item", return_value="item-1"
        ) as create:
            content_to_cms.run_content_to_cms("c", "r")
        self.assertIn("article-body", create.call_args.args[0])
        self.assertNotIn("post-body", create.call_args.args[0])

    def test_missing_final_output_gives_clear_error(self):
        with self.assertRaisesRegex(RuntimeError, "Final Output"):
            content_to_cms.run_content_to_cms("c", "no-such-run")

    def test_missing_credentials_give_clear_error(self):
        with mock.patch.dict("os.environ", {"WEBFLOW_TOKEN": ""}):
            with self.assertRaisesRegex(webflow.WebflowError, "WEBFLOW_TOKEN"):
                content_to_cms.run_content_to_cms("c", "r")


class FlowTests(unittest.TestCase):
    def test_unlocks_only_after_final_output(self):
        statuses = {name: "done" for name in STEP_ORDER}
        self.assertTrue(
            pipeline_flow.can_run_step("content_to_cms", statuses, has_topic=True)
        )
        statuses["final_output"] = "pending"
        self.assertFalse(
            pipeline_flow.can_run_step("content_to_cms", statuses, has_topic=True)
        )

    def test_input_is_final_output(self):
        statuses = {name: "done" for name in STEP_ORDER}
        src, kind = pipeline_flow.input_source_for_step("content_to_cms", statuses)
        self.assertEqual((src, kind), ("final_output", "artifact"))


class FullPipelineSkipsCmsTests(unittest.TestCase):
    def test_automatic_full_run_never_calls_content_to_cms(self):
        calls: list[str] = []
        fakes = {
            name: (lambda c, r, prev, _n=name: calls.append(_n) or "out")
            for name in STEP_ORDER
        }
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with mock.patch.object(config, "CLIENTS_DIR", tmp), mock.patch.dict(
            "backend.pipeline.STEP_RUNNERS", fakes
        ), mock.patch(
            "backend.context_summary.generate_context_summary", return_value=""
        ):
            runner.run_pipeline("c", "topic", verbose=False)
        self.assertNotIn("content_to_cms", calls)
        self.assertEqual(calls, [n for n in STEP_ORDER if n != "content_to_cms"])


class _FakeWebflow(BaseHTTPRequestHandler):
    seen: list[dict] = []
    status = 200

    def _handle(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        _FakeWebflow.seen.append(
            {
                "method": self.command,
                "path": self.path,
                "auth": self.headers.get("Authorization"),
                "agent": self.headers.get("User-Agent"),
                "body": body,
            }
        )
        payload = json.dumps({"id": "abc123"} if self.status == 200 else {"message": "nope"})
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload.encode())

    do_POST = do_PATCH = _handle

    def log_message(self, *args):
        pass


class WebflowClientTests(unittest.TestCase):
    def setUp(self):
        _FakeWebflow.seen = []
        _FakeWebflow.status = 200
        self.server = HTTPServer(("127.0.0.1", 0), _FakeWebflow)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        base = mock.patch.object(
            webflow, "API_BASE", f"http://127.0.0.1:{self.server.server_port}/v2"
        )
        base.start()
        self.addCleanup(base.stop)
        env = mock.patch.dict(
            "os.environ", {"WEBFLOW_TOKEN": "secret-token", "WEBFLOW_COLLECTION_ID": "col-9"}
        )
        env.start()
        self.addCleanup(env.stop)

    def test_create_sends_a_draft_to_the_right_collection(self):
        item_id = webflow.create_draft_item({"name": "T", "slug": "t"})
        req = _FakeWebflow.seen[0]
        self.assertEqual(item_id, "abc123")
        self.assertEqual((req["method"], req["path"]), ("POST", "/v2/collections/col-9/items"))
        self.assertEqual(req["auth"], "Bearer secret-token")
        self.assertEqual(req["agent"], "contentflow-webflow/1.0")
        self.assertEqual(
            req["body"],
            {"isArchived": False, "isDraft": True, "fieldData": {"name": "T", "slug": "t"}},
        )

    def test_update_patches_only_field_data(self):
        webflow.update_item("item-5", {"name": "New"})
        req = _FakeWebflow.seen[0]
        self.assertEqual(
            (req["method"], req["path"]), ("PATCH", "/v2/collections/col-9/items/item-5")
        )
        self.assertEqual(req["body"], {"fieldData": {"name": "New"}})

    def test_http_error_carries_status_and_message(self):
        _FakeWebflow.status = 404
        with self.assertRaises(webflow.WebflowError) as ctx:
            webflow.update_item("gone", {"name": "x"})
        self.assertEqual(ctx.exception.status, 404)
        self.assertIn("404", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
