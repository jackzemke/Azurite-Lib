#!/usr/bin/env python3
"""Direct test of query endpoint logic."""

import sys
sys.path.insert(0, '/home/jack/lib/project-library/app/backend')

from pathlib import Path
import yaml
from app.core.embedder import Embedder
from app.core.indexer import Indexer

# Load config
config_path = Path("/home/jack/lib/project-library/app/backend/config.yaml")
with open(config_path) as f:
    config = yaml.safe_load(f)

print("Simulating query endpoint logic...")
print("=" * 60)

# Initialize components (same as query endpoint)
print("\n1. Initializing Embedder...")
embedder = Embedder(model_name=config["embedding"]["model_name"])
print(f"   Model loaded: {embedder.model}")

print("\n2. Initializing Indexer...")
indexer = Indexer(chroma_db_path=Path(config["paths"]["chroma_db"]))
print(f"   Collection: {indexer.collection.name}")
print(f"   Total chunks: {indexer.collection.count()}")

# Test query (same as query endpoint)
query_text = "excavation depth"
project_id = "demo_project"
k = 6

print(f"\n3. Embedding query: '{query_text}'")
query_embedding = embedder.model.encode([query_text])[0].tolist()
print(f"   Embedding length: {len(query_embedding)}")

print(f"\n4. Querying indexer (project={project_id}, k={k})...")
retrieved_chunks = indexer.query(
    query_embedding=query_embedding,
    project_id=project_id,
    top_k=k,
)

print(f"\n5. Results:")
print(f"   Retrieved chunks: {len(retrieved_chunks)}")

if retrieved_chunks:
    print("\n   First 3 chunks:")
    for i, chunk in enumerate(retrieved_chunks[:3], 1):
        print(f"   [{i}] {chunk['chunk_id']}")
        print(f"       Text: {chunk['text'][:80]}...")
        print(f"       Distance: {chunk.get('distance', 'N/A')}")
        print(f"       Project: {chunk['metadata'].get('project_id', 'N/A')}")
else:
    print("   NO CHUNKS RETURNED!")
    print("   This is the bug!")

print("\n" + "=" * 60)
print("This should match what the API returns.")
