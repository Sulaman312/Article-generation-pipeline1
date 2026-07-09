#!/usr/bin/env python3
"""Read-only audit of MongoDB workspace storage across pipeline databases.

Connects to the cluster configured in `.env` and prints collection counts plus
per-workspace file counts for both `article_generation_pipeline` and
`post_generation_pipeline`. When both databases are audited, also compares path
sets and `updated_at` timestamps. No writes or deletes.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import config  # noqa: E402

DEFAULT_DATABASES = (
    "article_generation_pipeline",
    "post_generation_pipeline",
)


def _workspace_prefix(path: str) -> str:
    """First path segment of an app_files.path value (workspace id)."""
    path = (path or "").strip().replace("\\", "/")
    if not path:
        return "(empty)"
    return path.split("/", 1)[0] or "(empty)"


def _normalize_updated_at(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_app_files_index(client, db_name: str) -> dict[str, datetime | None]:
    """Read-only map of app_files.path -> updated_at for one database."""
    db = client[db_name]
    rows: dict[str, datetime | None] = {}
    for doc in db["app_files"].find({}, {"path": 1, "updated_at": 1}):
        path = str(doc.get("path") or "").strip()
        if not path:
            continue
        rows[path] = _normalize_updated_at(doc.get("updated_at"))
    return rows


def audit_database(client, db_name: str) -> dict:
    """Return read-only stats for one database."""
    db = client[db_name]
    app_files = db["app_files"]
    blob_files = db["app_blobs.files"]

    index = load_app_files_index(client, db_name)
    by_workspace = Counter(_workspace_prefix(p) for p in index)

    return {
        "database": db_name,
        "app_files": app_files.count_documents({}),
        "app_blobs.files": blob_files.count_documents({}),
        "workspaces": dict(sorted(by_workspace.items(), key=lambda item: (-item[1], item[0]))),
        "index": index,
    }


def print_cross_database_comparison(article: dict, post: dict) -> None:
    article_paths = set(article["index"])
    post_paths = set(post["index"])

    print("=== cross-database comparison ===")
    print(f"article paths: {len(article_paths)}")
    print(f"post paths:    {len(post_paths)}")
    print(f"shared paths:  {len(article_paths & post_paths)}")
    print()

    if article_paths <= post_paths:
        print("Superset check: post_generation_pipeline IS a strict superset of article_generation_pipeline by path.")
        if article_paths == post_paths:
            print("  (path sets are identical)")
        else:
            print(f"  post-only paths: {len(post_paths - article_paths)}")
    elif post_paths <= article_paths:
        print("Superset check: article_generation_pipeline IS a strict superset of post_generation_pipeline by path.")
        print(f"  article-only paths: {len(article_paths - post_paths)}")
    else:
        print("Superset check: NEITHER database is a strict superset of the other — path sets diverge.")
        print(f"  article-only paths: {len(article_paths - post_paths)}")
        print(f"  post-only paths:    {len(post_paths - article_paths)}")
    print()

    article_only = sorted(article_paths - post_paths)
    print(f"Paths present in article_generation_pipeline but absent from post_generation_pipeline ({len(article_only)}):")
    if not article_only:
        print("  (none)")
    else:
        for path in article_only:
            updated = article["index"][path]
            print(f"  {path}\tupdated_at={updated}")
    print()

    newer_in_article = []
    for path in sorted(article_paths & post_paths):
        article_ts = article["index"][path]
        post_ts = post["index"][path]
        if article_ts is None or post_ts is None:
            continue
        if article_ts > post_ts:
            newer_in_article.append((path, article_ts, post_ts))

    print(
        "Shared paths where updated_at is NEWER in article_generation_pipeline "
        f"than in post_generation_pipeline ({len(newer_in_article)}):"
    )
    if not newer_in_article:
        print("  (none)")
    else:
        for path, article_ts, post_ts in newer_in_article:
            print(f"  {path}")
            print(f"    article: {article_ts.isoformat()}")
            print(f"    post:    {post_ts.isoformat()}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only MongoDB audit for pipeline databases."
    )
    parser.add_argument(
        "--databases",
        nargs="+",
        default=list(DEFAULT_DATABASES),
        help="Database names to audit (default: both pipeline databases).",
    )
    args = parser.parse_args()

    if not config.MONGODB_URI:
        parser.error("MONGODB_URI is not set in the environment / .env")

    try:
        import certifi
        from pymongo import MongoClient
    except ImportError as exc:
        parser.error(f"pymongo is required: {exc}")

    options = {
        "serverSelectionTimeoutMS": int(
            __import__("os").getenv("MONGODB_TIMEOUT_MS") or "15000"
        ),
        "connectTimeoutMS": int(
            __import__("os").getenv("MONGODB_TIMEOUT_MS") or "15000"
        ),
        "appname": "contentflow-audit",
    }
    if config.MONGODB_URI.startswith("mongodb+srv://"):
        options["tlsCAFile"] = certifi.where()

    client = MongoClient(config.MONGODB_URI, **options)
    client.admin.command("ping")

    host = client.address[0] if client.address else "unknown"
    print(f"Cluster host: {host}")
    print(f"MONGODB_URI configured: yes")
    print(f"config.MONGODB_DB (runtime default): {config.MONGODB_DB!r}")
    print()

    audits: dict[str, dict] = {}
    for db_name in args.databases:
        stats = audit_database(client, db_name)
        audits[db_name] = stats
        print(f"=== {stats['database']} ===")
        print(f"app_files:        {stats['app_files']}")
        print(f"app_blobs.files:  {stats['app_blobs.files']}")
        print("By workspace prefix:")
        if not stats["workspaces"]:
            print("  (no files)")
        else:
            for workspace, count in stats["workspaces"].items():
                print(f"  {workspace}: {count}")
        print()

    article_name = "article_generation_pipeline"
    post_name = "post_generation_pipeline"
    if article_name in audits and post_name in audits:
        print_cross_database_comparison(audits[article_name], audits[post_name])

    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
