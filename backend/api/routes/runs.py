import json
import logging
import threading
from datetime import datetime
from pathlib import Path

from flask import jsonify, request, send_from_directory

from backend import artifacts
from backend import config
from backend import editorial_input
from backend import job_control
from backend import mongo_storage
from backend import pipeline_flow
from backend.api.blueprint import api_bp
from backend.api.helpers import (
    load_manifest,
    reject_client,
    reject_run_id,
    reject_step_name,
)
from backend.pipelines import get_pipeline, resolve_pipeline_id

logger = logging.getLogger(__name__)

_STEP_JOBS: dict[tuple[str, str, str], threading.Thread] = {}
_STEP_JOBS_LOCK = threading.Lock()


def _run_has_active_job(client_id: str, run_id: str) -> bool:
    with _STEP_JOBS_LOCK:
        return any(
            cid == client_id and rid == run_id and thread.is_alive()
            for (cid, rid, _step), thread in _STEP_JOBS.items()
        )


def _step_job_alive(client_id: str, run_id: str, step_name: str) -> bool:
    with _STEP_JOBS_LOCK:
        thread = _STEP_JOBS.get((client_id, run_id, step_name))
        return bool(thread and thread.is_alive())


def _reconcile_stale_running_manifest(client_id: str, run_id: str, data: dict) -> dict:
    """Reset steps stuck as running after a server restart or crash."""
    statuses = dict(data.get("statuses") or {})
    timings = dict(data.get("step_timings") or {})
    stale_steps = [
        name
        for name, status in statuses.items()
        if status == "running" and not _step_job_alive(client_id, run_id, name)
    ]
    if not stale_steps:
        return data
    for name in stale_steps:
        statuses[name] = "pending"
        timings.pop(name, None)
    artifacts.save_run_manifest(
        client_id,
        run_id,
        data.get("topic") or "untitled",
        statuses,
        step_timings=timings,
        step_errors=data.get("step_errors") or {},
    )
    return load_manifest(client_id, run_id)


def _run_step_job(
    *,
    key: tuple[str, str, str],
    client_id: str,
    run_id: str,
    step_name: str,
    previous_artifact: str,
    runner_fn,
) -> None:
    cancel_event = job_control.get_or_create_event(key)
    try:
        with job_control.bind_cancel(cancel_event):
            if cancel_event.is_set():
                return
            try:
                runner_fn(client_id, run_id, previous_artifact)
            except job_control.JobCancelled:
                _discard_cancelled_artifact(client_id, run_id, step_name)
                return
            if cancel_event.is_set():
                _discard_cancelled_artifact(client_id, run_id, step_name)
                return
            with _STEP_JOBS_LOCK:
                manifest = load_manifest(client_id, run_id)
                statuses = dict(manifest.get("statuses") or {})
                if statuses.get(step_name) == "running":
                    statuses[step_name] = "done"
                    timings = artifacts.record_step_finished(
                        client_id, run_id, step_name, "done"
                    )
                    errors = dict(manifest.get("step_errors") or {})
                    errors.pop(step_name, None)
                    artifacts.save_run_manifest(
                        client_id,
                        run_id,
                        manifest.get("topic") or "untitled",
                        statuses,
                        step_timings=timings,
                        step_errors=errors,
                    )
    except Exception as exc:
        if cancel_event.is_set() or isinstance(exc, job_control.JobCancelled):
            _discard_cancelled_artifact(client_id, run_id, step_name)
            return
        logger.exception(
            "Background pipeline step failed: %s/%s/%s",
            client_id,
            run_id,
            step_name,
        )
        with _STEP_JOBS_LOCK:
            manifest = load_manifest(client_id, run_id)
            statuses = dict(manifest.get("statuses") or {})
            if statuses.get(step_name) == "running":
                statuses[step_name] = "error"
                timings = artifacts.record_step_finished(
                    client_id, run_id, step_name, "error"
                )
                errors = dict(manifest.get("step_errors") or {})
                errors[step_name] = f"{type(exc).__name__}: {exc}"
                artifacts.save_run_manifest(
                    client_id,
                    run_id,
                    manifest.get("topic") or "untitled",
                    statuses,
                    step_timings=timings,
                    step_errors=errors,
                )
    finally:
        try:
            mongo_storage.sync_cache(delete_missing=True)
        except Exception:
            logger.exception(
                "Could not persist background step result: %s/%s/%s",
                client_id,
                run_id,
                step_name,
            )
        with _STEP_JOBS_LOCK:
            _STEP_JOBS.pop(key, None)
        job_control.clear_event(key)


