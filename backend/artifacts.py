import base64
import binascii
import json
import logging
import os
import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import config
from . import editorial_input
from .pipeline_steps import ARTICLE_STEP_ORDER

logger = logging.getLogger(__name__)


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{threading.get_ident()}.tmp")
    temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temp, path)
    _flush_mongo_path(path)


def _flush_mongo_path(path: Path) -> None:
    try:
        from . import mongo_storage

        mongo_storage.flush_local_path(path)
    except Exception:
        logger.exception("Mongo flush failed for %s", path)


ARTIFACTS_INDEX_FILENAME = "artifacts_index.json"
_MAX_RUN_LOGO_BYTES = 2 * 1024 * 1024
_RUN_LOGO_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})

# Article step order — see `backend/pipeline_steps.py`.
_ARTICLE_STEP_ORDER = ARTICLE_STEP_ORDER

_BUILTIN_SPECS: list[dict[str, str]] = [
    {
        "filename": "personas.md",
        "title": "Audience personas",
        "description": "Who you write for — roles, goals, objections, and vocabulary.",
        "placeholder": "## Primary persona\n- Role:\n- Goals:\n- What they need from this content:\n",
    },
    {
        "filename": "context.md",
        "title": "Company context",
        "description": "Positioning, offerings, and facts the pipeline should treat as ground truth.",
        "placeholder": "## Company overview\n- Company name:\n- What you sell:\n- Key differentiators:\n",
    },
    {
        "filename": "writing_guidelines.md",
        "title": "Writing guidelines",
        "description": "Tone, banned hype, preferred phrasing, and structure expectations.",
        "placeholder": (
            "## Voice\n"
            "- Tone:\n"
            "- Reading level:\n\n"
            "## Format (pipeline-enforced)\n"
            "Sentence case headings, BLUF under every H2/H3, max 30 words per sentence, "
            "max 4 sentences per paragraph, no em dashes, 2–3 inline CTAs at H2 breaks.\n\n"
            "## Avoid\n"
            "- …\n\n"
            "## Preferred words\n"
            "- …\n"
        ),
    },
]

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


def allowed_context_filenames() -> frozenset[str]:
    """Filenames under clients/<id>/context/ that the pipeline may read."""
    names: set[str] = set()
    for flist in config.STEP_CONTEXT_FILES.values():
        names.update(flist)
    return frozenset(names)


def _artifacts_index_path(client_id: str) -> Path:
    return config.CLIENTS_DIR / client_id / "context" / ARTIFACTS_INDEX_FILENAME


def _read_artifacts_index(client_id: str) -> dict:
    path = _artifacts_index_path(client_id)
    if not path.is_file():
        return {"custom": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"custom": []}
    custom = data.get("custom")
    if not isinstance(custom, list):
        custom = []
    return {"custom": custom}


def _write_artifacts_index(client_id: str, index: dict) -> None:
    path = _artifacts_index_path(client_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, indent=2), encoding="utf-8")


def _builtin_specs_by_filename() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for spec in _BUILTIN_SPECS:
        row = dict(spec)
        row["builtin"] = True
        row["removable"] = False
        out[row["filename"]] = row
    for fn in config.pipeline_context_filenames_ordered():
        if fn in out:
            continue
        label = config.CONTEXT_FILE_LABELS.get(fn, fn)
        out[fn] = {
            "filename": fn,
            "title": label,
            "description": f"Pipeline context — {label}.",
            "placeholder": f"# {label}\n",
            "builtin": True,
            "removable": False,
        }
    return out


