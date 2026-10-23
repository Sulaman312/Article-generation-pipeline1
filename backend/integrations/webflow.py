"""Minimal Webflow CMS (API v2) client used by the Content to CMS step.

Uses only the standard library, so no new dependency is needed for HTTP.
Credentials come from the caller (per-workspace config); env is only a fallback.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

API_BASE = "https://api.webflow.com/v2"
TIMEOUT_SECONDS = 30


class WebflowError(RuntimeError):
    """Webflow rejected the request. `status` is the HTTP status code."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _credentials(
    token: str = "",
    collection_id: str = "",
) -> tuple[str, str]:
    token = (token or os.getenv("WEBFLOW_TOKEN") or "").strip()
    collection_id = (collection_id or os.getenv("WEBFLOW_COLLECTION_ID") or "").strip()
    missing = [
        name
        for name, value in (
            ("token", token),
            ("collection_id", collection_id),
        )
        if not value
    ]
    if missing:
        raise WebflowError(
            "Missing Webflow credentials ("
            + ", ".join(missing)
            + "). Set them on the workspace (Edit workspace -> CMS) or in .env "
            "(WEBFLOW_TOKEN / WEBFLOW_COLLECTION_ID)."
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


def create_draft_item(
    field_data: dict,
    *,
    token: str = "",
    collection_id: str = "",
) -> str:
    """Create a new CMS item as a draft. Returns the Webflow item id."""
    token, collection_id = _credentials(token, collection_id)
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


def update_item(
    item_id: str,
    field_data: dict,
    *,
    token: str = "",
    collection_id: str = "",
) -> str:
    """Update the fields of an existing item (draft status is left unchanged)."""
    token, collection_id = _credentials(token, collection_id)
    _request(
        "PATCH",
        f"/collections/{collection_id}/items/{item_id}",
        token,
        {"fieldData": field_data},
    )
    logger.info("webflow CMS item updated item=%s", item_id)
    return item_id


def get_item(
    item_id: str,
    *,
    token: str = "",
    collection_id: str = "",
) -> dict:
    """Read one CMS item (used to see whether it is published and its slug)."""
    token, collection_id = _credentials(token, collection_id)
    return _request(
        "GET", f"/collections/{collection_id}/items/{item_id}", token, None
    )


def list_items(*, token: str = "", collection_id: str = "") -> list[dict]:
    """Read every item in the collection (paged, 100 per request). Read-only."""
    token, collection_id = _credentials(token, collection_id)
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


def collection_id(*, token: str = "", collection_id: str = "") -> str:
    return _credentials(token, collection_id)[1]


def get_collection(
    *,
    token: str = "",
    collection_id: str = "",
) -> dict:
    """Read collection metadata (may include siteId depending on API version)."""
    token, collection_id = _credentials(token, collection_id)
    return _request("GET", f"/collections/{collection_id}", token, None)


def get_site(site_id: str, *, token: str = "") -> dict:
    """Read site details including shortName for Designer URLs."""
    token = (token or os.getenv("WEBFLOW_TOKEN") or "").strip()
    if not token:
        raise WebflowError(
            "Missing Webflow credentials (token). Set them on the workspace "
            "or in .env (WEBFLOW_TOKEN)."
        )
    if not (site_id or "").strip():
        raise WebflowError("Missing Webflow site id.")
    return _request("GET", f"/sites/{site_id.strip()}", token, None)


def list_sites(*, token: str = "") -> list[dict]:
    """List sites the token can access (for resolving Designer shortName)."""
    token = (token or os.getenv("WEBFLOW_TOKEN") or "").strip()
    if not token:
        raise WebflowError(
            "Missing Webflow credentials (token). Set them on the workspace "
            "or in .env (WEBFLOW_TOKEN)."
        )
    result = _request("GET", "/sites", token, None)
    return list(result.get("sites") or [])


def resolve_site_short_name(
    *,
    token: str = "",
    collection_id: str = "",
) -> str:
    """Best-effort Designer site slug (e.g. arsuno-site) from collection → site.

    Requires sites:read on the token. Returns "" if lookup fails.
    """
    try:
        token, collection_id = _credentials(token, collection_id)
        collection = get_collection(token=token, collection_id=collection_id)
        site_id = str(collection.get("siteId") or "").strip()
        if site_id:
            site = get_site(site_id, token=token)
            short = str(site.get("shortName") or "").strip()
            if short:
                return short
        # Fallback: find which listed site owns this collection.
        for site in list_sites(token=token):
            sid = str(site.get("id") or "").strip()
            if not sid:
                continue
            try:
                listed = _request(
                    "GET", f"/sites/{sid}/collections", token, None
                )
            except WebflowError:
                continue
            for col in listed.get("collections") or []:
                if str(col.get("id") or "") == collection_id:
                    return str(site.get("shortName") or "").strip()
    except WebflowError as e:
        logger.info("webflow site shortName lookup skipped: %s", e)
    return ""


def designer_cms_url(
    site_short_name: str,
    *,
    collection_id: str = "",
    item_id: str = "",
) -> str:
    """Open this CMS item in the Webflow Designer (CMS workflow).

    Example:
    https://arsuno-site.design.webflow.com/?legacyEditorMigrated=true&workflow=cms
      &collectionId=...&itemId=...
    """
    short = (site_short_name or "").strip().strip("/")
    if short.startswith("https://"):
        # Allow pasting a full designer host or base URL.
        short = short.removeprefix("https://").removeprefix("http://")
        short = short.split("/")[0]
        short = short.removesuffix(".design.webflow.com")
    if not short or not collection_id or not item_id:
        return ""

    query = urlencode(
        {
            "legacyEditorMigrated": "true",
            "workflow": "cms",
            "collectionId": collection_id,
            "itemId": item_id,
        }
    )
    return f"https://{short}.design.webflow.com/?{query}"