def _discard_cancelled_artifact(
    client_id: str, run_id: str, step_name: str
) -> None:
    try:
        path = (
            config.CLIENTS_DIR
            / client_id
            / "runs"
            / run_id
            / f"{step_name}.md"
        )
        if path.is_file():
            path.unlink()
            try:
                from backend import mongo_storage

                mongo_storage.flush_missing_relative_path(
                    f"{client_id}/runs/{run_id}/{step_name}.md"
                )
            except Exception:
                logger.exception(
                    "Could not flush cancelled artifact delete %s/%s/%s",
                    client_id,
                    run_id,
                    step_name,
                )
    except OSError:
        logger.exception(
            "Could not discard cancelled artifact %s/%s/%s",
            client_id,
            run_id,
            step_name,
        )


@api_bp.get("/clients/<client_id>/runs")
def list_runs(client_id: str):
    bad = reject_client(client_id)
    if bad:
        return bad
    runs_root = Path(config.CLIENTS_DIR) / client_id / "runs"
    if not runs_root.is_dir():
        return jsonify(runs=[])

    rows: list[dict] = []
    for p in sorted(
        runs_root.iterdir(),
        key=lambda x: x.name,
        reverse=True,
    ):
        if not p.is_dir():
            continue
        run_id = p.name
        manifest_path = p / "run_manifest.json"
        if manifest_path.is_file():
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                manual = data.get("manual_inputs")
                row = {
                    "run_id": run_id,
                    "topic": data.get("topic") or "untitled",
                    "statuses": data.get("statuses") or {},
                    "timestamp": data.get("timestamp") or "",
                    "archived": bool(data.get("archived")),
                    "pipeline_id": resolve_pipeline_id(data),
                }
                if isinstance(manual, dict):
                    row["manual_inputs"] = {
                        k: manual[k]
                        for k in ("paragraph", "additional_details")
                        if manual.get(k)
                    }
                rows.append(row)
            except json.JSONDecodeError:
                rows.append(
                    {
                        "run_id": run_id,
                        "topic": "untitled",
                        "statuses": {},
                        "timestamp": "",
                        "archived": False,
                        "pipeline_id": "article",
                    }
                )
        else:
            rows.append(
                {
                    "run_id": run_id,
                    "topic": "untitled",
                    "statuses": {},
                    "timestamp": "",
                    "archived": False,
                    "pipeline_id": "article",
                }
            )

    return jsonify(runs=rows)


@api_bp.post("/clients/<client_id>/runs")
def create_run(client_id: str):
    bad = reject_client(client_id)
    if bad:
        return bad
    body = request.get_json(silent=True) or {}
    manual = editorial_input.sanitize_manual_inputs(body.get("manual_inputs"))
    semrush = (body.get("semrush_notes") or "").strip()
    if isinstance(body.get("manual_inputs"), dict):
        semrush = semrush or str(body["manual_inputs"].get("semrush_notes") or "").strip()

    topic = (body.get("topic") or "").strip()
    if manual:
        built = editorial_input.build_topic_payload(manual, semrush_notes=semrush)
        if built:
            topic = built
        if not topic:
            topic = editorial_input.topic_title_from_fields(manual) or topic
    if not topic:
        return jsonify(detail="Topic is required (fill in the article form)"), 400

    display_topic = editorial_input.topic_title_from_fields(manual) or topic.split("\n", 1)[0][:500]
    wc_target = editorial_input.word_count_from_manual(manual)
    pipeline_id = "article"
    context_summary = None

    base = Path(config.CLIENTS_DIR) / client_id
    (base / "context").mkdir(parents=True, exist_ok=True)
    (base / "runs").mkdir(parents=True, exist_ok=True)

    run_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    pipeline = get_pipeline(pipeline_id)
    statuses = {name: "pending" for name in pipeline.step_order}
    artifacts.save_run_manifest(
        client_id,
        run_id,
        display_topic,
        statuses,
        pipeline_id=pipeline_id,
        manual_inputs=manual,
        target_word_count=wc_target,
        context_summary=context_summary,
    )

    logo_b64 = body.get("logo_base64")
    logo_name = str(body.get("logo_filename") or "").strip()
    if logo_b64:
        try:
            stored = artifacts.save_run_logo_from_base64(
                client_id, run_id, str(logo_b64), logo_name
            )
            artifacts.set_run_logo_file(client_id, run_id, stored)
        except ValueError as e:
            return jsonify(detail=str(e)), 400

    return jsonify(
        run_id=run_id,
        client_id=client_id,
        topic=display_topic,
        pipeline_id=pipeline_id,
    )


