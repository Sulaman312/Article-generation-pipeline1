"""Language context, free preflight diagnostics and rejected-output retention.

Diagnostics are sidecars, never successful artifacts or inputs for later steps.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import asdict
import json
import logging

from . import artifacts, editorial_input, french_language, job_control

logger = logging.getLogger(__name__)
active_language: ContextVar[str] = ContextVar("article_language", default="en")
active_glossary: ContextVar = ContextVar("article_glossary", default=None)
repair_budget: ContextVar[int | None] = ContextVar("french_repair_budget", default=None)
candidate_output: ContextVar[str] = ContextVar("candidate_output", default="")


def save_diagnostic(client_id: str, run_id: str, step_name: str, report: dict) -> None:
    step_name = artifacts._validate_step_name(step_name)
    artifacts._write_json_atomic(
        artifacts.get_run_dir(client_id, run_id) / f"{step_name}.quality.json", report
    )


def load_diagnostic(client_id: str, run_id: str, step_name: str) -> dict:
    step_name = artifacts._validate_step_name(step_name)
    path = artifacts.get_run_dir(client_id, run_id) / f"{step_name}.quality.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def preflight(client_id: str, run_id: str, manual: dict) -> list[dict]:
    """Scan all effective French templates and supplied inputs without paid calls.

    English in source material is diagnostic, not a reason to reject a French run.
    """
    from . import prompts
    from pathlib import Path

    glossary = french_language.load_glossary(client_id)
    sources = {}
    for path in (Path(prompts.__file__).parent / "fr").glob("*.md"):
        sources[f"template:{path.name}"] = french_language.localize_model_input(
            (Path(prompts.__file__).parent / "french_common.md").read_text(encoding="utf-8")
            + "\n" + path.read_text(encoding="utf-8"))
    sources.update({f"input:{k}": v for k, v in manual.items() if isinstance(v, str)})
    for filename in artifacts.writable_context_filenames(client_id):
        if filename and filename != french_language.GLOSSARY_FILENAME:
            sources[f"context:{filename}"] = artifacts.read_context_file(client_id, filename) or ""
    findings = []
    for source, text in sources.items():
        for issue in french_language.scan_french(text, glossary=glossary, spelling=False, structural=True):
            findings.append({"source": source, **asdict(issue)})
    for finding in findings:
        logger.warning("French preflight %s: %s (%s)", finding["source"], finding["term"], finding["severity"])
    save_diagnostic(client_id, run_id, "topic_card", {"kind": "preflight", "issues": findings})
    return findings


def execute_step(runner, client_id: str, run_id: str, step_name: str, previous: str = ""):
    manifest = artifacts.read_run_manifest(client_id, run_id) or {}
    manual = manifest.get("manual_inputs") or {"Topic": manifest.get("topic", "")}
    lang = editorial_input.article_language_from_manual(manual)
    token = active_language.set(lang)
    glossary_token = active_glossary.set(french_language.load_glossary(client_id) if lang == "fr" else None)
    candidate_token = candidate_output.set("")
    budget_token = repair_budget.set(2)
    try:
        job_control.raise_if_cancelled()
        if lang == "fr" and step_name == "topic_card":
            preflight(client_id, run_id, manual)
        if step_name != "topic_card":
            save_diagnostic(client_id, run_id, step_name, {})
        try:
            output = runner(client_id, run_id, previous)
        except job_control.JobCancelled:
            raise
        except Exception as exc:
            content = getattr(exc, "text", "") or candidate_output.get()
            if not content:
                raise
            save_diagnostic(client_id, run_id, step_name, {
                "kind": "rejected", "check": "fact_check" if step_name == "fact_check" else "french", "content": content,
                "original_content": getattr(exc, "original_text", content),
                "issues": [asdict(i) for i in getattr(exc, "issues", [])], "message": str(exc),
            })
            raise
        # Clear a stale rejection only after a successful replacement.
        if step_name != "topic_card":
            save_diagnostic(client_id, run_id, step_name, {})
        return output
    finally:
        repair_budget.reset(budget_token)
        candidate_output.reset(candidate_token)
        active_glossary.reset(glossary_token)
        active_language.reset(token)
