import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(".env")
uri = os.getenv("MONGODB_URI", "").strip()
client = MongoClient(uri, serverSelectionTimeoutMS=8000)
print("Server:", ", ".join(f"{h}:{p}" for h, p in client.nodes))

dbs = client.list_database_names()
for name in ("article_generation_pipeline", "article_generation_pipeline_test_cms"):
    if name not in dbs:
        print(f"\n{name}: NOT FOUND on this server")
        continue
    print(f"\n{name}:")
    for col in sorted(client[name].list_collection_names()):
        print(f"  {col}: {client[name][col].estimated_document_count()} docs")