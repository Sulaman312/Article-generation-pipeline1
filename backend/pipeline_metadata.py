"""UI metadata for article pipeline steps (order from ``pipeline_steps``)."""

from __future__ import annotations

from backend.pipeline_steps import ARTICLE_STEP_ORDER

_STEP_UI: dict[str, dict[str, str]] = {
    "topic_card": {
        "label": "Topic Card",
        "matrixLabel": "Plan & topic",
        "matrixCol": "TC",
    },
    "serp_research": {
        "label": "SERP Research",
        "matrixLabel": "Search landscape",
        "matrixCol": "SR",
    },
    "research": {
        "label": "SERP Analysis & Gaps",
        "matrixLabel": "Gap analysis",
        "matrixCol": "SA",
    },
    "assignment_brief": {
        "label": "Assignment Brief",
        "matrixLabel": "Editorial brief",
        "matrixCol": "BR",
    },
    "outline": {
        "label": "Outline",
        "matrixLabel": "Article outline",
        "matrixCol": "OL",
    },
    "draft": {
        "label": "Draft",
        "matrixLabel": "First draft",
        "matrixCol": "DR",
    },
    "fact_check": {
        "label": "Fact Check (web + editor)",
        "matrixLabel": "Review & accuracy",
        "matrixCol": "FC",
    },
    "meta_seo": {
        "label": "Meta Title & Description",
        "matrixLabel": "SEO meta tags",
        "matrixCol": "MS",
    },
    "final_output": {
        "label": "Final Output",
        "matrixLabel": "Ready to publish",
        "matrixCol": "FO",
    },
}


def article_pipeline_steps() -> list[dict[str, str | int]]:
    """Return ordered step metadata for the article pipeline API + UI."""
    rows: list[dict[str, str | int]] = []
    for index, key in enumerate(ARTICLE_STEP_ORDER, start=1):
        ui = _STEP_UI.get(key)
        if not ui:
            raise KeyError(f"Missing UI metadata for pipeline step {key!r}")
        rows.append({"key": key, "index": index, **ui})
    return rows
