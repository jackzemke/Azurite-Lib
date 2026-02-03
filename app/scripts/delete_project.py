#!/usr/bin/env python3
"""
Delete all data for a project (raw docs, chunks, embeddings, ChromaDB entries).
"""

import sys
import shutil
from pathlib import Path

# Add backend to path
sys.path.insert(0, "/home/jack/lib/project-library/app/backend")


def delete_project(project_id: str, dry_run: bool = False):
    """Delete all project data including ChromaDB entries."""
    base = Path("/home/jack/lib/project-library/data")
    
    paths_to_delete = [
        base / "raw_docs" / project_id,
        base / "chunks" / project_id,
        base / "embeddings" / f"{project_id}.parquet",
        base / "logs" / f"ingest_report_{project_id}.json",
    ]
    
    print(f"\n🗑️  {'[DRY RUN] ' if dry_run else ''}Deleting project: {project_id}")
    print("=" * 60)
    
    # Filesystem cleanup
    for path in paths_to_delete:
        if path.exists():
            if path.is_dir():
                print(f"{'Would remove' if dry_run else 'Removing'} directory: {path}")
                if not dry_run:
                    shutil.rmtree(path)
            else:
                print(f"{'Would remove' if dry_run else 'Removing'} file: {path}")
                if not dry_run:
                    path.unlink()
        else:
            print(f"Skipping (not found): {path}")
    
    # ChromaDB cleanup
    print("\n📊 ChromaDB cleanup:")
    try:
        from app.core.indexer import Indexer
        indexer = Indexer(chroma_db_path=base / "index/chroma")
        
        # Count chunks for this project
        all_data = indexer.collection.get(
            where={"project_id": project_id},
            include=["metadatas"]
        )
        chunk_count = len(all_data["ids"]) if all_data["ids"] else 0
        
        if chunk_count == 0:
            print(f"   No chunks found for project '{project_id}' in ChromaDB")
        else:
            print(f"   Found {chunk_count} chunks for project '{project_id}'")
            if dry_run:
                print(f"   Would delete {chunk_count} chunks from ChromaDB")
            else:
                # Delete by IDs
                indexer.collection.delete(ids=all_data["ids"])
                print(f"   ✓ Deleted {chunk_count} chunks from ChromaDB")
    except Exception as e:
        print(f"   ⚠️  ChromaDB cleanup failed: {e}")
    
    print(f"\n✓ Project '{project_id}' {'would be' if dry_run else ''} deleted\n")


def list_projects():
    """List all projects in filesystem and ChromaDB."""
    base = Path("/home/jack/lib/project-library/data")
    
    print("\n📁 Projects on filesystem (raw_docs):")
    raw_docs = base / "raw_docs"
    for p in sorted(raw_docs.iterdir()):
        if p.is_dir() and not p.name.startswith('.'):
            print(f"   {p.name}")
    
    print("\n📊 Projects in ChromaDB:")
    try:
        from app.core.indexer import Indexer
        from collections import Counter
        indexer = Indexer(chroma_db_path=base / "index/chroma")
        all_data = indexer.collection.get(include=["metadatas"])
        counts = Counter(m.get("project_id", "unknown") for m in all_data["metadatas"])
        for pid, count in sorted(counts.items()):
            print(f"   {pid}: {count} chunks")
    except Exception as e:
        print(f"   ⚠️  Could not read ChromaDB: {e}")
    print()


if __name__ == "__main__":
    if len(sys.argv) == 1 or sys.argv[1] == "--list":
        list_projects()
        print("Usage: python delete_project.py <project_id> [--dry-run]")
        sys.exit(0)
    
    project_id = sys.argv[1]
    dry_run = "--dry-run" in sys.argv
    
    if dry_run:
        delete_project(project_id, dry_run=True)
    else:
        confirm = input(f"Delete ALL data for project '{project_id}'? (yes/no): ")
        if confirm.lower() == 'yes':
            delete_project(project_id)
        else:
            print("Cancelled.")
