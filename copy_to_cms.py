"""Copy the live MongoDB database to '<name>_cms'. The live DB is only READ.

    python copy_to_cms.py            # copy everything
    python copy_to_cms.py --dry-run  # show what would be copied
"""
import os
import sys

from dotenv import load_dotenv
from pymongo import MongoClient, ReplaceOne

load_dotenv(".env")
dry_run = "--dry-run" in sys.argv

uri = (os.getenv("MONGODB_URI") or "").strip()
db_name = (os.getenv("MONGODB_DB") or "article_generation_pipeline").strip()
if not uri:
    sys.exit("MONGODB_URI is empty in .env")

src_name = db_name[: -len("_cms")] if db_name.endswith("_cms") else db_name
dst_name = src_name + "_cms"

client = MongoClient(uri)
if src_name not in client.list_database_names():
    sys.exit(f"Database '{src_name}' not found on this server.")
src, dst = client[src_name], client[dst_name]
print(f"Copying '{src_name}' (read only) -> '{dst_name}'" + (" [DRY RUN]" if dry_run else ""))

for name in src.list_collection_names():
    if name.startswith("system."):
        continue
    count, batch = 0, []
    for doc in src[name].find():
        count += 1
        batch.append(ReplaceOne({"_id": doc["_id"]}, doc, upsert=True))
        if len(batch) >= 100:
            if not dry_run:
                dst[name].bulk_write(batch)
            batch = []
    if batch and not dry_run:
        dst[name].bulk_write(batch)
    print(f"  {name}: {count} documents")

print("Done." + (" (dry run, nothing written)" if dry_run else ""))