def workspace_artifact_specs(client_id: str) -> list[dict]:
    """Built-in pipeline context files plus custom entries for this workspace."""
    by_fn = _builtin_specs_by_filename()
    index = _read_artifacts_index(client_id)
    for entry in index.get("custom", []):
        if not isinstance(entry, dict):
            continue
        fn = entry.get("filename")
        if not isinstance(fn, str) or not fn.strip():
            continue
        fn = fn.strip()
        if fn in by_fn:
            continue
        by_fn[fn] = {
            "filename": fn,
            "title": entry.get("title") or fn,
            "description": entry.get("description") or "Custom workspace artifact.",
            "placeholder": entry.get("placeholder")
            or f"# {entry.get('title') or fn}\n",
            "builtin": False,
            "removable": True,
            "custom": True,
        }
    ordered: list[dict] = []
    seen: set[str] = set()
    for fn in config.pipeline_context_filenames_ordered():
        if fn in by_fn:
            ordered.append(by_fn[fn])
            seen.add(fn)
    for spec in _BUILTIN_SPECS:
        fn = spec["filename"]
        if fn not in seen and fn in by_fn:
            ordered.append(by_fn[fn])
            seen.add(fn)
    for fn, spec in sorted(by_fn.items()):
        if fn not in seen:
            ordered.append(spec)
    return ordered


def writable_context_filenames(client_id: str) -> frozenset[str]:
    return frozenset(s["filename"] for s in workspace_artifact_specs(client_id))


def artifact_filename_from_slug(slug: str) -> str:
    raw = (slug or "").strip().lower()
    if raw.endswith(".md"):
        raw = raw[:-3]
    raw = re.sub(r"[^a-z0-9_-]+", "-", raw)
    raw = re.sub(r"-+", "-", raw).strip("-_")
    if not raw or not _SLUG_RE.match(raw):
        raise ValueError(
            "slug must be 1–63 characters: lowercase letters, numbers, hyphens"
        )
    return f"{raw}.md"


def create_custom_workspace_artifact(
    client_id: str,
    *,
    slug: str,
    title: str,
    description: str = "",
    content: str = "",
) -> dict:
    filename = artifact_filename_from_slug(slug)
    if filename in allowed_context_filenames():
        raise ValueError(f"{filename!r} is a reserved pipeline file name")
    title = (title or "").strip()
    if not title:
        raise ValueError("title is required")
    specs = workspace_artifact_specs(client_id)
    if any(s["filename"] == filename for s in specs):
        raise ValueError(f"artifact {filename!r} already exists")

    index = _read_artifacts_index(client_id)
    entry = {
        "filename": filename,
        "title": title,
        "description": (description or "").strip(),
        "created_at": datetime.now().isoformat(),
    }
    index.setdefault("custom", []).append(entry)
    _write_artifacts_index(client_id, index)
    write_context_file(client_id, filename, content or "")
    return {**entry, "builtin": False, "removable": True, "custom": True}


def delete_custom_workspace_artifact(client_id: str, filename: str) -> bool:
    index = _read_artifacts_index(client_id)
    custom = index.get("custom", [])
    kept = [e for e in custom if e.get("filename") != filename]
    if len(kept) == len(custom):
        return False
    index["custom"] = kept
    _write_artifacts_index(client_id, index)
    path = config.CLIENTS_DIR / client_id / "context" / filename
    if path.is_file():
        path.unlink()
    return True


def _context_file_path(client_id: str, filename: str) -> Path:
    if filename not in writable_context_filenames(client_id):
        raise ValueError(f"unknown context file: {filename!r}")
    return config.CLIENTS_DIR / client_id / "context" / filename


def read_context_file(client_id: str, filename: str) -> str | None:
    path = _context_file_path(client_id, filename)
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def write_context_file(client_id: str, filename: str, content: str) -> Path:
    path = _context_file_path(client_id, filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    invalidate_context_cache(client_id)
    return path


def delete_client_workspace(client_id: str) -> bool:
    """Remove clients/<client_id> entirely (context + runs). Returns True if removed."""
    base = config.CLIENTS_DIR / client_id
    if not base.is_dir():
        return False
    shutil.rmtree(base)
    invalidate_context_cache(client_id)
    return True


def get_run_dir(client_id: str, run_id: str) -> Path:
    run_dir = config.CLIENTS_DIR / client_id / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _decode_logo_base64(logo_base64: str) -> bytes:
    raw = (logo_base64 or "").strip()
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        data = base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error) as e:
        raise ValueError("invalid logo image data") from e
    if len(data) > _MAX_RUN_LOGO_BYTES:
        raise ValueError("logo must be 2 MB or smaller")
    return data


