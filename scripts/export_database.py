#!/usr/bin/env python3
"""Export a MongoDB pipeline database to a local folder (read-only).

Downloads the full app_files / GridFS tree from the named database into a
directory on disk. Does not modify MongoDB.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import config  # noqa: E402

ARTICLE_STEP_MARKERS = (
    "topic_card.md",
    "serp_research.md",
    "research.md",
    "assignment_brief.md",
    "outline.md",
    "draft.md",
    "fact_check.md",
    "meta_seo.md",
    "final_output.md",
    "run_manifest.json",
)


def _is_article_run_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if "/runs/" not in normalized:
        return False
    name = Path(normalized).name
    return name in ARTICLE_STEP_MARKERS


def _workspace_support_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    parts = normalized.split("/")
    if len(parts) < 2:
        return False
    if parts[1] == "context":
        return True
    if parts[1] == "runs":
        return _is_article_run_path(normalized)
    return parts[1] in {"logo.png", "workspace.json"}


def export_database(
    *,
    client,
    database: str,
    output: Path,
    article_runs_only: bool = False,
) -> dict[str, int]:
    from gridfs import GridFSBucket

    db = client[database]
    files = db["app_files"]
    bucket = GridFSBucket(db, bucket_name="app_blobs")

    docs = list(files.find({}, {"path": 1, "gridfs_id": 1}))
    if article_runs_only:
        article_workspaces = {
            path.split("/", 1)[0]
            for path in (str(doc.get("path") or "") for doc in docs)
            if _is_article_run_path(path)
        }
        docs = [
            doc
            for doc in docs
            if (
                (path := str(doc.get("path") or ""))
                and path.split("/", 1)[0] in article_workspaces
                and _workspace_support_path(path)
            )
        ]

    output.mkdir(parents=True, exist_ok=True)
    written = 0
    skipped = 0

    for doc in docs:
        rel = str(doc.get("path") or "")
        if not rel or rel.startswith("/") or ".." in Path(rel).parts:
            skipped += 1
            continue
        target = output / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(f".{target.name}.export-tmp")
        stream = bucket.open_download_stream(doc["gridfs_id"])
        with temp.open("wb") as handle:
            while chunk := stream.read(1024 * 1024):
                handle.write(chunk)
        temp.replace(target)
        written += 1

    manifest = {
        "source_database": database,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "files_written": written,
        "files_skipped": skipped,
        "article_runs_only": article_runs_only,
    }
    (output / ".export-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "written": written,
        "skipped": skipped,
        "total_in_db": len(list(files.find({}, {"path": 1}))),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export MongoDB pipeline database files to a local folder."
    )
    parser.add_argument(
        "--database",
        default="post_generation_pipeline",
        help="MongoDB database name to export (default: post_generation_pipeline).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "exports" / "post_generation_pipeline",
        help="Destination directory for exported files.",
    )
    parser.add_argument(
        "--article-runs-only",
        action="store_true",
        help="Export only article-pipeline runs plus each workspace's context/logo.",
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
        "appname": "contentflow-export",
    }
    if config.MONGODB_URI.startswith("mongodb+srv://"):
        options["tlsCAFile"] = certifi.where()

    client = MongoClient(config.MONGODB_URI, **options)
    client.admin.command("ping")

    output = args.output.resolve()
    print(f"Exporting {args.database!r} -> {output}")
    print(f"article_runs_only={args.article_runs_only}")
    result = export_database(
        client=client,
        database=args.database,
        output=output,
        article_runs_only=args.article_runs_only,
    )
    client.close()

    print(
        "Export complete: "
        f"written={result['written']} skipped={result['skipped']} "
        f"total_in_db={result['total_in_db']}"
    )
    print(f"Manifest: {output / '.export-manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
