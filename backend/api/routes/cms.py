from flask import jsonify, request

from backend import content_to_cms
from backend.api.blueprint import api_bp
from backend.api.helpers import reject_client, reject_run_id
from backend.integrations import webflow


@api_bp.get("/clients/<client_id>/runs/<run_id>/cms/status")
def get_cms_status(client_id: str, run_id: str):
    """Read-only: is this run's Webflow item published, and what is its live link?"""
    bad = reject_client(client_id)
    if bad:
        return bad
    bad_run = reject_run_id(run_id)
    if bad_run:
        return bad_run
    try:
        return jsonify(content_to_cms.fetch_status(client_id, run_id))
    except webflow.WebflowError as e:
        return jsonify(detail=str(e)), 502
    except RuntimeError as e:
        return jsonify(detail=str(e)), 400
@api_bp.post("/clients/<client_id>/cms/sync")
def sync_cms_published(client_id: str):
    """Mark articles that are already published in Webflow as Content to CMS done."""
    bad = reject_client(client_id)
    if bad:
        return bad
    force = bool((request.get_json(silent=True) or {}).get("force"))
    try:
        return jsonify(content_to_cms.sync_published_status(client_id, force=force))
    except webflow.WebflowError as e:
        return jsonify(detail=str(e)), 502
    except RuntimeError as e:
        return jsonify(detail=str(e)), 400