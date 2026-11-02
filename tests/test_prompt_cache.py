"""Phase-2 prompt caching assembly tests (no live API calls)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import config
from backend import prompt_cache
from backend.integrations import anthropic as claude
from backend.prompt_cache import CachedPrompt


class PromptCacheAssemblyTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        self.client_id = "cache_test_client"
        self.run_id = "2026-10-18_12-00-00"
        ctx = self.root / self.client_id / "context"
        ctx.mkdir(parents=True)
        (ctx / "context.md").write_text(
            "Company Name: CacheCo\nWebsite: https://example.com\n",
            encoding="utf-8",
        )
        (ctx / "personas.md").write_text(
            '## Persona 1: "Ops Lead"\n',
            encoding="utf-8",
        )
        (ctx / "brand_voice.md").write_text(
            "Confident, Not Arrogant\nInstruction text\nRight: good\nWrong: bad\n",
            encoding="utf-8",
        )
        (ctx / "writing_guidelines.md").write_text(
            'Words like "leverage" and "synergy" are overused.\n',
            encoding="utf-8",
        )
        (ctx / "cta_guidelines.md").write_text(
            "### 1. CTA Philosophy\nBe helpful.\n\n"
            '✅ Recommended Phrases\n"Talk to us"\n',
            encoding="utf-8",
        )
        (ctx / "internal_links.md").write_text(
            "## CLUSTER 1\nTitle: Automation basics\n\n## CLUSTER 2\nTitle: ROI guides\n",
            encoding="utf-8",
        )
        run_dir = self.root / self.client_id / "runs" / self.run_id
        run_dir.mkdir(parents=True)
        (run_dir / "topic_card.md").write_text("---TOPIC CARD---\nTopic A\n", encoding="utf-8")
        (run_dir / "research.md").write_text("---SERP---\nGaps\n", encoding="utf-8")
        (run_dir / "atp_topic_research.md").write_text("ATP body\n", encoding="utf-8")
        (run_dir / "paa_faq_research.md").write_text("PAA body\n", encoding="utf-8")
        (run_dir / "research_audit.md").write_text("Audit body\n", encoding="utf-8")
        (run_dir / "assignment_brief.md").write_text("Brief body\n", encoding="utf-8")

        self._clients_dir = config.CLIENTS_DIR
        config.CLIENTS_DIR = self.root
        prompt_cache.clear_warmed_sessions()

    def tearDown(self):
        config.CLIENTS_DIR = self._clients_dir
        prompt_cache.clear_warmed_sessions()
        self._tmpdir.cleanup()

    def test_system_identical_across_steps(self):
        a = prompt_cache.build_client_system_prompt(self.client_id)
        b = prompt_cache.build_client_system_prompt(self.client_id)
        self.assertEqual(a, b)
        self.assertIn("=== context.md ===", a)
        self.assertIn("=== french_glossary.md ===", a)
        self.assertIn("BRAND VOICE RULES", a)
        self.assertIn("WRITING FORMAT GUIDELINES", a)
        self.assertIn("content clusters", a.lower())
        # Nothing run-specific in system
        self.assertNotIn(self.run_id, a)
        self.assertNotIn("2026-10-18", a)

    def test_shared_docs_fixed_order_and_stable_headers(self):
        block = prompt_cache.build_shared_documents_block(
            self.client_id, self.run_id, "research_audit"
        )
        specs = prompt_cache.STEP_SHARED_DOCS["research_audit"]
        positions = [block.index(f"---{label}---") for label, _ in specs]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("Topic A", block)
        self.assertIn("ATP body", block)
        self.assertNotIn("Brief body", block)
        self.assertNotIn("STEP ", block)
        self.assertNotIn(self.run_id, block)

    def test_missing_docs_are_omitted(self):
        other_run = "empty_run"
        (self.root / self.client_id / "runs" / other_run).mkdir(parents=True)
        block = prompt_cache.build_shared_documents_block(
            self.client_id, other_run, "outline"
        )
        self.assertEqual(block.strip(), "")

    def test_unique_block_holds_step_prompt_and_varying_bits(self):
        prompt = prompt_cache.build_cached_prompt(
            client_id=self.client_id,
            run_id=self.run_id,
            step_prompt="STEP PROMPT TEXT",
            unique_suffix=f"run={self.run_id}\noutline only here",
            step_label="Step 6 (outline)",
            step_name="outline",
        )
        self.assertIn("STEP PROMPT TEXT", prompt.unique_text)
        self.assertIn(self.run_id, prompt.unique_text)
        self.assertNotIn(self.run_id, prompt.system_text)
        self.assertNotIn(self.run_id, prompt.shared_docs_text)
        self.assertNotIn("STEP PROMPT TEXT", prompt.shared_docs_text)

    def test_cache_control_breakpoint_on_system_and_shared_user_block(self):
        prompt = prompt_cache.build_cached_prompt(
            client_id=self.client_id,
            run_id=self.run_id,
            step_prompt="Do the outline.",
            unique_suffix="notices",
            step_label="outline",
            step_name="outline",
        )
        sys_blocks = prompt.system_blocks()
        user_blocks = prompt.user_content_blocks()
        self.assertGreaterEqual(len(sys_blocks), 2)
        self.assertIn("=== context.md ===", sys_blocks[0]["text"])
        self.assertIn("=== french_glossary.md ===", sys_blocks[0]["text"])
        self.assertNotIn("=== brand_voice.md ===", sys_blocks[0]["text"])
        self.assertIn("=== brand_voice.md ===", sys_blocks[1]["text"])
        self.assertIn("BRAND VOICE RULES", sys_blocks[1]["text"])
        self.assertEqual(sys_blocks[0]["cache_control"]["type"], "ephemeral")
        self.assertEqual(sys_blocks[0]["cache_control"].get("ttl"), config.PROMPT_CACHE_TTL)
        self.assertEqual(sys_blocks[1]["cache_control"]["type"], "ephemeral")
        self.assertEqual(user_blocks[0]["cache_control"]["type"], "ephemeral")
        self.assertNotIn("cache_control", user_blocks[1])
        self.assertEqual(len(user_blocks), 2)
        self.assertNotIn(self.run_id, prompt.workspace_text)

    def test_french_rules_stay_out_of_workspace_file_block(self):
        en = prompt_cache.build_cached_prompt(
            client_id=self.client_id,
            run_id=self.run_id,
            step_prompt="Draft the article.",
            unique_suffix="notices",
            step_label="draft",
            lang="en",
            step_name="draft",
        )
        fr = prompt_cache.build_cached_prompt(
            client_id=self.client_id,
            run_id=self.run_id,
            step_prompt="Draft the article.",
            unique_suffix="notices",
            step_label="draft",
            lang="fr",
            step_name="draft",
        )
        self.assertEqual(en.workspace_text, fr.workspace_text)
        self.assertIn("RÈGLE DE LANGUE", fr.system_text)
        self.assertNotIn("RÈGLE DE LANGUE", en.system_text)
        self.assertNotIn("RÈGLE DE LANGUE", fr.workspace_text)

    def test_lean_steps_omit_brand_voice_and_cta(self):
        for step_name in (
            "topic_card",
            "research",
            "research_audit",
            "meta_seo",
            "fact_check",
        ):
            prompt = prompt_cache.build_cached_prompt(
                client_id=self.client_id,
                run_id=self.run_id,
                step_prompt="Do the step.",
                unique_suffix="notices",
                step_label=step_name,
                step_name=step_name,
            )
            self.assertNotIn("brand_voice.md", prompt.workspace_text, step_name)
            self.assertNotIn("cta_guidelines.md", prompt.workspace_text, step_name)
            self.assertNotIn("BRAND VOICE RULES", prompt.system_text, step_name)
            self.assertNotIn("WRITING FORMAT GUIDELINES", prompt.system_text, step_name)
            self.assertNotIn("=== brand_voice.md ===", prompt.system_text, step_name)
            self.assertIn("=== context.md ===", prompt.workspace_text)

    def test_outline_gets_brief_not_raw_serp(self):
        prompt = prompt_cache.build_cached_prompt(
            client_id=self.client_id,
            run_id=self.run_id,
            step_prompt="Do the outline.",
            unique_suffix="notices",
            step_label="outline",
            step_name="outline",
        )
        self.assertIn("Brief body", prompt.shared_docs_text)
        self.assertNotIn("---SERP ANALYSIS---", prompt.shared_docs_text)
        self.assertNotIn("ATP body", prompt.shared_docs_text)
        self.assertNotIn("PAA body", prompt.shared_docs_text)

    def test_research_summary_keeps_gaps_and_urls_not_raw_dumps(self):
        run_dir = self.root / self.client_id / "runs" / self.run_id
        (run_dir / "research.md").write_text(
            "## Snapshot\nWinning guides are practical.\n\n"
            "## Content gaps to own\nGAP: missing cost section\n\n"
            "## External sources to cite\n- NIST — https://example.gov/nist\n",
            encoding="utf-8",
        )
        (run_dir / "research_audit.md").write_text(
            "## Audit summary\n- OVERALL: PASS WITH NOTES\n\n"
            "## Approved FAQ questions\n1. How long does setup take?\n",
            encoding="utf-8",
        )
        (run_dir / "atp_topic_research.md").write_text(
            "Huge ATP dump that must not be forwarded wholesale.\n",
            encoding="utf-8",
        )
        summary = prompt_cache.build_research_summary(self.client_id, self.run_id)
        self.assertIn("Winning guides are practical", summary)
        self.assertIn("missing cost section", summary)
        self.assertIn("https://example.gov/nist", summary)
        self.assertIn("How long does setup take?", summary)
        self.assertNotIn("Huge ATP dump", summary)
        brief = prompt_cache.build_shared_documents_block(
            self.client_id, self.run_id, "assignment_brief"
        )
        self.assertIn("RESEARCH SUMMARY", brief)
        self.assertNotIn("Huge ATP dump", brief)

    def test_session_id_stable_per_run(self):
        self.assertEqual(
            prompt_cache.session_id_for_run(self.client_id, self.run_id),
            f"article:{self.client_id}:{self.run_id}",
        )

    def test_warm_cache_then_map_runs_first_before_rest(self):
        order: list[str] = []

        def fake_call(p: CachedPrompt) -> str:
            order.append(p.step_label)
            return p.step_label

        prompts = [
            CachedPrompt("sys", "shared", "u1", "sess", step_label="first"),
            CachedPrompt("sys", "shared", "u2", "sess", step_label="second"),
            CachedPrompt("sys", "shared", "u3", "sess", step_label="third"),
        ]
        out = claude.warm_cache_then_map(prompts, call=fake_call, max_workers=2)
        self.assertEqual(order[0], "first")
        self.assertEqual(set(order[1:]), {"second", "third"})
        self.assertEqual(set(out), {"first", "second", "third"})


class PromptCacheUsageParseTests(unittest.TestCase):
    def test_usage_from_anthropic_style(self):
        class U:
            cache_read_input_tokens = 9000
            cache_creation_input_tokens = 100
            input_tokens = 9500

        read, write, inp = claude._usage_cache_fields(U())
        self.assertEqual(read, 9000)
        self.assertEqual(write, 100)
        self.assertEqual(inp, 9500)

    def test_usage_from_openrouter_details(self):
        usage = {
            "prompt_tokens": 10339,
            "prompt_tokens_details": {
                "cached_tokens": 10318,
                "cache_write_tokens": 0,
            },
        }
        read, write, inp = claude._usage_cache_fields(usage)
        self.assertEqual(read, 10318)
        self.assertEqual(write, 0)
        self.assertEqual(inp, 10339)

    def test_stream_kwargs_attach_cache_control_and_openrouter_usage(self):
        prompt = CachedPrompt(
            system_text="Brand rules.",
            shared_docs_text="Shared docs " * 40,
            unique_text="Do the step.",
            session_id="article:cache_client:2026-11-02_10-00-00",
            step_label="draft",
            workspace_text="Workspace files " * 40,
        )
        with patch.object(
            claude.config, "ANTHROPIC_BASE_URL", "https://openrouter.ai/api"
        ), patch.object(claude.config, "PROMPT_CACHE_TTL", "1h"):
            kwargs = claude._stream_kwargs_for_cached(
                prompt,
                model="anthropic/claude-sonnet-4.6",
                max_tok=1800,
                temp=0.5,
            )
        self.assertGreaterEqual(claude._count_cache_breakpoints(prompt), 2)
        self.assertEqual(kwargs["system"][0]["cache_control"]["type"], "ephemeral")
        self.assertEqual(kwargs["system"][0]["cache_control"]["ttl"], "1h")
        shared = kwargs["messages"][0]["content"][0]
        self.assertEqual(shared["cache_control"]["ttl"], "1h")
        extra = kwargs["extra_body"]
        self.assertEqual(extra["session_id"], prompt.session_id)
        self.assertTrue(extra["stream_options"]["include_usage"])
        self.assertTrue(extra["usage"]["include"])

    def test_log_cache_usage_records_hit(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        try:
            with patch.object(claude.config, "CLIENTS_DIR", root):
                claude._log_cache_usage(
                    "draft",
                    {
                        "prompt_tokens": 10000,
                        "prompt_tokens_details": {
                            "cached_tokens": 9000,
                            "cache_write_tokens": 0,
                        },
                    },
                    session_id="article:hit_client:run1",
                )
            self.assertIsNotNone(claude.LAST_CACHE_USAGE)
            self.assertTrue(claude.LAST_CACHE_USAGE["hit"])
            self.assertEqual(claude.LAST_CACHE_USAGE["cache_read"], 9000)
            log_path = root / "hit_client" / "runs" / "run1" / "cache_usage.jsonl"
            self.assertTrue(log_path.is_file())
            self.assertIn("cache_read", log_path.read_text(encoding="utf-8"))
        finally:
            tmp.cleanup()

    def test_extract_batch_text_from_messages_and_responses(self):
        messages_batch = {
            "id": "batch_1",
            "status": "completed",
            "results": [
                {
                    "custom_id": "supporting-run1",
                    "response": {
                        "status_code": 200,
                        "body": {
                            "content": [{"type": "text", "text": "Post S1 body"}],
                        },
                    },
                    "error": None,
                }
            ],
        }
        self.assertEqual(
            claude.extract_batch_text(messages_batch, "supporting-run1"),
            "Post S1 body",
        )
        responses_batch = {
            "id": "batch_2",
            "status": "completed",
            "results": [
                {
                    "custom_id": "supporting-run1",
                    "response": {
                        "body": {
                            "status": "completed",
                            "output": [
                                {
                                    "type": "message",
                                    "content": [
                                        {"type": "output_text", "text": "Post S2 body"}
                                    ],
                                }
                            ],
                        }
                    },
                    "error": None,
                }
            ],
        }
        self.assertEqual(
            claude.extract_batch_text(responses_batch, "supporting-run1"),
            "Post S2 body",
        )

    def test_batch_message_body_keeps_cache_control(self):
        prompt = CachedPrompt(
            system_text="Brand rules.",
            shared_docs_text="Shared docs " * 40,
            unique_text="Write posts.",
            session_id="article:c:r",
            step_label="supporting_posts",
            workspace_text="Workspace files " * 40,
        )
        with patch.object(
            claude.config, "ANTHROPIC_BASE_URL", "https://openrouter.ai/api"
        ), patch.object(claude.config, "PROMPT_CACHE_TTL", "1h"):
            body = claude.message_body_for_cached(
                prompt, max_tokens=6000, temperature=0.55, include_model=False
            )
        self.assertEqual(body["system"][0]["cache_control"]["ttl"], "1h")
        self.assertEqual(body["messages"][0]["content"][0]["cache_control"]["type"], "ephemeral")
        self.assertEqual(body["session_id"], "article:c:r")
        self.assertNotIn("model", body)


if __name__ == "__main__":
    unittest.main()
