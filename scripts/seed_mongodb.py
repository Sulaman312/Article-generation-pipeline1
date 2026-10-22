#!/usr/bin/env python3
"""Seed MongoDB/GridFS from the repository's current clients directory."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import config, mongo_storage  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mirror the local clients/ tree into MongoDB GridFS."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "clients",
        help="Clients directory to upload (default: repository clients/)",
    )
    parser.add_argument(
        "--keep-extra",
        action="store_true",
        help="Do not delete database files that are absent from the source tree.",
    )
    args = parser.parse_args()

    if not config.MONGODB_URI:
        parser.error("MONGODB_URI is not set")
    source = args.source.resolve()
    if not source.is_dir():
        parser.error(f"source directory does not exist: {source}")

    def progress(index: int, total: int, relative_path: str) -> None:
        print(f"[{index}/{total}] {relative_path}", flush=True)

    print(
        f"Seeding {source} into MongoDB database {config.MONGODB_DB!r}...",
        flush=True,
    )
    result = mongo_storage.seed_from_directory(
        source,
        delete_missing=not args.keep_extra,
        progress=progress,
    )
    print(
        "Seed complete: "
        f"uploaded={result['uploaded']} deleted={result['deleted']} "
        f"total={result['total']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
