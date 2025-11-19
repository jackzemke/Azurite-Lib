#!/usr/bin/env python3
"""
CLI tool for ingesting documents.

Usage:
    python ingest_cli.py --project proj_demo
    python ingest_cli.py --project proj_demo --files file1.pdf file2.docx
"""

import argparse
import sys
from pathlib import Path
import requests
import json

API_URL = "http://127.0.0.1:8000"


def ingest_project(project_id: str, files: list = None):
    """Trigger ingestion for a project."""
    url = f"{API_URL}/api/v1/projects/{project_id}/ingest"
    
    payload = {}
    if files:
        payload["files"] = files
    
    print(f"Ingesting project: {project_id}")
    if files:
        print(f"Files: {files}")
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        
        result = response.json()
        print("\n[OK] Ingestion complete!")
        print(f"  Files processed: {result['files_processed']}")
        print(f"  Chunks created: {result['chunks_created']}")
        print(f"  Duration: {result.get('duration_seconds', 0):.2f}s")
        
        if result.get('errors'):
            print(f"\n[WARN] Errors ({len(result['errors'])}):")
            for error in result['errors']:
                print(f"  - {error}")
        
        return 0
        
    except requests.exceptions.RequestException as e:
        print(f"\n[FAIL] Ingestion failed: {e}")
        return 1


def main():
    parser = argparse.ArgumentParser(description="Ingest documents into Project Library")
    parser.add_argument("--project", required=True, help="Project ID")
    parser.add_argument("--files", nargs="*", help="Specific files to ingest (optional)")
    parser.add_argument("--api-url", default=API_URL, help="API base URL")
    
    args = parser.parse_args()
    
    global API_URL
    API_URL = args.api_url
    
    return ingest_project(args.project, args.files)


if __name__ == "__main__":
    sys.exit(main())
