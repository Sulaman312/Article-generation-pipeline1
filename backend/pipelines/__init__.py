"""Article pipeline registry (standalone article service)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

RunnerFn = Callable[[str, str, str], str]


@dataclass(frozen=True)
class PipelineSpec:
    pipeline_id: str
    step_order: list[str]
    step_runners: dict[str, RunnerFn]


def resolve_pipeline_id(manifest: dict | None) -> str:
    return "article"


def upgrade_manifest(manifest: dict) -> tuple[dict, bool]:
    if not isinstance(manifest, dict):
        return manifest, False

    out = dict(manifest)
    changed = out.get("pipeline_id") != "article"
    out["pipeline_id"] = "article"

    pipeline = get_pipeline("article")
    statuses = dict(out.get("statuses") or {})
    for name in pipeline.step_order:
        if name not in statuses:
            statuses[name] = "pending"
            changed = True

    ordered = {name: statuses[name] for name in pipeline.step_order}
    if ordered != out.get("statuses"):
        out["statuses"] = ordered
        changed = True

    return out, changed


def get_pipeline(pipeline_id: str) -> PipelineSpec:
    from backend.pipeline import STEP_ORDER, STEP_RUNNERS

    return PipelineSpec(
        pipeline_id="article",
        step_order=list(STEP_ORDER),
        step_runners=STEP_RUNNERS,
    )