def _logo_filename_from_upload(filename: str) -> tuple[str, str]:
    ext = Path(filename or "").suffix.lower()
    if ext not in _RUN_LOGO_EXTS:
        ext = ".png"
    return f"logo{ext}", ext


def save_run_logo_from_base64(
    client_id: str, run_id: str, logo_base64: str, filename: str = ""
) -> str:
    """Decode base64 image and write runs/<run_id>/logo.<ext>. Returns stored filename."""
    data = _decode_logo_base64(logo_base64)
    out_name, _ = _logo_filename_from_upload(filename)
    path = get_run_dir(client_id, run_id) / out_name
    path.write_bytes(data)
    return out_name


def save_client_logo_from_base64(
    client_id: str, logo_base64: str, filename: str = ""
) -> str:
    """Decode base64 image and write clients/<id>/logo.<ext>. Returns stored filename."""
    data = _decode_logo_base64(logo_base64)
    out_name, _ = _logo_filename_from_upload(filename)
    base = config.CLIENTS_DIR / client_id
    base.mkdir(parents=True, exist_ok=True)
    path = base / out_name
    path.write_bytes(data)
    return out_name


def client_logo_path(client_id: str) -> Path | None:
    base = config.CLIENTS_DIR / client_id
    if not base.is_dir():
        return None
    for ext in _RUN_LOGO_EXTS:
        p = base / f"logo{ext}"
        if p.is_file():
            return p
    return None


WORKSPACE_META_FILENAME = "workspace.json"


def workspace_meta_path(client_id: str) -> Path:
    return config.CLIENTS_DIR / client_id / WORKSPACE_META_FILENAME


