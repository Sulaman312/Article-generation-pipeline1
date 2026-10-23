"""Canonical article pipeline step order (shared across backend modules)."""

ARTICLE_STEP_ORDER = [
    "topic_card",
    "serp_research",
    "research",
    "source_research",
    "assignment_brief",
    "outline",
    "draft",
    "fact_check",
    "meta_seo",
    "final_output",
    "content_to_cms",
]

# Steps that run only when a user runs them (never in the automatic full-pipeline loop).
MANUAL_ONLY_STEPS = frozenset({"content_to_cms"})
