from flask import jsonify, request

from backend import artifacts
from backend import editorial_input
from backend import final_output_enforce
from backend.api.blueprint import api_bp
from backend.api.helpers import reject_client, reject_run_id


@api_bp.get("/clients/<client_id>/runs/<run_id>/artifacts/<step_name>")
def get_artifact(client_id: str, run_id: str, step_name: str):
    bad = reject_client(client_id)
    if bad:
        return bad
    bad_run = reject_run_id(run_id)
    if bad_run:
        return bad_run
    try:
        text = artifacts.load_artifact(client_id, run_id, step_name)
    except FileNotFoundError:
        return jsonify(content="")

    manifest = artifacts.read_run_manifest(client_id, run_id) or {}
    wc = editorial_input.word_count_target_from_manifest(manifest)

    if step_name == "topic_card" and (text or "").strip():
        manual = manifest.get("manual_inputs")
        if isinstance(manual, dict):
            repaired = editorial_input.apply_manual_keywords_topic_card(
                text, manual, semrush_notes=""
            )
            if wc:
                repaired = editorial_input.enforce_word_count_in_topic_card(
                    repaired, wc
                )
            if repaired != text:
                artifacts.save_artifact(
                    client_id, run_id, step_name, repaired
                )
                text = repaired

    if step_name == "final_output" and (text or "").strip():
        repaired = final_output_enforce.enforce_final_output(
            text, client_id, run_id, allow_llm_repair=False
        )
        # Fast path: FAQ, external links, JSON-LD (no LLM trim on load)
        if repaired != text:
            artifacts.save_artifact(client_id, run_id, step_name, repaired)
            text = repaired

    if wc and (text or "").strip():
        if step_name == "assignment_brief":
            repaired = editorial_input.enforce_word_count_in_brief(text, wc)
        elif step_name == "outline":
            repaired = editorial_input.enforce_outline_section_word_counts(
                text, wc
            )
        else:
            repaired = text
        if repaired != text:
            artifacts.save_artifact(client_id, run_id, step_name, repaired)
            text = repaired

    return jsonify(content=text)


@api_bp.post(
    "/clients/<client_id>/runs/<run_id>/artifacts/final_output/repair"
)
def repair_final_output_artifact(client_id: str, run_id: str):
    """Full repair: FAQ, external links, word-count trim (may take 1–3 min)."""
    bad = reject_client(client_id)
    if bad:
        return bad
    bad_run = reject_run_id(run_id)
    if bad_run:
        return bad_run
    try:
        text = artifacts.load_artifact(client_id, run_id, "final_output")
    except FileNotFoundError:
        return jsonify(error="final_output artifact not found"), 404
    repaired = final_output_enforce.enforce_final_output(
        text, client_id, run_id, allow_llm_repair=True
    )
    if repaired != text:
        artifacts.save_artifact(client_id, run_id, "final_output", repaired)
    return jsonify(content=repaired)


@api_bp.put("/clients/<client_id>/runs/<run_id>/artifacts/<step_name>")
def put_artifact(client_id: str, run_id: str, step_name: str):
    bad = reject_client(client_id)
    if bad:
        return bad
    bad_run = reject_run_id(run_id)
    if bad_run:
        return bad_run

    repair_flag = request.args.get("repair", "").lower() in ("1", "true", "yes")
    if step_name == "final_output" and repair_flag:
        try:
            content = artifacts.load_artifact(client_id, run_id, "final_output")
        except FileNotFoundError:
            return jsonify(error="final_output artifact not found"), 404
        full = request.args.get("full", "").lower() in ("1", "true", "yes")
        repaired = final_output_enforce.enforce_final_output(
            content,
            client_id,
            run_id,
            allow_llm_repair=full,
        )
        if repaired != content:
            artifacts.save_artifact(client_id, run_id, "final_output", repaired)
        return jsonify(content=repaired, saved=True)

    body = request.get_json(silent=True) or {}
    content = body.get("content", "")
    if step_name == "final_output" and not (content or "").strip():
        try:
            existing = artifacts.load_artifact(client_id, run_id, step_name)
        except FileNotFoundError:
            existing = ""
        if (existing or "").strip():
            return (
                jsonify(
                    error="Refusing to save empty final_output — use Repair or paste content."
                ),
                400,
            )
    artifacts.save_artifact(client_id, run_id, step_name, content)
    return jsonify(saved=True)
