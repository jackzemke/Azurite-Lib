#!/usr/bin/env python3
"""
Delete all data for a project (raw docs, chunks, embeddings, ChromaDB entries).
"""

import sys
import shutil
from pathlib import Path

def delete_project(project_id: str):
    """Delete all project data."""
    base = Path("/home/jack/lib/project-library/data")
    
    paths_to_delete = [
        base / "raw_docs" / project_id,
        base / "chunks" / project_id,
        base / "embeddings" / f"{project_id}.parquet",
    ]
    
    print(f"\n🗑️  Deleting project: {project_id}")
    print("=" * 60)
    
    for path in paths_to_delete:
        if path.exists():
            if path.is_dir():
                print(f"Removing directory: {path}")
                shutil.rmtree(path)
            else:
                print(f"Removing file: {path}")
                path.unlink()
        else:
            print(f"Skipping (not found): {path}")
    
    # ChromaDB - need to delete from collection
    print("\n⚠️  ChromaDB entries:")
    print("   To delete from ChromaDB, restart backend and run:")
    print(f"   DELETE FROM embeddings WHERE metadata->>'project_id' = '{project_id}';")
    print("   OR delete the entire ChromaDB and re-ingest all projects:")
    print(f"   rm -rf {base / 'index/chroma'}")
    
    print(f"\n✓ Project {project_id} data deleted from filesystem")
    print("   Restart backend to clear ChromaDB entries\n")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python delete_project.py <project_id>")
        print("Example: python delete_project.py proj_demo")
        sys.exit(1)
    
    project_id = sys.argv[1]
    confirm = input(f"Delete ALL data for project '{project_id}'? (yes/no): ")
    
    if confirm.lower() == 'yes':
        delete_project(project_id)
    else:
        print("Cancelled.")
