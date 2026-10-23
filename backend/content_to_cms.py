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

# Supported CMS providers for a workspace. More can be added later.
CMS_PROVIDERS = ("none", "webflow")
DEFAULT_CMS_PROVIDER = "none"

# Webflow field slugs. `name` and `slug` are built into every Webflow collection.
# The body and run-id slugs can differ per collection, so they are configurable.
# Matches webflow_fields.json for this project's Blog Posts collection.
DEFAULT_BODY_FIELD = "content---1"
# Empty = omit unless WEBFLOW_FIELD_RUN_ID / workspace cms.field_run_id is set.
DEFAULT_RUN_ID_FIELD = ""
DEFAULT_PUBLISHED_DATE_FIELD = "published-date"

# ---------- Per-workspace CMS config (workspace.json → .env → defaults) ----------


def normalize_cms_provider(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if raw in ("", "off", "disabled", "null"):
        return "none"
    if raw in CMS_PROVIDERS:
        return raw
    return "none"


def _infer_provider(
    explicit: str | None,
    *,
    token: str,
    collection_id: str,
) -> str:
    """Resolve provider: explicit workspace value, else webflow if creds exist, else none."""
    if explicit is not None:
        return normalize_cms_provider(explicit)
    # Back-compat: global .env Webflow still works when provider was never set.
    if token and collection_id:
        return "webflow"
    return DEFAULT_CMS_PROVIDER


def resolve_cms_config(client_id: str = "") -> dict[str, str]:
    """Effective CMS settings for this workspace.

    ``provider`` is ``none`` or ``webflow`` (extensible later).
    For Webflow fields: workspace ``cms.*`` if set → ``WEBFLOW_*`` env → defaults.
    ``live_url_base`` lives on workspace meta with the same env fallback.
    """
    meta = artifacts.read_workspace_meta(client_id) if client_id else {}
    raw = meta.get("cms") if isinstance(meta, dict) else None
    cms = raw if isinstance(raw, dict) else {}

    def from_ws(key: str) -> str | None:
        if key not in cms or cms[key] is None:
            return None
        return str(cms[key]).strip()

    def pick(ws_key: str, env_key: str, default: str = "") -> str:
        ws = from_ws(ws_key)
        if ws is not None:
            return ws
        env = os.getenv(env_key)
        if env is not None:
            return env.strip()
        return default

    # Optional field slugs: absent key → default; present empty → omit field.
    if "field_run_id" in cms and cms["field_run_id"] is not None:
        field_run_id = str(cms["field_run_id"]).strip()
    elif os.getenv("WEBFLOW_FIELD_RUN_ID") is not None:
        field_run_id = (os.getenv("WEBFLOW_FIELD_RUN_ID") or "").strip()
    else:
        field_run_id = DEFAULT_RUN_ID_FIELD

    if "field_published_date" in cms and cms["field_published_date"] is not None:
        field_published_date = str(cms["field_published_date"]).strip()
    elif os.getenv("WEBFLOW_FIELD_PUBLISHED_DATE") is not None:
        field_published_date = (os.getenv("WEBFLOW_FIELD_PUBLISHED_DATE") or "").strip()
    else:
        field_published_date = DEFAULT_PUBLISHED_DATE_FIELD

    live = ""
    if isinstance(meta, dict):
        live = str(meta.get("live_url_base") or "").strip()
    if not live:
        live = (os.getenv("WEBFLOW_LIVE_URL_BASE") or "").strip()

    token = pick("token", "WEBFLOW_TOKEN", "")
    collection_id = pick("collection_id", "WEBFLOW_COLLECTION_ID", "")
    # Key absent → infer; key present (even empty) → explicit choice.
    explicit = str(cms.get("provider") or "").strip() if "provider" in cms else None

    body = pick("field_body", "WEBFLOW_FIELD_BODY", DEFAULT_BODY_FIELD)
    return {
        "provider": _infer_provider(explicit, token=token, collection_id=collection_id),
        "token": token,
        "collection_id": collection_id,
        "field_body": body or DEFAULT_BODY_FIELD,
        "field_run_id": field_run_id,
        "field_meta_title": pick("field_meta_title", "WEBFLOW_FIELD_META_TITLE", ""),
        "field_meta_description": pick(
            "field_meta_description", "WEBFLOW_FIELD_META_DESCRIPTION", ""
        ),
        "field_published_date": field_published_date,
        # Designer host slug, e.g. arsuno-site → https://arsuno-site.design.webflow.com/
        "site_short_name": pick(
            "site_short_name", "WEBFLOW_SITE_SHORT_NAME", ""
        ),
        "live_url_base": live.rstrip("/"),
    }


def public_cms_settings(client_id: str) -> dict:
    """Workspace-stored CMS settings for the UI (token masked, never raw)."""
    meta = artifacts.read_workspace_meta(client_id) if client_id else {}
    raw = meta.get("cms") if isinstance(meta, dict) else None
    cms = dict(raw) if isinstance(raw, dict) else {}
    token = str(cms.get("token") or "").strip()
    if "provider" in cms:
        provider = normalize_cms_provider(str(cms.get("provider") or ""))
    else:
        provider = resolve_cms_config(client_id).get("provider") or DEFAULT_CMS_PROVIDER
    out = {
        "provider": provider,
        "providers": list(CMS_PROVIDERS),
        "collection_id": str(cms.get("collection_id") or "").strip(),
        "field_body": str(cms.get("field_body") or "").strip(),
        "field_run_id": str(cms.get("field_run_id") or "").strip()
        if "field_run_id" in cms
        else "",
        "field_meta_title": str(cms.get("field_meta_title") or "").strip(),
        "field_meta_description": str(cms.get("field_meta_description") or "").strip(),
        "field_published_date": str(cms.get("field_published_date") or "").strip()
        if "field_published_date" in cms
        else "",
        "site_short_name": str(cms.get("site_short_name") or "").strip(),
        "token_set": bool(token),
        "token_hint": (f"••••{token[-4:]}" if len(token) >= 4 else ("••••" if token else "")),
    }
    return out


def merge_cms_settings(existing: dict | None, patch: dict | None) -> dict:
    """Merge a CMS patch into workspace cms. Blank token keeps the existing token."""
    base = dict(existing) if isinstance(existing, dict) else {}
    incoming = dict(patch) if isinstance(patch, dict) else {}
    keys = (
        "provider",
        "token",
        "collection_id",
        "field_body",
        "field_run_id",
        "field_meta_title",
        "field_meta_description",
        "field_published_date",
        "site_short_name",
    )
    for key in keys:
        if key not in incoming:
            continue
        value = incoming[key]
        if key == "token":
            text = "" if value is None else str(value).strip()
            if not text:
                continue  # blank = keep existing
            base["token"] = text
            continue
        if key == "provider":
            base["provider"] = normalize_cms_provider(
                "" if value is None else str(value)
            )
            continue
        if value is None:
            continue
        base[key] = str(value).strip()
    if "provider" not in base:
        base["provider"] = DEFAULT_CMS_PROVIDER
    else:
        base["provider"] = normalize_cms_provider(str(base.get("provider") or ""))
    return base


def _webflow_kwargs(cms: dict) -> dict[str, str]:
    return {
        "token": cms.get("token") or "",
        "collection_id": cms.get("collection_id") or "",
    }


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
    """Create (or update) a CMS draft for this run (provider-specific)."""
    try:
        final_output = artifacts.load_artifact(client_id, run_id, "final_output")
    except FileNotFoundError as e:
        raise RuntimeError("Run the Final Output step before Content to CMS.") from e

    post = build_post(final_output, run_id)
    if not post["html"]:
        raise RuntimeError("The final output is empty, nothing to send to the CMS.")

    cms = resolve_cms_config(client_id)
    provider = normalize_cms_provider(cms.get("provider"))
    if provider == "none":
        raise RuntimeError(
            "CMS is disabled for this workspace (provider=none). "
            "Open Edit workspace and set CMS provider to Webflow, or leave it "
            "disabled if this client has no CMS."
        )
    if provider != "webflow":
        raise RuntimeError(
            f"Unsupported CMS provider {provider!r}. "
            f"Supported: {', '.join(CMS_PROVIDERS)}."
        )

    wf = _webflow_kwargs(cms)
    body_field = (cms.get("field_body") or DEFAULT_BODY_FIELD).strip()
    run_id_field = (cms.get("field_run_id") or "").strip()

    field_data = {"name": post["title"], "slug": post["slug"], body_field: post["html"]}
    if run_id_field:
        field_data[run_id_field] = run_id

    # Published Date = current system date/time (Webflow wants ISO 8601, UTC).
    published_date_field = (cms.get("field_published_date") or "").strip()
    if published_date_field:
        field_data[published_date_field] = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )

    # Meta title / meta description — only when field slugs are configured.
    meta_title, meta_description = _recommended_meta(client_id, run_id)
    meta_title_field = (cms.get("field_meta_title") or "").strip()
    meta_description_field = (cms.get("field_meta_description") or "").strip()

    if meta_title_field and meta_title:
        field_data[meta_title_field] = meta_title
    if meta_description_field and meta_description:
        field_data[meta_description_field] = meta_description

    collection_id = webflow.collection_id(**wf)
    old_item_id, old_collection_id = _previous_send(client_id, run_id)

    result = "created"
    item_id = ""
    if old_item_id and old_collection_id == collection_id:
        try:
            existing = webflow.get_item(old_item_id, **wf)
            # Any prior publish means the live item exists. PATCH-ing fields would
            # stage "Queued to publish" changes on top of the live post. We never
            # auto-publish, so refuse and keep the live version untouched.
            if existing.get("lastPublished"):
                raise RuntimeError(
                    "This article is already published in Webflow. "
                    "Content to CMS will not overwrite it (that would queue a "
                    "new draft on top of the live post). Edit or re-publish in "
                    "Webflow, or create a new article run."
                )
        except webflow.WebflowError as e:
            if e.status != 404:
                raise
        try:
            item_id = webflow.update_item(old_item_id, field_data, **wf)
            result = "updated"
        except webflow.WebflowError as e:
            if e.status != 404:  # 404 = draft was deleted in Webflow: create a new one
                raise
    if not item_id:
        item_id = webflow.create_draft_item(field_data, **wf)

    sent_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    designer = _designer_url(item_id, client_id, cms)
    designer_line = (
        f"- Designer CMS: {designer}\n"
        if designer
        else (
            "- Designer CMS: (set site short name on this workspace, e.g. arsuno-site, "
            "or WEBFLOW_SITE_SHORT_NAME, to show the Designer link)\n"
        )
    )
    output = (
        "## Draft sent to CMS\n\n"
        f"- Result: {result}\n"
        f"- Title: {post['title']}\n"
        f"- Slug: {post['slug']}\n"
        f"- Webflow item ID: {item_id}\n"
        f"- Collection ID: {collection_id}\n"
        f"{designer_line}"
        f"- Sent at: {sent_at}\n\n"
        f"- Meta title: {meta_title or '(not set, run the Meta Title & Description step)'}\n"
        f"- Meta description: {meta_description or '(not set, run the Meta Title & Description step)'}\n"
        "Open the Designer CMS link to review this draft, then publish it in Webflow. "
        "Running this step again updates the same draft (unless it is already published).\n"
    )
    output = wrap_step_artifact(STEP_NAME, output)
    artifacts.save_artifact(client_id, run_id, STEP_NAME, output)
    logger.info("step complete %s (%s)", STEP_NAME, result)
    return output




