"""Minimal Webflow CMS (API v2) client used by the Content to CMS step.

Uses only the standard library, so no new dependency is needed for HTTP.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

API_BASE = "https://api.webflow.com/v2"
TIMEOUT_SECONDS = 30


class WebflowError(RuntimeError):
    """Webflow rejected the request. `status` is the HTTP status code."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _credentials() -> tuple[str, str]:
    token = (os.getenv("WEBFLOW_TOKEN") or "").strip()
    collection_id = (os.getenv("WEBFLOW_COLLECTION_ID") or "").strip()
    missing = [
        name
        for name, value in (
            ("WEBFLOW_TOKEN", token),
            ("WEBFLOW_COLLECTION_ID", collection_id),
        )
        if not value
    ]
    if missing:
        raise WebflowError(
            "Missing environment variable(s): "
            + ", ".join(missing)
            + ". Add them to .env and restart the backend."
        )
    return token, collection_id


def _request(method: str, path: str, token: str, payload: dict | None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Some edge firewalls reject Python's default user agent.
            "User-Agent": "contentflow-webflow/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:800]
        raise WebflowError(f"Webflow {e.code}: {detail}", status=e.code) from e
    except urllib.error.URLError as e:
        raise WebflowError(f"Could not reach Webflow: {e.reason}") from e


def create_draft_item(field_data: dict) -> str:
    """Create a new CMS item as a draft. Returns the Webflow item id."""
    token, collection_id = _credentials()
    result = _request(
        "POST",
        f"/collections/{collection_id}/items",
        token,
        {"isArchived": False, "isDraft": True, "fieldData": field_data},
    )
    item_id = result.get("id")
    if not item_id:
        raise WebflowError(f"Webflow CMS response had no item id: {str(result)[:300]}")
    logger.info("webflow CMS draft created item=%s", item_id)
    return item_id


def update_item(item_id: str, field_data: dict) -> str:
    """Update the fields of an existing item (draft status is left unchanged)."""
    token, collection_id = _credentials()
    _request(
        "PATCH",
        f"/collections/{collection_id}/items/{item_id}",
        token,
        {"fieldData": field_data},
    )
    logger.info("webflow CMS item updated item=%s", item_id)
    return item_id

def get_item(item_id: str) -> dict:
    """Read one CMS item (used to see whether it is published and its slug)."""
    token, collection_id = _credentials()
    return _request("GET", f"/collections/{collection_id}/items/{item_id}", token, None)

def list_items() -> list[dict]:
    """Read every item in the collection (paged, 100 per request). Read-only."""
    token, collection_id = _credentials()
    items: list[dict] = []
    offset = 0
    while True:
        result = _request(
            "GET",
            f"/collections/{collection_id}/items?limit=100&offset={offset}",
            token,
            None,
        )
        batch = result.get("items") or []
        items.extend(batch)
        offset += len(batch)
        total = (result.get("pagination") or {}).get("total")
        if len(batch) < 100 or (total is not None and offset >= total):
            break
    return items
def collection_id() -> str:
    return _credentials()[1]
