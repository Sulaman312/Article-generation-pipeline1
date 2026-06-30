"""Registered pipeline steps shared by HTTP API (mirrors runner / manifest order)."""

from . import steps

STEP_RUNNERS = {
    "topic_card": steps.run_step_1,
    "serp_research": steps.run_serp_research,
    "research": steps.run_step_3,
    "assignment_brief": steps.run_step_2,
    "outline": steps.run_step_4,
    "draft": steps.run_step_5,
    "fact_check": steps.run_step_6,
    "final_output": steps.run_step_7,
}

STEP_ORDER = [
    "topic_card",
    "serp_research",
    "research",
    "assignment_brief",
    "outline",
    "draft",
    "fact_check",
    "final_output",
]