# ---------- Publish status + live link (read-only, never changes Webflow) ----------


def _live_url(slug: str, client_id: str = "", cms: dict | None = None) -> str:
    """Live article URL = base + "/" + slug.

    Base = resolve_cms_config live_url_base (workspace meta, else WEBFLOW_LIVE_URL_BASE).
    Returns "" if no base is set.
    """
    if cms is None:
        cms = resolve_cms_config(client_id) if client_id else resolve_cms_config("")
    base = (cms.get("live_url_base") or "").strip().rstrip("/")
    if not base or not slug:
        return ""
    return f"{base}/{slug}"


def _site_short_name(cms: dict) -> str:
    """Configured Designer short name, or look it up once via the Webflow API."""
    configured = (cms.get("site_short_name") or "").strip()
    if configured:
        return configured
    short = webflow.resolve_site_short_name(**_webflow_kwargs(cms))
    return short


def _designer_url(
    item_id: str,
    client_id: str = "",
    cms: dict | None = None,
) -> str:
    """Webflow Designer CMS deep link for this item (review / publish next)."""
    if cms is None:
        cms = resolve_cms_config(client_id) if client_id else resolve_cms_config("")
    short = _site_short_name(cms)
    return webflow.designer_cms_url(
        short,
        collection_id=cms.get("collection_id") or "",
        item_id=item_id,
    )


