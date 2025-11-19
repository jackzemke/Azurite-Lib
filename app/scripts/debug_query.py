#!/usr/bin/env python3
"""Debug script to check indexer query."""

import sys
sys.path.insert(0, '/home/jack/lib/project-library/app/backend')

from pathlib import Path
import yaml
from app.core.indexer import Indexer
from app.core.embedder import Embedder

# Load config
config_path = Path("/home/jack/lib/project-library/app/backend/config.yaml")
with open(config_path) as f:
    config = yaml.safe_load(f)

# Initialize
embedder = Embedder(model_name=config["embedding"]["model_name"])
indexer = Indexer(chroma_db_path=Path(config["paths"]["chroma_db"]))

# Check collection
print(f"Total chunks in collection: {indexer.collection.count()}")

# Get all items
all_items = indexer.collection.get()
print(f"\nAll IDs: {all_items['ids'][:5] if all_items['ids'] else 'None'}")
print(f"All metadatas: {all_items['metadatas'][:2] if all_items['metadatas'] else 'None'}")

# Test query
query_text = "How deep was the drainage ditch?"
print(f"\nQuery: {query_text}")

query_embedding = embedder.model.encode([query_text])[0].tolist()
print(f"Query embedding size: {len(query_embedding)}")

# Query without filter
results_no_filter = indexer.query(
    query_embedding=query_embedding,
    project_id=None,
    top_k=6,
)
print(f"\nResults WITHOUT filter: {len(results_no_filter)}")
for r in results_no_filter[:2]:
    print(f"  - {r['chunk_id']}: {r['text'][:80]}...")
    print(f"    Distance: {r['distance']}, Project: {r['metadata'].get('project_id')}")

# Query with filter
results_with_filter = indexer.query(
    query_embedding=query_embedding,
    project_id="demo_project",
    top_k=6,
)
print(f"\nResults WITH filter (project=demo_project): {len(results_with_filter)}")
for r in results_with_filter[:2]:
    print(f"  - {r['chunk_id']}: {r['text'][:80]}...")
    print(f"    Distance: {r['distance']}, Project: {r['metadata'].get('project_id')}")
