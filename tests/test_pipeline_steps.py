from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

from backend.pipeline import STEP_ORDER, STEP_RUNNERS
from backend.pipeline_steps import ARTICLE_STEP_ORDER
from backend import prompts
from backend import steps
from backend import word_count_enforce
from backend import writing_format_enforce
from backend.prompt_cache import CachedPrompt


class PipelineStepRegistryTests(unittest.TestCase):
    def test_canonical_order_matches_pipeline_module(self):
        self.assertEqual(STEP_ORDER, ARTICLE_STEP_ORDER)

    def test_every_step_has_a_runner(self):
        self.assertEqual(set(STEP_RUNNERS.keys()), set(ARTICLE_STEP_ORDER))

    def test_steps_module_numbering_matches_order(self):
        for index, name in enumerate(ARTICLE_STEP_ORDER, start=1):
            self.assertEqual(steps._PIPELINE_STEP_NUM[name], index)

    def test_meta_seo_runs_before_final_output(self):
        self.assertLess(
            ARTICLE_STEP_ORDER.index("meta_seo"),
            ARTICLE_STEP_ORDER.index("final_output"),
        )


class FinalOutputNoRewriteTests(unittest.TestCase):
    def test_final_output_does_not_call_claude(self):
        fact = (
            "---FACT CHECK START---\n"
            "report\n"
            "---CORRECTED ARTICLE START---\n"
            "# Hello\n\nBody sentence here for publish.\n"
            "---CORRECTED ARTICLE END---\n"
            "---FACT CHECK END---\n"
        )

        def fake_enforce(text, client_id, run_id, *, allow_llm_repair=False):
            return text

        with patch("backend.steps._chat_complete") as chat, patch(
            "backend.steps.artifacts.save_artifact"
        ) as save, patch(
            "backend.steps._load_prior_artifact", return_value=""
        ), patch(
            "backend.steps.final_output_enforce.enforce_final_output",
            side_effect=fake_enforce,
        ):
            out = steps.run_step_7("client", "run", previous_artifact=fact)
        chat.assert_not_called()
        save.assert_called_once()
        self.assertIn("Hello", out)
        self.assertIn("---FINAL OUTPUT START---", out)

    def test_fact_check_prompt_asks_for_corrections_not_article(self):
        self.assertIn("---CORRECTIONS START---", prompts.FACT_CHECK_PROMPT)
        self.assertNotIn("---CORRECTED ARTICLE START---", prompts.FACT_CHECK_PROMPT)

    def test_hard_gates_run_on_final_not_draft(self):
        from backend import final_output_enforce

        self.assertNotIn(
            "enforce_article_gates", inspect.getsource(steps.run_step_5)
        )
        self.assertNotIn("_chat_complete", inspect.getsource(steps.run_step_7))
        self.assertIn(
            "enforce_article_gates",
            inspect.getsource(final_output_enforce.enforce_final_output),
        )


class OutputTokenBudgetTests(unittest.TestCase):
    def test_brief_outline_audit_meta_below_draft_ceiling(self):
        draft = steps.max_tokens_for_step("draft", word_count_target=2500)
        self.assertGreaterEqual(draft, 6000)
        self.assertLessEqual(draft, 8192)
        for name in (
            "topic_card",
            "assignment_brief",
            "outline",
            "research_audit",
            "meta_seo",
            "fact_check",
        ):
            cap = steps.max_tokens_for_step(name)
            self.assertLess(cap, 4000, name)
            self.assertLess(cap, draft, name)

    def test_section_repair_cap_is_not_a_full_article(self):
        self.assertLessEqual(word_count_enforce._max_tokens_for_target(2000), 2200)
        self.assertLessEqual(word_count_enforce._max_tokens_for_target(None), 2200)

    def test_repairs_ask_for_snippets_not_the_article(self):
        self.assertIn("JSON array", writing_format_enforce._SENTENCE_REPAIR_SYSTEM)
        self.assertIn("Do not rewrite the rest of the article", writing_format_enforce._SENTENCE_REPAIR_SYSTEM)
        trim_src = inspect.getsource(word_count_enforce.trim_section_body)
        self.assertIn("Output ONLY the section", trim_src)
        self.assertIn("ONLY this article section", trim_src)


class SupportingPostsBatchTests(unittest.TestCase):
    def test_submits_batch_instead_of_blocking_chat(self):
        cached = CachedPrompt("sys", "shared", "unique", "sess", step_label="supporting")
        with patch("backend.steps._load_prior_artifact", return_value="# Draft\n"), patch(
            "backend.steps._run_language", return_value="en"
        ), patch(
            "backend.steps._editorial_notices_for_run", return_value=""
        ), patch(
            "backend.steps._cached_prompt", return_value=cached
        ), patch(
            "backend.steps.claude.submit_cached_batch",
            return_value={"id": "batch_abc", "provider": "openrouter"},
        ) as submit, patch(
            "backend.steps._chat_complete"
        ) as chat, patch(
            "backend.steps.artifacts.save_artifact"
        ) as save, patch(
            "backend.steps._spawn_supporting_posts_poller"
        ) as spawn, patch(
            "backend.steps.config.SUPPORTING_POSTS_USE_BATCH", True
        ):
            out = steps.run_supporting_posts("client", "run1")
        submit.assert_called_once()
        self.assertEqual(submit.call_args.kwargs["max_tokens"], 6000)
        chat.assert_not_called()
        spawn.assert_called_once()
        save.assert_called_once()
        self.assertIn("batch_abc", out)
        self.assertIn("SUPPORTING POSTS", out.upper())

    def test_falls_back_to_sync_when_batch_submit_fails(self):
        cached = CachedPrompt("sys", "shared", "unique", "sess", step_label="supporting")
        with patch("backend.steps._load_prior_artifact", return_value="# Draft\n"), patch(
            "backend.steps._run_language", return_value="en"
        ), patch(
            "backend.steps._editorial_notices_for_run", return_value=""
        ), patch(
            "backend.steps._cached_prompt", return_value=cached
        ), patch(
            "backend.steps.claude.submit_cached_batch",
            side_effect=RuntimeError("no batch"),
        ), patch(
            "backend.steps._chat_complete", return_value="## Cluster overview\n"
        ) as chat, patch(
            "backend.steps._finish_supporting_posts_text",
            side_effect=lambda text, **kwargs: text,
        ), patch(
            "backend.steps.config.SUPPORTING_POSTS_USE_BATCH", True
        ):
            out = steps.run_supporting_posts("client", "run1")
        chat.assert_called_once()
        self.assertIn("Cluster overview", out)


if __name__ == "__main__":
    unittest.main()