def fetch_status(client_id: str, run_id: str) -> dict:
    """Ask the configured CMS whether the draft sent by this run has been published.

    Returns {"sent", "status", "live_url", "last_published", "item_id", "slug", "provider"}.
    status: "disabled" | "not_sent" | "draft" | "published" | "changes_in_draft" | "missing".
    Read-only: nothing is changed in the CMS or in the saved artifact.
    """
    cms = resolve_cms_config(client_id)
    provider = normalize_cms_provider(cms.get("provider"))
    if provider == "none":
        return {
            "sent": False,
            "status": "disabled",
            "live_url": "",
            "designer_url": "",
            "last_published": "",
            "item_id": "",
            "slug": "",
            "provider": "none",
        }
    if provider != "webflow":
        raise RuntimeError(f"Unsupported CMS provider {provider!r}.")
    wf = _webflow_kwargs(cms)
    item_id, old_collection_id = _previous_send(client_id, run_id)
    if not item_id:
        return {
            "sent": False,
            "status": "not_sent",
            "live_url": "",
            "designer_url": "",
            "last_published": "",
            "item_id": "",
            "slug": "",
            "provider": "webflow",
        }
    collection = webflow.collection_id(**wf)
    if old_collection_id and old_collection_id != collection:
        raise RuntimeError(
            "This article was sent to a different Webflow collection than the one "
            "configured for this workspace."
        )
    try:
        item = webflow.get_item(item_id, **wf)
    except webflow.WebflowError as e:
        if e.status == 404:  # draft was deleted in Webflow
            return {
                "sent": True,
                "status": "missing",
                "live_url": "",
                "designer_url": "",
                "last_published": "",
                "item_id": item_id,
                "slug": "",
                "provider": "webflow",
            }
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
        "live_url": _live_url(slug, client_id, cms) if last_published else "",
        "designer_url": _designer_url(item_id, client_id, cms),
        "last_published": last_published,
        "item_id": item_id,
        "slug": slug,
        "provider": "webflow",
    }


