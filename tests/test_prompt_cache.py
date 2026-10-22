"""Phase-2 prompt caching assembly tests (no live API calls)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
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
        self.assertIn("BRAND VOICE RULES", a)
        self.assertIn("WRITING FORMAT GUIDELINES", a)
        self.assertIn("content clusters", a.lower())
        # Nothing run-specific in system
        self.assertNotIn(self.run_id, a)
        self.assertNotIn("2026-10-18", a)

    def test_shared_docs_fixed_order_and_stable_headers(self):
        block = prompt_cache.build_shared_documents_block(self.client_id, self.run_id)
        positions = [block.index(f"---{label}---") for label, _ in prompt_cache.SHARED_DOC_SPECS]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("Topic A", block)
        self.assertIn("Brief body", block)
        self.assertNotIn("STEP ", block)
        self.assertNotIn(self.run_id, block)

    def test_missing_docs_use_stable_placeholder(self):
        other_run = "empty_run"
        (self.root / self.client_id / "runs" / other_run).mkdir(parents=True)
        block = prompt_cache.build_shared_documents_block(self.client_id, other_run)
        self.assertEqual(block.count("[not available yet]"), len(prompt_cache.SHARED_DOC_SPECS))

    def test_unique_block_holds_step_prompt_and_varying_bits(self):
        prompt = prompt_cache.build_cached_prompt(
            client_id=self.client_id,
            run_id=self.run_id,
            step_prompt="STEP PROMPT TEXT",
            unique_suffix=f"run={self.run_id}\noutline only here",
            step_label="Step 6 (outline)",
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
        )
        sys_blocks = prompt.system_blocks()
        user_blocks = prompt.user_content_blocks()
        self.assertEqual(sys_blocks[0]["cache_control"]["type"], "ephemeral")
        self.assertEqual(sys_blocks[0]["cache_control"].get("ttl"), config.PROMPT_CACHE_TTL)
        self.assertEqual(user_blocks[0]["cache_control"]["type"], "ephemeral")
        self.assertNotIn("cache_control", user_blocks[1])
        self.assertEqual(len(user_blocks), 2)

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


if __name__ == "__main__":
    unittest.main()