def _cancel_pipeline_step(client_id: str, run_id: str, step_name: str):
    """Reset a step stuck in ``running`` or ``error`` back to ``pending``."""
    manifest = load_manifest(client_id, run_id)
    pipeline_id = resolve_pipeline_id(manifest) if manifest else "article"
    pipeline = get_pipeline(pipeline_id)
    if step_name not in pipeline.step_order:
        return jsonify(detail=f"Unknown step_name: {step_name!r}"), 400

    if not manifest:
        return jsonify(detail="run not found"), 404
    with _STEP_JOBS_LOCK:
        manifest = load_manifest(client_id, run_id) or {}
        topic = manifest.get("topic") or ""
        statuses = dict(manifest.get("statuses") or {})
        for name in pipeline.step_order:
            statuses.setdefault(name, "pending")

        st = statuses.get(step_name, "pending")
        if st not in ("running", "error"):
            return jsonify(detail="Step is not running or in error"), 400

        cancel_key = (client_id, run_id, step_name)
        job_control.request_cancel(cancel_key)

        statuses[step_name] = "pending"
        timings = dict(manifest.get("step_timings") or {})
        timings.pop(step_name, None)
        errors = dict(manifest.get("step_errors") or {})
        errors.pop(step_name, None)
        artifacts.save_run_manifest(
            client_id,
            run_id,
            topic,
            statuses,
            step_timings=timings,
            step_errors=errors,
        )
    try:
        mongo_storage.sync_cache(delete_missing=True)
    except Exception:
        logger.exception(
            "Could not sync Mongo after cancel %s/%s/%s",
            client_id,
            run_id,
            step_name,
        )
    return jsonify(cancelled=True, step_name=step_name)


@api_bp.patch("/clients/<client_id>/runs/<run_id>")
def patch_run(client_id: str, run_id: str):
    """Body: ``{"action": "archive"|"unarchive"|"delete"|"cancel_step", "step_name": "..."}``."""
    bad = reject_client(client_id)
    if bad:
        return bad
    bad_run = reject_run_id(run_id)
    if bad_run:
        return bad_run

    body = request.get_json(silent=True) or {}
    action = (body.get("action") or "").strip().lower()

    if action == "archive":
        if not artifacts.set_run_archived(client_id, run_id, archived=True):
            return jsonify(detail="run not found"), 404
        return jsonify(archived=True, run_id=run_id)
    if action == "unarchive":
        if not artifacts.set_run_archived(client_id, run_id, archived=False):
            return jsonify(detail="run not found"), 404
        return jsonify(archived=False, run_id=run_id)
    if action == "delete":
        if _run_has_active_job(client_id, run_id):
            return jsonify(detail="Wait for the background step to finish before deleting this run"), 409
        if not artifacts.delete_run(client_id, run_id):
            return jsonify(detail="run not found"), 404
        return jsonify(deleted=True, run_id=run_id)
    if action == "cancel_step":
        step_name = (body.get("step_name") or "").strip()
        if not step_name:
            return jsonify(detail="step_name is required for cancel_step"), 400
        bad_step = reject_step_name(step_name)
        if bad_step:
            return bad_step
        return _cancel_pipeline_step(client_id, run_id, step_name)

    return jsonify(
        detail="action must be archive, unarchive, delete, or cancel_step",
    ), 400


@api_bp.post("/clients/<client_id>/runs/<run_id>/archive")
def archive_run(client_id: str, run_id: str):
    bad = reject_client(client_id)
    if bad:
        return bad
    bad_run = reject_run_id(run_id)
    if bad_run:
        return bad_run
    if not artifacts.set_run_archived(client_id, run_id, archived=True):
        return jsonify(detail="run not found"), 404
    return jsonify(archived=True, run_id=run_id)


