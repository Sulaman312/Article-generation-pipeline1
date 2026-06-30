"""MongoDB/GridFS persistence for the filesystem-oriented client workspace.

The existing pipeline renders images and templates through filesystem APIs. When MongoDB is
enabled, CLIENTS_DIR is a disposable local cache: this module hydrates it on startup and mirrors
mutations back to GridFS after API write requests.
"""

from __future__ import annotations

import logging
import mimetypes
import os
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import config

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()
_client = None
_db = None
_bucket = None
_files = None
_snapshot: dict[str, tuple[int, int]] = {}
_known_paths: set[str] = set()


def enabled() -> bool:
    return bool(config.MONGODB_URI)


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
        docs = list(files.find({}, {"path": 1, "gridfs_id": 1}))
        root = Path(config.CLIENTS_DIR)
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
            stream = bucket.open_download_stream(doc["gridfs_id"])
            with temp.open("wb") as handle:
                while chunk := stream.read(1024 * 1024):
                    handle.write(chunk)
            os.replace(temp, target)

        rows = _relative_files(root)
        _snapshot = _stat_snapshot(rows)
        _known_paths = set(rows)
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


def sync_cache(*, force: bool = False, delete_missing: bool = True) -> dict[str, int]:
    """Persist changed cache files and known deletions to MongoDB."""
    global _snapshot, _known_paths
    if not enabled():
        return {"uploaded": 0, "deleted": 0, "total": 0}

    with _LOCK:
        files, bucket = _connect()
        root = Path(config.CLIENTS_DIR)
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
        logger.info("MongoDB persistence disabled; using %s", config.CLIENTS_DIR)
        return 0

    try:
        attempts = max(1, int(os.getenv("MONGODB_STARTUP_ATTEMPTS") or "3"))
        retry_delay = max(0.0, float(os.getenv("MONGODB_RETRY_DELAY_SECONDS") or "2"))
    except ValueError as exc:
        raise RuntimeError("Invalid MongoDB startup retry configuration") from exc

    for attempt in range(1, attempts + 1):
        try:
            return hydrate_cache(clear=True)
        except Exception:
            _reset_connection()
            if attempt == attempts:
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
