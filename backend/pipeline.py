"""Registered pipeline steps shared by HTTP API (mirrors runner / manifest order)."""

from . import steps
from .pipeline_steps import ARTICLE_STEP_ORDER

STEP_RUNNERS = {
    "topic_card": steps.run_step_1,
    "serp_research": steps.run_serp_research,
    "research": steps.run_step_3,
    "source_research": steps.run_source_research,
    "assignment_brief": steps.run_step_2,
    "outline": steps.run_step_4,
    "draft": steps.run_step_5,
    "fact_check": steps.run_step_6,
    "final_output": steps.run_step_7,
    "meta_seo": steps.run_meta_seo,
}

STEP_ORDER = list(ARTICLE_STEP_ORDER)