@api_bp.post("/clients/<client_id>/runs/<run_id>/unarchive")
def unarchive_run(client_id: str, run_id: str):
    bad = reject_client(client_id)
    if bad:
        return bad
    bad_run = reject_run_id(run_id)
    if bad_run:
        return bad_run
    if not artifacts.set_run_archived(client_id, run_id, archived=False):
        return jsonify(detail="run not found"), 404
    return jsonify(archived=False, run_id=run_id)


@api_bp.delete("/clients/<client_id>/runs/<run_id>")
def delete_run(client_id: str, run_id: str):
    bad = reject_client(client_id)
    if bad:
        return bad
    bad_run = reject_run_id(run_id)
    if bad_run:
        return bad_run
    if _run_has_active_job(client_id, run_id):
        return jsonify(detail="Wait for the background step to finish before deleting this run"), 409
    if not artifacts.delete_run(client_id, run_id):
        return jsonify(detail="run not found"), 404
    return jsonify(deleted=True, run_id=run_id)


@api_bp.get("/clients/<client_id>/runs/<run_id>")
def get_run(client_id: str, run_id: str):
    bad = reject_client(client_id)
    if bad:
        return bad
    bad_run = reject_run_id(run_id)
    if bad_run:
        return bad_run
    run_dir = Path(config.CLIENTS_DIR) / client_id / "runs" / run_id
    if not run_dir.is_dir():
        return jsonify(detail="run not found"), 404
    data = load_manifest(client_id, run_id)
    data = _reconcile_stale_running_manifest(client_id, run_id, data)
    display_timings = artifacts.step_timings_for_display(client_id, run_id, data)
    wc = data.get("target_word_count")
    if wc is None and isinstance(data.get("manual_inputs"), dict):
        from backend import editorial_input

        wc = editorial_input.word_count_from_manual(data.get("manual_inputs"))

    return jsonify(
        run_id=run_id,
        client_id=client_id,
        pipeline_id=resolve_pipeline_id(data),
        topic=data.get("topic") or "untitled",
        statuses=data.get("statuses") or {},
        timestamp=data.get("timestamp") or "",
        manual_inputs=data.get("manual_inputs"),
        target_word_count=wc,
        logo_file=data.get("logo_file"),
        step_timings=display_timings,
        step_errors=data.get("step_errors") or {},
    )


@api_bp.get("/clients/<client_id>/runs/<run_id>/logo")
def get_run_logo(client_id: str, run_id: str):
    bad = reject_client(client_id)
    if bad:
        return bad
    bad_run = reject_run_id(run_id)
    if bad_run:
        return bad_run
    data = load_manifest(client_id, run_id)
    logo_file = data.get("logo_file") if data else None
    if not isinstance(logo_file, str) or not logo_file.strip():
        return jsonify(detail="no logo"), 404
    logo_file = logo_file.strip()
    if ".." in logo_file or "/" in logo_file or "\\" in logo_file:
        return jsonify(detail="invalid logo path"), 400
    run_dir = Path(config.CLIENTS_DIR) / client_id / "runs" / run_id
    path = run_dir / logo_file
    if not path.is_file():
        return jsonify(detail="logo not found"), 404
    resp = send_from_directory(run_dir, logo_file)
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp


