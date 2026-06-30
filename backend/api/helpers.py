"""Shared validation and manifest helpers for HTTP routes."""

import json
import re
from pathlib import Path

from flask import jsonify

from backend import artifacts
from backend import config
from backend.pipeline import STEP_ORDER
from backend.pipelines import resolve_pipeline_id, upgrade_manifest

_RUN_ID_PATTERN = re.compile(r"^[a-zA-Z0-9._-]+$")


def safe_run_id(run_id: str):
    if not run_id or not str(run_id).strip():
        return False, ("run_id is required", 400)
    rid = str(run_id).strip()
    if ".." in rid or not _RUN_ID_PATTERN.match(rid):
        return False, ("invalid run_id", 400)
    return True, None


def reject_run_id(run_id: str):
    ok, err = safe_run_id(run_id)
    if not ok:
        return jsonify(detail=err[0]), err[1]
    return None


def safe_client_id(client_id: str):
    if not client_id or not client_id.strip():
        return False, ("client_id is required", 400)
    if "/" in client_id or "\\" in client_id or ".." in client_id:
        return False, ("invalid client_id", 400)
    if client_id.strip().startswith("_"):
        return False, ("invalid client_id", 400)
    return True, None


def reject_client(client_id: str):
    ok, err = safe_client_id(client_id)
    if not ok:
        return jsonify(detail=err[0]), err[1]
    return None


def load_manifest(client_id: str, run_id: str) -> dict:
    manifest_path = (
        Path(config.CLIENTS_DIR) / client_id / "runs" / run_id / "run_manifest.json"
    )
    if not manifest_path.is_file():
        return {
            "topic": "",
            "statuses": {name: "pending" for name in STEP_ORDER},
        }
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {
            "topic": "",
            "statuses": {name: "pending" for name in STEP_ORDER},
        }

    data, changed = upgrade_manifest(raw)
    if changed:
        artifacts.save_run_manifest(
            client_id,
            run_id,
            data.get("topic") or "untitled",
            data.get("statuses") or {},
            pipeline_id=resolve_pipeline_id(data),
            manual_inputs=data.get("manual_inputs")
            if isinstance(data.get("manual_inputs"), dict)
            else None,
            target_word_count=data.get("target_word_count")
            if isinstance(data.get("target_word_count"), int)
            else None,
            step_timings=data.get("step_timings")
            if isinstance(data.get("step_timings"), dict)
            else None,
            context_summary=data.get("context_summary")
            if isinstance(data.get("context_summary"), str)
            else None,
        )
    return data


def list_workspace_dir_names(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    return sorted(
        p.name
        for p in root.iterdir()
        if p.is_dir() and not p.name.startswith("_")
    )
