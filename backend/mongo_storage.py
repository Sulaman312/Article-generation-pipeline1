"""MongoDB/GridFS persistence for the filesystem-oriented client workspace.

The existing pipeline renders images and templates through filesystem APIs. When MongoDB is
enabled, CLIENTS_DIR is a disposable local cache: this module hydrates it on startup and mirrors
mutations back to GridFS after API write requests.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import config

logger = logging.getLogger(__name__)

CACHE_METADATA_FILENAME = ".contentflow-cache.json"

_LOCK = threading.RLock()
_client = None
_db = None
_bucket = None
_files = None
_snapshot: dict[str, tuple[int, int]] = {}
_known_paths: set[str] = set()
_startup_state_lock = threading.Lock()
_startup_thread: threading.Thread | None = None
_startup_state: dict[str, object] = {
    "status": "disabled",
    "attempt": 0,
    "last_error": None,
    "hydrated_files": 0,
}


def enabled() -> bool:
    return bool(config.MONGODB_URI)


def _set_startup_state(
    status: str,
    *,
    attempt: int | None = None,
    last_error: str | None = None,
    hydrated_files: int | None = None,
) -> None:
    with _startup_state_lock:
        _startup_state["status"] = status
        if attempt is not None:
            _startup_state["attempt"] = attempt
        if last_error is not None or status in {"ready", "disabled"}:
            _startup_state["last_error"] = last_error
        if hydrated_files is not None:
            _startup_state["hydrated_files"] = hydrated_files


def startup_status() -> dict[str, object]:
    with _startup_state_lock:
        status = dict(_startup_state)
    status["enabled"] = enabled()
    if not status["enabled"]:
        status["status"] = "disabled"
    return status


def runtime_ready() -> bool:
    if not enabled():
        return True
    return str(startup_status().get("status")) == "ready"


def _cache_metadata_path(root: Path | None = None) -> Path:
    return (root or Path(config.CLIENTS_DIR)) / CACHE_METADATA_FILENAME


def _read_cache_metadata(root: Path | None = None) -> dict[str, Any] | None:
    path = _cache_metadata_path(root)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not read cache metadata from %s", path, exc_info=True)
        return None
    return payload if isinstance(payload, dict) else None


def _write_cache_metadata(root: Path | None = None) -> None:
    path = _cache_metadata_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "database": config.MONGODB_DB,
        "hydrated_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _assert_cache_database_matches(*, root: Path | None = None) -> None:
    """Abort sync/hydration when the on-disk cache belongs to another database."""
    cache_root = root or Path(config.CLIENTS_DIR)
    meta = _read_cache_metadata(cache_root)
    if not meta:
        return
    recorded = str(meta.get("database") or "").strip()
    expected = config.MONGODB_DB
    if recorded and recorded != expected:
        message = (
            f"MongoDB cache at {cache_root} was hydrated from database "
            f"{recorded!r}, but MONGODB_DB is {expected!r}. "
            "Refusing to sync or overwrite the cache."
        )
        logger.error(message)
        raise RuntimeError(message)


def _cache_database_mismatch_error(root: Path | None = None) -> RuntimeError:
    cache_root = root or Path(config.CLIENTS_DIR)
    meta = _read_cache_metadata(cache_root) or {}
    recorded = str(meta.get("database") or "(unknown)").strip()
    expected = config.MONGODB_DB
    message = (
        f"MongoDB cache at {cache_root} was hydrated from database "
        f"{recorded!r}, but MONGODB_DB is {expected!r}. "
        "Refusing to delete the existing cache. "
        "Remove the cache directory manually or point MONGODB_CACHE_DIR "
        "at an empty folder before restarting."
    )
    return RuntimeError(message)


def _reset_connection() -> None:
    global _client, _db, _bucket, _files
    if _client is not None:
        try:
            _client.close()
        except Exception:
            logger.debug("Could not close failed MongoDB client", exc_info=True)
    _client = None
    _db = None
    _bucket = None
    _files = None


def _connect():
    global _client, _db, _bucket, _files
    if not enabled():
        raise RuntimeError("MONGODB_URI is not configured")
    if _client is None:
        try:
            import certifi
            from gridfs import GridFSBucket
            from pymongo import MongoClient
        except ImportError as exc:
            raise RuntimeError(
                "pymongo is required when MONGODB_URI is configured"
            ) from exc

        timeout_ms = int(os.getenv("MONGODB_TIMEOUT_MS") or "10000")
        options = {
            "serverSelectionTimeoutMS": timeout_ms,
            "connectTimeoutMS": timeout_ms,
            "appname": "contentflow",
        }
        if config.MONGODB_URI.startswith("mongodb+srv://"):
            options["tlsCAFile"] = certifi.where()

        candidate = MongoClient(config.MONGODB_URI, **options)
        try:
            candidate.admin.command("ping")
        except Exception:
            candidate.close()
            raise

        _client = candidate
        _db = candidate[config.MONGODB_DB]
        _bucket = GridFSBucket(_db, bucket_name="app_blobs")
        _files = _db["app_files"]
        _files.create_index("path", unique=True)
    return _files, _bucket


def _relative_files(root: Path) -> dict[str, Path]:
    if not root.is_dir():
        return {}
    rows: dict[str, Path] = {}
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            if path.name == CACHE_METADATA_FILENAME:
                continue
            if path.name.startswith(".") and path.name.endswith(".tmp"):
                continue
            rel = path.relative_to(root).as_posix()
            if rel and not rel.startswith("../"):
                rows[rel] = path
    return rows


def _stat_snapshot(rows: dict[str, Path]) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for rel, path in rows.items():
        stat = path.stat()
        out[rel] = (stat.st_size, stat.st_mtime_ns)
    return out


def database_file_count() -> int:
    if not enabled():
        return 0
    files, _ = _connect()
    return int(files.count_documents({}))


def hydrate_cache(*, clear: bool = True) -> int:
    """Replace the runtime cache with the complete file tree stored in MongoDB."""
    global _snapshot, _known_paths
    if not enabled():
        return 0

    with _LOCK:
        files, bucket = _connect()
        root = Path(config.CLIENTS_DIR)
        if root.exists():
            meta = _read_cache_metadata(root)
            if meta:
                recorded = str(meta.get("database") or "").strip()
                if recorded and recorded != config.MONGODB_DB:
                    raise _cache_database_mismatch_error(root)
        docs = list(files.find({}, {"path": 1, "gridfs_id": 1}))
        if clear:
            shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)

        for doc in docs:
            rel = str(doc.get("path") or "")
            if not rel or rel.startswith("/") or ".." in Path(rel).parts:
                logger.warning("Ignoring unsafe MongoDB file path %r", rel)
                continue
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(f".{target.name}.mongo-tmp")
            temp.parent.mkdir(parents=True, exist_ok=True)
            stream = bucket.open_download_stream(doc["gridfs_id"])
            with temp.open("wb") as handle:
                while chunk := stream.read(1024 * 1024):
                    handle.write(chunk)
            os.replace(temp, target)

        rows = _relative_files(root)
        _snapshot = _stat_snapshot(rows)
        _known_paths = set(rows)
        _write_cache_metadata(root)
        logger.info(
            "Hydrated %s files from MongoDB database %s into %s",
            len(rows),
            config.MONGODB_DB,
            root,
        )
        return len(rows)


def _upload_file(rel: str, path: Path, files, bucket) -> None:
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    with path.open("rb") as source:
        new_id = bucket.upload_from_stream(
            rel,
            source,
            metadata={"path": rel, "content_type": content_type},
        )
    previous = files.find_one_and_update(
        {"path": rel},
        {
            "$set": {
                "gridfs_id": new_id,
                "size": path.stat().st_size,
                "content_type": content_type,
                "updated_at": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )
    old_id = previous.get("gridfs_id") if previous else None
    if old_id and old_id != new_id:
        try:
            bucket.delete(old_id)
        except Exception:
            logger.warning("Could not remove superseded GridFS blob %s", old_id)


def sync_cache(*, force: bool = False, delete_missing: bool = False) -> dict[str, int]:
    """Persist changed cache files and known deletions to MongoDB."""
    global _snapshot, _known_paths
    if not enabled():
        return {"uploaded": 0, "deleted": 0, "total": 0}

    with _LOCK:
        root = Path(config.CLIENTS_DIR)
        _assert_cache_database_matches(root=root)
        files, bucket = _connect()
        rows = _relative_files(root)
        current = _stat_snapshot(rows)
        changed = [
            rel
            for rel, stat in current.items()
            if force or _snapshot.get(rel) != stat
        ]
        deleted = sorted(_known_paths - set(rows)) if delete_missing else []

        for rel in changed:
            _upload_file(rel, rows[rel], files, bucket)

        deleted_count = 0
        for rel in deleted:
            doc = files.find_one_and_delete({"path": rel})
            if not doc:
                continue
            deleted_count += 1
            blob_id = doc.get("gridfs_id")
            if blob_id:
                try:
                    bucket.delete(blob_id)
                except Exception:
                    logger.warning("Could not remove GridFS blob %s for %s", blob_id, rel)

        _snapshot = current
        _known_paths.update(rows)
        _known_paths.difference_update(deleted)
        if changed or deleted_count:
            logger.info(
                "MongoDB sync complete: uploaded=%s deleted=%s total_local=%s",
                len(changed),
                deleted_count,
                len(rows),
            )
        return {
            "uploaded": len(changed),
            "deleted": deleted_count,
            "total": len(rows),
        }


def seed_from_directory(
    source: Path,
    *,
    delete_missing: bool = True,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, int]:
    """Upload a source clients tree directly, independent of the runtime cache."""
    if not enabled():
        raise RuntimeError("Set MONGODB_URI before running the seed script")
    source = source.resolve()
    rows = _relative_files(source)

    with _LOCK:
        files, bucket = _connect()
        existing = {str(doc["path"]): doc for doc in files.find({})}
        total = len(rows)
        for index, (rel, path) in enumerate(sorted(rows.items()), start=1):
            _upload_file(rel, path, files, bucket)
            if progress:
                progress(index, total, rel)

        deleted_count = 0
        if delete_missing:
            for rel in sorted(set(existing) - set(rows)):
                doc = files.find_one_and_delete({"path": rel})
                if not doc:
                    continue
                deleted_count += 1
                if doc.get("gridfs_id"):
                    bucket.delete(doc["gridfs_id"])

    return {"uploaded": total, "deleted": deleted_count, "total": total}


def initialize_runtime_cache() -> int:
    """Initialize MongoDB and hydrate CLIENTS_DIR when persistence is enabled."""
    if not enabled():
        _set_startup_state("disabled", attempt=0, last_error=None, hydrated_files=0)
        logger.info("MongoDB persistence disabled; using %s", config.CLIENTS_DIR)
        return 0

    try:
        attempts = max(1, int(os.getenv("MONGODB_STARTUP_ATTEMPTS") or "3"))
        retry_delay = max(0.0, float(os.getenv("MONGODB_RETRY_DELAY_SECONDS") or "2"))
    except ValueError as exc:
        raise RuntimeError("Invalid MongoDB startup retry configuration") from exc

    for attempt in range(1, attempts + 1):
        try:
            root = Path(config.CLIENTS_DIR)
            if root.exists():
                meta = _read_cache_metadata(root)
                if meta:
                    recorded = str(meta.get("database") or "").strip()
                    if recorded and recorded != config.MONGODB_DB:
                        raise _cache_database_mismatch_error(root)
            _set_startup_state("running", attempt=attempt)
            hydrated = hydrate_cache(clear=True)
            _set_startup_state(
                "ready",
                attempt=attempt,
                last_error=None,
                hydrated_files=hydrated,
            )
            return hydrated
        except Exception:
            _reset_connection()
            if attempt == attempts:
                _set_startup_state(
                    "failed",
                    attempt=attempt,
                    last_error="MongoDB startup hydration failed",
                )
                logger.exception(
                    "MongoDB startup hydration failed after %s attempts",
                    attempts,
                )
                raise
            logger.warning(
                "MongoDB startup hydration failed (attempt %s/%s); retrying in %.1fs",
                attempt,
                attempts,
                retry_delay,
                exc_info=True,
            )
            time.sleep(retry_delay)

    raise RuntimeError("MongoDB startup hydration failed")


def initialize_runtime_cache_background() -> None:
    """Start MongoDB hydration in a background thread so web startup is non-blocking."""
    global _startup_thread
    if not enabled():
        initialize_runtime_cache()
        return

    with _startup_state_lock:
        if _startup_thread is not None and _startup_thread.is_alive():
            return
        _startup_state["status"] = "pending"
        _startup_state["attempt"] = 0
        _startup_state["hydrated_files"] = 0
        _startup_state["last_error"] = None

    try:
        retry_delay = max(
            0.0, float(os.getenv("MONGODB_RETRY_DELAY_SECONDS") or "2")
        )
    except ValueError:
        retry_delay = 2.0

    def _worker() -> None:
        attempt = 0
        while True:
            attempt += 1
            _set_startup_state("running", attempt=attempt)
            try:
                hydrated = hydrate_cache(clear=True)
            except Exception as exc:
                _reset_connection()
                detail = f"{type(exc).__name__}: {exc}"
                _set_startup_state("retrying", attempt=attempt, last_error=detail)
                logger.warning(
                    "MongoDB hydration attempt %s failed; retrying in %.1fs",
                    attempt,
                    retry_delay,
                    exc_info=True,
                )
                time.sleep(retry_delay)
                continue

            _set_startup_state(
                "ready",
                attempt=attempt,
                last_error=None,
                hydrated_files=hydrated,
            )
            logger.info(
                "MongoDB hydration complete after %s attempt(s)",
                attempt,
            )
            return

    _startup_thread = threading.Thread(
        target=_worker,
        name="mongodb-hydration",
        daemon=True,
    )
    _startup_thread.start()