# ---------- Mark articles already published in Webflow as "Content to CMS: done" ----------

_ITEMS_CACHE: dict[str, dict] = {}  # collection_id → {at, items}
_ITEMS_TTL_SECONDS = 60
_SYNC_AT: dict[str, float] = {}
_SYNC_MIN_SECONDS = 300


def _all_items(cms: dict) -> list[dict]:
    wf = _webflow_kwargs(cms)
    collection = cms.get("collection_id") or ""
    now = time.monotonic()
    cached = _ITEMS_CACHE.get(collection) or {}
    if cached.get("items") and now - cached.get("at", 0) < _ITEMS_TTL_SECONDS:
        return cached["items"]
    items = webflow.list_items(**wf)
    _ITEMS_CACHE[collection] = {"at": now, "items": items}
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
    cms = resolve_cms_config(client_id)
    items = _all_items(cms)
    run_id_field = (cms.get("field_run_id") or "").strip()

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
            "live_url": _live_url(slug, client_id, cms) if item.get("lastPublished") else "",
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
    cms_preview = resolve_cms_config(client_id)
    if normalize_cms_provider(cms_preview.get("provider")) != "webflow":
        return {"skipped": True, "updated": [], "reason": "cms_disabled"}
    matched = published_map(client_id)
    _SYNC_AT[client_id] = now
    cms = resolve_cms_config(client_id)
    collection = cms.get("collection_id") or ""
    updated: list[str] = []
    for run_id, info in matched.items():
        manifest = artifacts.read_run_manifest(client_id, run_id)
        if not manifest:
            continue
        statuses = dict(manifest.get("statuses") or {})
        if statuses.get(STEP_NAME) == "done":
            continue
        if not _previous_send(client_id, run_id)[0]:
            item_id = info.get("item_id") or ""
            designer = _designer_url(item_id, client_id, cms) if item_id else ""
            designer_line = (
                f"- Designer CMS: {designer}\n"
                if designer
                else ""
            )
            body = (
                "## Already published in CMS\n\n"
                "- Result: linked to the item that is already published in Webflow\n"
                f"- Webflow item ID: {item_id}\n"
                f"- Collection ID: {collection}\n"
                f"{designer_line}"
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