def read_workspace_meta(client_id: str) -> dict:
    path = workspace_meta_path(client_id)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def write_workspace_meta(client_id: str, meta: dict) -> None:
    path = workspace_meta_path(client_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def workspace_display_name(client_id: str) -> str:
    """Human-readable workspace title (preserves stored display_name when set)."""
    meta = read_workspace_meta(client_id)
    stored = str(meta.get("display_name") or "").strip()
    if stored:
        return stored
    raw = (client_id or "").strip()
    if not raw:
        return client_id or "Workspace"
    parts = re.split(r"[-_\s]+", raw)
    if len(parts) > 1:
        return " ".join(
            (p[:1].upper() + p[1:].lower()) if p else p for p in parts if p
        )
    return raw[:1].upper() + raw[1:] if raw else raw


def set_run_logo_file(client_id: str, run_id: str, logo_file: str) -> None:
    data = ensure_run_manifest(client_id, run_id)
    if not data:
        return
    manifest_path = get_run_dir(client_id, run_id) / "run_manifest.json"
    data["logo_file"] = logo_file
    _write_json_atomic(manifest_path, data)


_STEP_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _validate_step_name(step_name: str) -> str:
    name = str(step_name or "").strip()
    if (
        not name
        or ".." in name
        or "/" in name
        or "\\" in name
        or not _STEP_NAME_RE.match(name)
    ):
        raise ValueError(f"invalid step_name: {step_name!r}")
    return name


def save_artifact(client_id: str, run_id: str, step_name: str, content: str) -> Path:
    from .step_markers import STEP_MARKER_LABELS, ensure_step_markers

    step_name = _validate_step_name(step_name)
    if step_name in STEP_MARKER_LABELS:
        content = ensure_step_markers(step_name, content)
    path = get_run_dir(client_id, run_id) / f"{step_name}.md"
    path.write_text(content, encoding="utf-8")
    logger.info("artifact saved %s", path)
    _flush_mongo_path(path)
    return path


def load_artifact(client_id: str, run_id: str, step_name: str) -> str:
    step_name = _validate_step_name(step_name)
    path = config.CLIENTS_DIR / client_id / "runs" / run_id / f"{step_name}.md"
    if not path.is_file():
        raise FileNotFoundError(
            f"Artifact not found at expected path: {path}"
        )
    return path.read_text(encoding="utf-8")


_context_text_cache: dict[tuple[str, str], tuple[int, str]] = {}


def invalidate_context_cache(client_id: str | None = None) -> None:
    """Drop cached context file text (one client or all)."""
    if client_id is None:
        _context_text_cache.clear()
        return
    doomed = [key for key in _context_text_cache if key[0] == client_id]
    for key in doomed:
        _context_text_cache.pop(key, None)


def _read_context_file_cached(client_id: str, filename: str, path: Path) -> str | None:
    if not path.is_file():
        return None
    mtime_ns = path.stat().st_mtime_ns
    key = (client_id, filename)
    hit = _context_text_cache.get(key)
    if hit and hit[0] == mtime_ns:
        return hit[1]
    text = path.read_text(encoding="utf-8")
    _context_text_cache[key] = (mtime_ns, text)
    return text


def load_context(client_id: str, step_name: str) -> str:
    filenames = config.STEP_CONTEXT_FILES.get(step_name, [])
    if not filenames:
        return ""

    parts: list[str] = []
    context_root = config.CLIENTS_DIR / client_id / "context"

    for filename in filenames:
        path = context_root / filename
        header = f"=== {filename} ==="
        text = _read_context_file_cached(client_id, filename, path)
        if text is not None:
            parts.append(f"{header}\n{text}")
        else:
            parts.append(f"{header} [NOT YET PROVIDED]")

    return "\n\n".join(parts)


def load_context_debug(client_id: str, step_name: str) -> str:
    needed = config.STEP_CONTEXT_FILES.get(step_name, [])
    context_root = config.CLIENTS_DIR / client_id / "context"
    found = [fn for fn in needed if (context_root / fn).is_file()]
    text = load_context(client_id, step_name)
    logger.debug(
        "load_context_debug step=%s needed=%s found=%s chars=%s",
        step_name,
        needed,
        found,
        len(text),
    )
    return text


def _now_iso() -> str:
    return _format_iso_utc(datetime.now(timezone.utc))


def _format_iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _epoch_iso(ts: float) -> str:
    return _format_iso_utc(datetime.fromtimestamp(ts, tz=timezone.utc))


def _parse_iso(ts: str) -> datetime:
    s = str(ts).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        # Naive timestamps are UTC (never server-local wall clock).
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _normalize_step_timing(entry: dict) -> dict:
    if not isinstance(entry, dict):
        return entry
    out = dict(entry)
    for key in ("started_at", "finished_at"):
        raw = out.get(key)
        if isinstance(raw, str) and raw.strip():
            try:
                out[key] = _format_iso_utc(_parse_iso(raw))
            except ValueError:
                pass
    return out


def _duration_ms(started_at: str | None, finished_at: str | None) -> int | None:
    if not started_at or not finished_at:
        return None
    try:
        start = _parse_iso(started_at)
        end = _parse_iso(finished_at)
    except ValueError:
        return None
    delta = int((end - start).total_seconds() * 1000)
    return max(0, delta)


def patch_step_timing(
    timings: dict,
    step_name: str,
    *,
    event: str,
    status: str,
) -> dict:
    """Update an in-memory ``step_timings`` map for a pipeline step."""
    out = dict(timings or {})
    if event == "start":
        out[step_name] = {
            "started_at": _now_iso(),
            "finished_at": None,
            "duration_ms": None,
            "status": "running",
        }
        return out
    entry = dict(out.get(step_name) or {})
    finished_at = _now_iso()
    started_at = entry.get("started_at") or finished_at
    out[step_name] = {
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": _duration_ms(started_at, finished_at),
        "status": status,
    }
    return out


def record_step_started(client_id: str, run_id: str, step_name: str) -> dict:
    manifest = read_run_manifest(client_id, run_id) or {}
    timings = patch_step_timing(
        manifest.get("step_timings") or {}, step_name, event="start", status="running"
    )
    return timings


def record_step_finished(
    client_id: str, run_id: str, step_name: str, status: str
) -> dict:
    manifest = read_run_manifest(client_id, run_id) or {}
    return patch_step_timing(
        manifest.get("step_timings") or {},
        step_name,
        event="finish",
        status=status,
    )


def record_step_cancelled(client_id: str, run_id: str, step_name: str) -> None:
    manifest = read_run_manifest(client_id, run_id)
    if not manifest:
        return
    timings = dict(manifest.get("step_timings") or {})
    timings.pop(step_name, None)
    save_run_manifest(
        client_id,
        run_id,
        manifest.get("topic") or "",
        manifest.get("statuses") or {},
        step_timings=timings,
    )


def infer_step_timings_from_artifacts(
    client_id: str, run_id: str, manifest: dict
) -> dict[str, dict]:
    """Approximate durations for older runs using artifact file mtimes."""
    run_dir = get_run_dir(client_id, run_id)
    if not run_dir.is_dir():
        return {}
    statuses = manifest.get("statuses") or {}
    order = list(statuses.keys()) if isinstance(statuses, dict) and statuses else _ARTICLE_STEP_ORDER
    manifest_path = run_dir / "run_manifest.json"
    prev_ts = (
        manifest_path.stat().st_mtime
        if manifest_path.is_file()
        else run_dir.stat().st_ctime
    )
    inferred: dict[str, dict] = {}
    for name in order:
        path = run_dir / f"{name}.md"
        if not path.is_file():
            continue
        if statuses.get(name) not in ("done", "skipped", "error"):
            continue
        mtime = path.stat().st_mtime
        duration_ms = max(0, int((mtime - prev_ts) * 1000))
        finished_at = _epoch_iso(mtime)
        started_at = _epoch_iso(prev_ts)
        inferred[name] = {
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_ms": duration_ms if duration_ms > 0 else None,
            "status": statuses.get(name) or "done",
            "inferred": True,
        }
        prev_ts = mtime
    return inferred


def step_timings_for_display(client_id: str, run_id: str, manifest: dict) -> dict:
    recorded = manifest.get("step_timings")
    recorded = recorded if isinstance(recorded, dict) else {}
    inferred = infer_step_timings_from_artifacts(client_id, run_id, manifest)
    out: dict[str, dict] = {}
    statuses = manifest.get("statuses") or {}
    order = list(statuses.keys()) if isinstance(statuses, dict) and statuses else _ARTICLE_STEP_ORDER
    for name in order:
        if name in recorded:
            out[name] = _normalize_step_timing(recorded[name])
        elif name in inferred:
            out[name] = _normalize_step_timing(inferred[name])
    return out


def save_run_manifest(
    client_id: str,
    run_id: str,
    topic: str,
    statuses: dict,
    *,
    pipeline_id: str | None = None,
    editorial_source: dict | None = None,
    manual_inputs: dict | None = None,
    target_word_count: int | None = None,
    step_timings: dict | None = None,
    context_summary: str | None = None,
    step_errors: dict | None = None,
) -> None:
    run_dir = get_run_dir(client_id, run_id)
    manifest_path = run_dir / "run_manifest.json"
    prev_manual: dict | None = None
    prev_target_wc: int | None = None
    prev_step_timings: dict | None = None
    prev_archived = False
    prev_archived_at: str | None = None
    prev_context_summary: str | None = None
    prev_step_errors: dict | None = None
    prev: dict = {}
    if manifest_path.is_file():
        try:
            prev = json.loads(manifest_path.read_text(encoding="utf-8"))
            pm = prev.get("manual_inputs")
            prev_manual = pm if isinstance(pm, dict) else None
            ptw = prev.get("target_word_count")
            if isinstance(ptw, int) and ptw > 0:
                prev_target_wc = ptw
            pst = prev.get("step_timings")
            prev_step_timings = pst if isinstance(pst, dict) else None
            prev_archived = bool(prev.get("archived"))
            at = prev.get("archived_at")
            prev_archived_at = at if isinstance(at, str) and at.strip() else None
            pcs = prev.get("context_summary")
            prev_context_summary = pcs if isinstance(pcs, str) and pcs.strip() else None
            pse = prev.get("step_errors")
            prev_step_errors = pse if isinstance(pse, dict) else None
        except json.JSONDecodeError:
            pass

    mi = manual_inputs if manual_inputs is not None else prev_manual

    twc = target_word_count
    if twc is None and mi:
        twc = editorial_input.word_count_from_manual(mi)
    if twc is None:
        twc = prev_target_wc

    payload = {
        "client_id": client_id,
        "run_id": run_id,
        "pipeline_id": (pipeline_id or prev.get("pipeline_id") or "article"),
        "topic": topic,
        "statuses": statuses,
        "timestamp": datetime.now().isoformat(),
        "archived": prev_archived,
    }
    if prev_archived and prev_archived_at:
        payload["archived_at"] = prev_archived_at
    if mi:
        payload["manual_inputs"] = mi
    if twc:
        payload["target_word_count"] = int(twc)
    st = step_timings if step_timings is not None else prev_step_timings
    if st is not None:
        payload["step_timings"] = st
    if editorial_source is not None:
        payload["editorial_source"] = editorial_source
    cs = context_summary if context_summary is not None else prev_context_summary
    if cs:
        payload["context_summary"] = cs
    errors = step_errors if step_errors is not None else prev_step_errors
    if errors:
        payload["step_errors"] = errors
    _write_json_atomic(manifest_path, payload)


def read_run_manifest(client_id: str, run_id: str) -> dict | None:
    manifest_path = get_run_dir(client_id, run_id) / "run_manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _infer_statuses_from_run_dir(run_dir: Path) -> dict[str, str]:
    statuses = {name: "pending" for name in _ARTICLE_STEP_ORDER}
    for name in _ARTICLE_STEP_ORDER:
        if (run_dir / f"{name}.md").is_file():
            statuses[name] = "done"
    return statuses


def _infer_topic_from_run_dir(run_dir: Path) -> str:
    topic_card = run_dir / "topic_card.md"
    if topic_card.is_file():
        try:
            text = topic_card.read_text(encoding="utf-8")
            title = editorial_input.topic_title_from_topic_card_markdown(text)
            if title:
                return title
        except OSError:
            pass
    return "untitled"


def _repair_manifest_topic_if_needed(data: dict, run_dir: Path) -> dict:
    topic = data.get("topic")
    if not editorial_input.is_placeholder_topic_title(
        topic if isinstance(topic, str) else None
    ):
        return data
    inferred = _infer_topic_from_run_dir(run_dir)
    if not editorial_input.is_placeholder_topic_title(inferred):
        data["topic"] = inferred
    return data


def ensure_run_manifest(client_id: str, run_id: str) -> dict | None:
    """Load manifest or create one for legacy runs that only have step files."""
    run_dir = get_run_dir(client_id, run_id)
    if not run_dir.is_dir():
        return None

    manifest_path = run_dir / "run_manifest.json"
    if manifest_path.is_file():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            before = data.get("topic")
            data = _repair_manifest_topic_if_needed(data, run_dir)
            if data.get("topic") != before:
                _write_json_atomic(manifest_path, data)
            return data
        except json.JSONDecodeError:
            logger.warning("Corrupt manifest for %s/%s; rebuilding", client_id, run_id)

    data = {
        "client_id": client_id,
        "run_id": run_id,
        "pipeline_id": "article",
        "topic": _infer_topic_from_run_dir(run_dir),
        "statuses": _infer_statuses_from_run_dir(run_dir),
        "timestamp": datetime.now().isoformat(),
        "archived": False,
    }
    _write_json_atomic(manifest_path, data)
    return data


def set_run_archived(client_id: str, run_id: str, archived: bool = True) -> bool:
    data = ensure_run_manifest(client_id, run_id)
    if not data:
        return False

    manifest_path = get_run_dir(client_id, run_id) / "run_manifest.json"
    data["archived"] = bool(archived)
    if archived:
        data["archived_at"] = datetime.now().isoformat()
    else:
        data.pop("archived_at", None)
    _write_json_atomic(manifest_path, data)
    return True


def delete_run(client_id: str, run_id: str) -> bool:
    run_dir = get_run_dir(client_id, run_id)
    if not run_dir.is_dir():
        return False
    shutil.rmtree(run_dir)
    return True