@api_bp.post("/clients/<client_id>/runs/<run_id>/steps/<step_name>")
def run_single_step(client_id: str, run_id: str, step_name: str):
    bad = reject_client(client_id)
    if bad:
        return bad
    bad_run = reject_run_id(run_id)
    if bad_run:
        return bad_run
    bad_step = reject_step_name(step_name)
    if bad_step:
        return bad_step
    body = request.get_json(silent=True) or {}
    previous_artifact = (body.get("previous_artifact") or "").strip()

    manifest = load_manifest(client_id, run_id)
    pipeline_id = resolve_pipeline_id(manifest) if manifest else "article"
    try:
        pipeline = get_pipeline(pipeline_id)
    except ValueError as e:
        return jsonify(detail=str(e)), 400

    runner_fn = pipeline.step_runners.get(step_name)
    if runner_fn is None:
        return jsonify(detail=f"Unknown step_name: {step_name!r}"), 400

    topic = manifest.get("topic") or ""
    statuses_check = dict(manifest.get("statuses") or {})
    for name in pipeline.step_order:
        statuses_check.setdefault(name, "pending")
    has_topic = bool(topic.strip())
    if not pipeline_flow.can_run_step(
        step_name,
        statuses_check,
        has_topic=has_topic,
        step_order=pipeline.step_order,
    ):
        return jsonify(detail="Step prerequisites not met"), 409

    if pipeline.pipeline_id == "article" and step_name == "topic_card":
        manual = manifest.get("manual_inputs")
        if isinstance(manual, dict):
            built = editorial_input.build_topic_payload(manual)
            if built:
                previous_artifact = built
        if not previous_artifact:
            previous_artifact = topic
    key = (client_id, run_id, step_name)
    thread = threading.Thread(
        target=_run_step_job,
        kwargs={
            "key": key,
            "client_id": client_id,
            "run_id": run_id,
            "step_name": step_name,
            "previous_artifact": previous_artifact,
            "runner_fn": runner_fn,
        },
        name=f"pipeline-{client_id}-{run_id}-{step_name}",
        daemon=True,
    )
    with _STEP_JOBS_LOCK:
        latest = load_manifest(client_id, run_id)
        statuses = dict(latest.get("statuses") or {})
        for name in pipeline.step_order:
            statuses.setdefault(name, "pending")
        if not pipeline_flow.can_run_step(
            step_name,
            statuses,
            has_topic=bool((latest.get("topic") or topic or "").strip()),
            step_order=pipeline.step_order,
        ):
            return jsonify(detail="Step prerequisites not met"), 409
        existing = _STEP_JOBS.get(key)
        thread_alive = bool(existing and existing.is_alive())
        step_status = statuses.get(step_name, "pending")
        if step_status == "running" and not thread_alive:
            # Stale manifest after a crash/restart — allow a fresh run.
            statuses[step_name] = "pending"
            step_status = "pending"
        if step_status == "running":
            return jsonify(detail="This step is already running"), 409
        if thread_alive:
            return (
                jsonify(
                    detail=(
                        "This step is still finishing on the server. "
                        "Wait a moment, or pause again to reset."
                    )
                ),
                409,
            )
        timings = artifacts.record_step_started(client_id, run_id, step_name)
        statuses[step_name] = "running"
        errors = dict(latest.get("step_errors") or {})
        errors.pop(step_name, None)
        artifacts.save_run_manifest(
            client_id,
            run_id,
            topic,
            statuses,
            step_timings=timings,
            step_errors=errors,
        )
        event = job_control.get_or_create_event(key)
        event.clear()
        _STEP_JOBS[key] = thread
    thread.start()
    return jsonify(accepted=True, step_name=step_name, status="running"), 202


@api_bp.post("/clients/<client_id>/runs/<run_id>/final-output/repair")
def repair_final_output(client_id: str, run_id: str):
    """Repair final_output: FAQ, external links, optional full trim (query ?full=1)."""
    bad = reject_client(client_id)
    if bad:
        return bad
    bad_run = reject_run_id(run_id)
    if bad_run:
        return bad_run
    from backend import final_output_enforce

    try:
        text = artifacts.load_artifact(client_id, run_id, "final_output")
    except FileNotFoundError:
        return jsonify(error="final_output artifact not found"), 404
    full = request.args.get("full", "").lower() in ("1", "true", "yes")
    repaired = final_output_enforce.enforce_final_output(
        text, client_id, run_id, allow_llm_repair=full
    )
    if repaired != text:
        artifacts.save_artifact(client_id, run_id, "final_output", repaired)
    return jsonify(content=repaired)


@api_bp.post("/clients/<client_id>/runs/<run_id>/steps/<step_name>/cancel")
def cancel_step(client_id: str, run_id: str, step_name: str):
    bad = reject_client(client_id)
    if bad:
        return bad
    bad_run = reject_run_id(run_id)
    if bad_run:
        return bad_run
    bad_step = reject_step_name(step_name)
    if bad_step:
        return bad_step
    return _cancel_pipeline_step(client_id, run_id, step_name)
