#!/usr/bin/env python3
"""Debug ChromaDB indexing and querying."""

import sys
from pathlib import Path
sys.path.insert(0, "/home/jack/lib/project-library/app/backend")

from app.core.indexer import Indexer
from app.core.embedder import Embedder

# Initialize
indexer = Indexer(chroma_db_path=Path("/home/jack/lib/project-library/data/index/chroma"))
embedder = Embedder(model_name="sentence-transformers/all-MiniLM-L6-v2")

print(f"Total chunks in ChromaDB: {indexer.collection.count()}")
print()

# Try a simple query
query = "asbestos removal"
print(f"Query: '{query}'")
query_embedding = embedder.model.encode([query])[0].tolist()

results = indexer.query(
    query_embedding=query_embedding,
    project_ids=["proj_demo"],
    top_k=3
)

print(f"Results found: {len(results)}")
if results:
    for i, r in enumerate(results, 1):
        print(f"\n--- Result {i} ---")
        print(f"Chunk ID: {r['chunk_id']}")
        print(f"Text preview: {r['text'][:200]}...")
        print(f"Metadata: {r.get('metadata', {})}")
else:
    print("❌ No results found!")
    print("\nChecking random samples from collection...")
    sample = indexer.collection.peek(limit=3)
    print(f"Sample IDs: {sample['ids'][:3] if sample['ids'] else 'None'}")
    if sample['metadatas']:
        print(f"Sample metadata: {sample['metadatas'][0]}")
