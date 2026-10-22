"""Pipeline step: Content to CMS.

Sends the finished `final_output` article to Webflow as a DRAFT item.
It never publishes. It runs only when a user runs this step for one article.

Re-running the step updates the same Webflow draft instead of creating a duplicate.
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from datetime import datetime, timezone
from . import editorial_input
from . import artifacts
from . import config  # noqa: F401  (loads .env before os.getenv below)
from .integrations import webflow
from .step_markers import extract_step_body, wrap_step_artifact

logger = logging.getLogger(__name__)

STEP_NAME = "content_to_cms"

# Webflow field slugs. `name` and `slug` are built into every Webflow collection.
# The body and run-id slugs can differ per collection, so they are configurable.
DEFAULT_BODY_FIELD = "post-body"
DEFAULT_RUN_ID_FIELD = "contentflow-run-id-2"
DEFAULT_PUBLISHED_DATE_FIELD = "published-date"

# ---------- Turn the final_output artifact into a title + HTML ----------


def _article_markdown(final_output_artifact: str) -> str:
    """Article text only: drop step markers and the internal Hard gate report."""
    text = extract_step_body("final_output", final_output_artifact)
    text = re.split(r"^#{1,6}\s*Hard gate report", text, flags=re.I | re.M)[0]
    return text.strip()


def _split_title(markdown_text: str, fallback: str) -> tuple[str, str]:
    """First `# Heading` becomes the post title and is removed from the body."""
    match = re.search(r"^#\s+(.+)$", markdown_text, flags=re.M)
    if not match:
        return fallback, markdown_text
    title = match.group(1).strip()
    body = markdown_text.replace(match.group(0), "", 1).strip()
    return title, body


_SPACE = r"[ \t\u00a0]"
_MD_LINK_EDGE_SPACE = re.compile(
    rf"(?<!!)\[({_SPACE}*)([^\[\]\s](?:[^\[\]]*?[^\[\]\s])?)({_SPACE}*)\]\(([^)]*)\)"
)


def _spaces_outside_links(text: str) -> str:
    """`[ anchor ](url)` -> ` [anchor](url) ` so a space is never inside (underlined by) the link."""

    def fix(m: re.Match) -> str:
        lead, label, trail, url = m.groups()
        before = m.string[m.start() - 1 : m.start()]
        after = m.string[m.end() : m.end() + 1]
        # Keep one space outside, but only if there is not already one there.
        lead_out = " " if lead and before and not before.isspace() else ""
        trail_out = " " if trail and after and not after.isspace() else ""
        return f"{lead_out}[{label}]({url}){trail_out}"

    return _MD_LINK_EDGE_SPACE.sub(fix, text)


def _clean_markdown(text: str) -> str:
    text = _spaces_outside_links(text)
    # INTERNAL links: keep only the anchor text for now.
    text = re.sub(r"\[([^\]]+)\]\(INTERNAL:[^)]*\)", r"\1", text)
    # Image placeholders (src is not a real http link): drop them.
    text = re.sub(r"!\[[^\]]*\]\((?!https?://)[^)]*\)[ \t]*", "", text)
    return text


def _blank_line_before_lists(text: str) -> str:
    """Markdown needs a blank line before a list; the model often omits it."""
    out: list[str] = []
    prev_is_list = False
    for line in text.split("\n"):
        is_list = bool(re.match(r"^\s*([-*+]|\d+\.)\s+", line))
        if is_list and not prev_is_list and out and out[-1].strip():
            out.append("")
        out.append(line)
        prev_is_list = is_list
    return "\n".join(out)


def _markdown_to_html(text: str) -> str:
    import markdown  # imported here so the rest of the backend works without it

    html = markdown.markdown(
        _blank_line_before_lists(text), extensions=["sane_lists", "tables"]
    )
    # Webflow's rich text field drops lists that contain line breaks between
    # tags, or bold text right at the start of a list item. Normalise both.
    html = re.sub(r">\s*\n\s*<", "><", html)
    html = re.sub(r"<li><strong>(.*?)</strong>", r"<li>\1", html)
    return html.strip()


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:80].strip("-")


def build_post(final_output_artifact: str, run_id: str) -> dict:
    """Return {"title", "slug", "html"} for a final_output artifact."""
    title, body = _split_title(_article_markdown(final_output_artifact), run_id)
    html = _markdown_to_html(_clean_markdown(body))
    return {"title": title, "slug": _slugify(title) or _slugify(run_id), "html": html}
# ---------- Meta title + meta description (from the Meta SEO step) ----------


def _recommended_meta(client_id: str, run_id: str) -> tuple[str, str]:
    """(meta title, meta description) = option 1 of the Meta SEO step.

    Same values the Final Output "Metadata" tab shows as "Recommended".
    Returns empty strings when the Meta SEO step has not been run.
    """
    try:
        text = artifacts.load_artifact(client_id, run_id, "meta_seo")
    except FileNotFoundError:
        return "", ""
    parsed = editorial_input.parse_meta_seo_artifact(text)
    titles = parsed.get("title_options") or []
    descriptions = parsed.get("description_options") or []
    return (titles[0] if titles else ""), (descriptions[0] if descriptions else "")

# ---------- The step itself ----------


def _previous_send(client_id: str, run_id: str) -> tuple[str, str]:
    """(item_id, collection_id) from an earlier run of this step, if any."""
    try:
        text = artifacts.load_artifact(client_id, run_id, STEP_NAME)
    except FileNotFoundError:
        return "", ""
    item = re.search(r"Webflow item ID:\s*(\S+)", text)
    coll = re.search(r"Collection ID:\s*(\S+)", text)
    return (item.group(1) if item else ""), (coll.group(1) if coll else "")


def run_content_to_cms(client_id: str, run_id: str, previous_artifact: str = "") -> str:
    """Create (or update) the Webflow draft for this run."""
    try:
        final_output = artifacts.load_artifact(client_id, run_id, "final_output")
    except FileNotFoundError as e:
        raise RuntimeError("Run the Final Output step before Content to CMS.") from e

    post = build_post(final_output, run_id)
    if not post["html"]:
        raise RuntimeError("The final output is empty, nothing to send to Webflow.")

    body_field = (os.getenv("WEBFLOW_FIELD_BODY") or DEFAULT_BODY_FIELD).strip()
    run_id_field = os.getenv("WEBFLOW_FIELD_RUN_ID")
    run_id_field = DEFAULT_RUN_ID_FIELD if run_id_field is None else run_id_field.strip()

    field_data = {"name": post["title"], "slug": post["slug"], body_field: post["html"]}
    if run_id_field:  # set WEBFLOW_FIELD_RUN_ID= (empty) to skip this field
        field_data[run_id_field] = run_id
    
    
    # Published Date = current system date/time (Webflow wants ISO 8601, UTC).
    published_date_field = os.getenv("WEBFLOW_FIELD_PUBLISHED_DATE")
    published_date_field = (
        DEFAULT_PUBLISHED_DATE_FIELD
        if published_date_field is None
        else published_date_field.strip()
    )
    if published_date_field:  # set WEBFLOW_FIELD_PUBLISHED_DATE= (empty) to skip
        field_data[published_date_field] = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )


    # Meta title / meta description. Each is sent only when its Webflow field
    # slug is set in .env (WEBFLOW_FIELD_META_TITLE / WEBFLOW_FIELD_META_DESCRIPTION).
    meta_title, meta_description = _recommended_meta(client_id, run_id)
    meta_title_field = (os.getenv("WEBFLOW_FIELD_META_TITLE") or "").strip()
    meta_description_field = (os.getenv("WEBFLOW_FIELD_META_DESCRIPTION") or "").strip()
    
    if meta_title_field and meta_title:
        field_data[meta_title_field] = meta_title
    if meta_description_field and meta_description:
        field_data[meta_description_field] = meta_description

    collection_id = webflow.collection_id()
    old_item_id, old_collection_id = _previous_send(client_id, run_id)

    result = "created"
    item_id = ""
    if old_item_id and old_collection_id == collection_id:
        try:
            existing = webflow.get_item(old_item_id)
            if existing.get("lastPublished") and not existing.get("isDraft"):
                raise RuntimeError(
                    "This article is already published in Webflow, so the draft "
                    "was not changed. Edit it in Webflow instead."
                )
        except webflow.WebflowError as e:
            if e.status != 404:
                raise
        try:
            item_id = webflow.update_item(old_item_id, field_data)
            result = "updated"
        except webflow.WebflowError as e:
            if e.status != 404:  # 404 = draft was deleted in Webflow: create a new one
                raise
    if not item_id:
        item_id = webflow.create_draft_item(field_data)

    sent_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    output = (
        "## Draft sent to CMS\n\n"
        f"- Result: {result}\n"
        f"- Title: {post['title']}\n"
        f"- Slug: {post['slug']}\n"
        f"- Webflow item ID: {item_id}\n"
        f"- Collection ID: {collection_id}\n"
        f"- Sent at: {sent_at}\n\n"
        f"- Meta title: {meta_title or '(not set, run the Meta Title & Description step)'}\n"
        f"- Meta description: {meta_description or '(not set, run the Meta Title & Description step)'}\n"
        "Open Webflow CMS, find this draft, review it, then publish it there. "
        "Running this step again updates the same draft.\n"
    )
    output = wrap_step_artifact(STEP_NAME, output)
    artifacts.save_artifact(client_id, run_id, STEP_NAME, output)
    logger.info("step complete %s (%s)", STEP_NAME, result)
    return output




# ---------- Publish status + live link (read-only, never changes Webflow) ----------


def _live_url(slug: str, client_id: str = "") -> str:
    """Live article URL = base + "/" + slug.

    Base = this client's `live_url_base` (workspace meta), else WEBFLOW_LIVE_URL_BASE.
    Returns "" if no base is set.
    """
    base = ""
    if client_id:
        base = str(artifacts.read_workspace_meta(client_id).get("live_url_base") or "")
    if not base:
        base = os.getenv("WEBFLOW_LIVE_URL_BASE") or ""
    base = base.strip().rstrip("/")
    if not base or not slug:
        return ""
    return f"{base}/{slug}"


def fetch_status(client_id: str, run_id: str) -> dict:
    """Ask Webflow whether the draft sent by this run has been published.

    Returns {"sent", "status", "live_url", "last_published", "item_id", "slug"}.
    status: "not_sent" | "draft" | "published" | "changes_in_draft" | "missing".
    Read-only: nothing is changed in Webflow or in the saved artifact.
    """
    item_id, old_collection_id = _previous_send(client_id, run_id)
    if not item_id:
        return {"sent": False, "status": "not_sent", "live_url": "", "last_published": "",
                "item_id": "", "slug": ""}
    if old_collection_id and old_collection_id != webflow.collection_id():
        raise RuntimeError(
            "This article was sent to a different Webflow collection than the one "
            "set in .env (WEBFLOW_COLLECTION_ID)."
        )
    try:
        item = webflow.get_item(item_id)
    except webflow.WebflowError as e:
        if e.status == 404:  # draft was deleted in Webflow
            return {"sent": True, "status": "missing", "live_url": "", "last_published": "",
                    "item_id": item_id, "slug": ""}
        raise
    last_published = item.get("lastPublished") or ""
    is_draft = bool(item.get("isDraft"))
    slug = ((item.get("fieldData") or {}).get("slug")) or ""
    if not last_published:
        status = "draft"
    elif is_draft:
        status = "changes_in_draft"  # live article stays online; newer edits wait in Webflow
    else:
        status = "published"
    return {
        "sent": True,
        "status": status,
        "live_url": _live_url(slug,client_id) if last_published else "",
        "last_published": last_published,
        "item_id": item_id,
        "slug": slug,
    }
# ---------- Mark articles already published in Webflow as "Content to CMS: done" ----------

_ITEMS_CACHE: dict = {"at": 0.0, "items": []}
_ITEMS_TTL_SECONDS = 60
_SYNC_AT: dict[str, float] = {}
_SYNC_MIN_SECONDS = 300


def _all_items() -> list[dict]:
    now = time.monotonic()
    if _ITEMS_CACHE["items"] and now - _ITEMS_CACHE["at"] < _ITEMS_TTL_SECONDS:
        return _ITEMS_CACHE["items"]
    items = webflow.list_items()
    _ITEMS_CACHE.update(at=now, items=items)
    return items


def published_map(client_id: str) -> dict[str, dict]:
    """{run_id: {"status", "live_url", "item_id"}} for runs that exist in Webflow.

    Includes drafts, not only published items. A run is matched to a Webflow item by:
    (1) the item id saved by the Content to CMS step,
    (2) the run-id field in Webflow,
    (3) the slug or title of the real article (from final_output),
    (4) the topic slug.
    Read-only.
    """
    items = _all_items()
    run_id_field = os.getenv("WEBFLOW_FIELD_RUN_ID")
    run_id_field = DEFAULT_RUN_ID_FIELD if run_id_field is None else run_id_field.strip()

    by_id, by_run_id, by_slug, by_name = {}, {}, {}, {}
    for item in items:
        if item.get("isArchived"):
            continue  # archived in Webflow: ignore
        # NOTE: drafts are kept now (the old "lastPublished" check was removed)
        fields = item.get("fieldData") or {}
        by_id[item.get("id")] = item
        if run_id_field and fields.get(run_id_field):
            by_run_id[str(fields[run_id_field]).strip()] = item
        if fields.get("slug"):
            by_slug[fields["slug"]] = item
        if fields.get("name"):
            by_name[str(fields["name"]).strip().lower()] = item

    runs_root = Path(config.CLIENTS_DIR) / client_id / "runs"
    if not runs_root.is_dir():
        return {}

    out: dict[str, dict] = {}
    for run_dir in runs_root.iterdir():
        if not run_dir.is_dir():
            continue
        run_id = run_dir.name
        manifest = artifacts.read_run_manifest(client_id, run_id) or {}
        item = None

        # 1) item id saved by an earlier Content to CMS run
        if (manifest.get("statuses") or {}).get("content_to_cms") == "done":
            sent_id, _coll = _previous_send(client_id, run_id)
            item = by_id.get(sent_id)

        # 2) run-id field stored in Webflow
        if item is None:
            item = by_run_id.get(run_id)

        # 3) slug / title of the real article (this is what was sent to Webflow)
        if item is None:
            try:
                final_output = artifacts.load_artifact(client_id, run_id, "final_output")
                title, _body = _split_title(_article_markdown(final_output), run_id)
                item = by_slug.get(_slugify(title)) or by_name.get(title.strip().lower())
            except Exception:
                pass  # no final_output yet: skip this matcher

        # 4) topic slug (old fallback)
        if item is None and manifest.get("topic"):
            item = by_slug.get(_slugify(manifest["topic"]))

        if item is None:
            continue

        slug = (item.get("fieldData") or {}).get("slug") or ""
        if not item.get("lastPublished"):
            status = "draft"
        elif item.get("isDraft"):
            status = "changes_in_draft"
        else:
            status = "published"
        out[run_id] = {
            "status": status,
            "live_url": _live_url(slug,client_id) if item.get("lastPublished") else "",
            "item_id": item.get("id") or "",
        }
    return out


def sync_published_status(client_id: str, force: bool = False) -> dict:
    """Write content_to_cms = "done" into the manifest of every article that is
    published in Webflow but not yet marked. Nothing is changed in Webflow.

    Also saves a small content_to_cms.md (item id + collection id) so the Webflow
    panel on the step works. The manifest timestamp and all other fields are kept.
    Runs at most once every few minutes per client unless force=True.
    """
    now = time.monotonic()
    if not force and now - _SYNC_AT.get(client_id, -1e9) < _SYNC_MIN_SECONDS:
        return {"skipped": True, "updated": []}
    matched = published_map(client_id)
    _SYNC_AT[client_id] = now
    collection = webflow.collection_id()
    updated: list[str] = []
    for run_id, info in matched.items():
        manifest = artifacts.read_run_manifest(client_id, run_id)
        if not manifest:
            continue
        statuses = dict(manifest.get("statuses") or {})
        if statuses.get(STEP_NAME) == "done":
            continue
        if not _previous_send(client_id, run_id)[0]:
            body = (
                "## Already published in CMS\n\n"
                "- Result: linked to the item that is already published in Webflow\n"
                f"- Webflow item ID: {info['item_id']}\n"
                f"- Collection ID: {collection}\n"
            )
            artifacts.save_artifact(
                client_id, run_id, STEP_NAME, wrap_step_artifact(STEP_NAME, body)
            )
        statuses[STEP_NAME] = "done"
        manifest["statuses"] = statuses
        manifest_path = artifacts.get_run_dir(client_id, run_id) / "run_manifest.json"
        artifacts._write_json_atomic(manifest_path, manifest)
        updated.append(run_id)
    return {"skipped": False, "updated": updated}