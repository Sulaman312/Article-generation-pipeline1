"""Helpers for step order and resolving pipeline input."""

from __future__ import annotations

from .pipeline import STEP_ORDER as _DEFAULT_STEP_ORDER

# Publishing / cluster sidecars — not article LLM input for later content steps.
_PUBLISHING_SIDECAR_STEPS = frozenset({"meta_seo"})
_CLUSTER_SIDECAR_STEPS = frozenset({"supporting_posts"})


def _is_article_input_for_step(step_name: str, candidate: str) -> bool:
    if candidate in _CLUSTER_SIDECAR_STEPS and step_name in (
        "fact_check",
        "meta_seo",
        "final_output",
    ):
        return False
    if step_name == "final_output" and candidate in _PUBLISHING_SIDECAR_STEPS:
        return False
    return True


def input_source_for_step(
    step_name: str,
    statuses: dict[str, str],
    *,
    step_order: list[str] | None = None,
) -> tuple[str | None, str]:
    order = step_order or _DEFAULT_STEP_ORDER
    try:
        idx = order.index(step_name)
    except ValueError:
        return None, "blocked"

    for i in range(idx - 1, -1, -1):
        prev = order[i]
        if not _is_article_input_for_step(step_name, prev):
            continue
        st = statuses.get(prev, "pending")
        if st == "done":
            return prev, "artifact"
        if st == "skipped":
            continue
        return None, "blocked"

    return None, "topic"


def can_run_step(
    step_name: str,
    statuses: dict[str, str],
    *,
    has_topic: bool,
    step_order: list[str] | None = None,
) -> bool:
    _src, kind = input_source_for_step(step_name, statuses, step_order=step_order)
    if kind == "blocked":
        return False
    if kind == "topic":
        return has_topic
    return True
