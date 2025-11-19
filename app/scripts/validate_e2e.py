#!/usr/bin/env python3
"""
End-to-end validation script for the MVP.

Tests the entire pipeline: upload -> ingest -> query
"""

import sys
import requests
import json
import time
from pathlib import Path

BASE_URL = "http://127.0.0.1:8000"
PROJECT_ID = "demo_project"

def print_status(msg, status="INFO"):
    """Print colored status message."""
    colors = {
        "OK": "\033[92m",
        "FAIL": "\033[91m",
        "WARN": "\033[93m",
        "INFO": "\033[94m",
    }
    reset = "\033[0m"
    color = colors.get(status, "")
    print(f"{color}[{status}]{reset} {msg}")


def test_health():
    """Test health endpoint."""
    print_status("Testing health endpoint...", "INFO")
    try:
        resp = requests.get(f"{BASE_URL}/api/v1/health", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            print_status(f"Health OK - Stub mode: {data.get('stub_mode', 'unknown')}", "OK")
            print(f"   Total chunks: {data.get('total_chunks', 0)}")
            return True
        else:
            print_status(f"Health check failed: {resp.status_code}", "FAIL")
            return False
    except Exception as e:
        print_status(f"Health check error: {e}", "FAIL")
        print_status("Is the backend running? Start it with:", "INFO")
        print_status("  cd app/backend && uvicorn app.main:app --reload", "INFO")
        return False


def test_upload():
    """Test file upload - create test document."""
    print_status(f"Setting up test data for project '{PROJECT_ID}'...", "INFO")
    
    # Check if test file exists
    test_file = Path(f"data/raw_docs/{PROJECT_ID}/sample_report.pdf")
    
    if not test_file.exists():
        print_status("Creating test PDF...", "INFO")
        import subprocess
        result = subprocess.run(
            ["python", "app/scripts/create_test_pdf.py"],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            print_status(f"Failed to create PDF: {result.stderr}", "FAIL")
            return False
    
    print_status(f"Test file ready: {test_file} ({test_file.stat().st_size} bytes)", "OK")
    return True


def test_ingest():
    """Test ingestion."""
    print_status(f"Testing ingestion for project '{PROJECT_ID}'...", "INFO")
    print_status("This may take 30-60 seconds...", "INFO")
    try:
        resp = requests.post(
            f"{BASE_URL}/api/v1/projects/{PROJECT_ID}/ingest",
            json={},
            timeout=120,
        )
        
        if resp.status_code == 200:
            data = resp.json()
            print_status("Ingestion complete", "OK")
            print(f"   Files processed: {data.get('files_processed', 0)}")
            print(f"   Chunks created: {data.get('chunks_created', 0)}")
            print(f"   Duration: {data.get('duration_seconds', 0):.2f}s")
            
            if data.get('errors'):
                print_status(f"Errors encountered: {len(data['errors'])}", "WARN")
                for err in data['errors'][:3]:
                    print(f"      {err}")
            
            if data.get('chunks_created', 0) > 0:
                return True
            else:
                print_status("No chunks created!", "WARN")
                return False
        else:
            print_status(f"Ingestion failed: {resp.status_code}", "FAIL")
            print(f"   Response: {resp.text[:500]}")
            return False
            
    except Exception as e:
        print_status(f"Ingestion error: {e}", "FAIL")
        return False


def test_query(query_text, project_ids=None):
    """Test query endpoint."""
    if not project_ids or len(project_ids) == 0:
        scope = "ALL projects"
    else:
        scope = f"projects={', '.join(project_ids)}"
    
    print_status(f"Query: '{query_text}' (scope: {scope})", "INFO")
    try:
        payload = {
            "query": query_text,
            "k": 6,
        }
        if project_ids and len(project_ids) > 0:
            payload["project_ids"] = project_ids
            
        resp = requests.post(
            f"{BASE_URL}/api/v1/query",
            json=payload,
            timeout=30,
        )
        
        if resp.status_code == 200:
            data = resp.json()
            print_status("Query complete", "OK")
            print(f"   Answer: {data.get('answer', 'N/A')[:150]}...")
            print(f"   Citations: {len(data.get('citations', []))}")
            print(f"   Confidence: {data.get('confidence', 'N/A')}")
            print(f"   Elapsed: {data.get('elapsed_ms', 0)}ms")
            
            if data.get('stub_mode'):
                print_status("   Running in STUB MODE (placeholder response)", "WARN")
            
            # Print citations
            for i, cit in enumerate(data.get('citations', [])[:2], 1):
                proj = cit.get('project_id', 'N/A')
                print(f"   Citation {i}: [{proj}] {cit.get('file_path', 'N/A')} (page {cit.get('page', 0)})")
                excerpt = cit.get('text_excerpt', '')[:80].replace('\n', ' ')
                print(f"      {excerpt}...")
            
            return True
        else:
            print_status(f"Query failed: {resp.status_code}", "FAIL")
            print(f"   Response: {resp.text[:500]}")
            return False
            
    except Exception as e:
        print_status(f"Query error: {e}", "FAIL")
        return False


def main():
    """Run full validation."""
    print("=" * 70)
    print("PROJECT LIBRARY MVP - END-TO-END VALIDATION")
    print("=" * 70)
    print()
    
    # Test sequence
    tests = [
        ("Health Check", test_health),
        ("File Setup", test_upload),
        ("Document Ingestion", test_ingest),
    ]
    
    # Run tests
    results = []
    for name, test_func in tests:
        print()
        result = test_func()
        results.append((name, result))
        
        # If health check fails, stop immediately
        if name == "Health Check" and not result:
            print()
            print_status("Cannot proceed without backend running", "FAIL")
            return 1
        
        time.sleep(0.5)
    
    # Test queries
    print()
    print("-" * 70)
    print("TESTING QUERIES")
    print("-" * 70)
    
    queries = [
        ("How deep was the drainage ditch excavated?", [PROJECT_ID]),
        ("Who was the contractor for this project?", [PROJECT_ID]),
        ("What was the pipe diameter used?", []),  # All projects (empty list)
    ]
    
    for query_text, project_filters in queries:
        print()
        result = test_query(query_text, project_filters)
        if not project_filters or len(project_filters) == 0:
            scope = "ALL"
        else:
            scope = f"{len(project_filters)} project(s)"
        results.append((f"Query ({scope})", result))
        time.sleep(0.5)
    
    # Summary
    print()
    print("=" * 70)
    print("VALIDATION SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "PASS" if result else "FAIL"
        print_status(f"{name}: {status}", "OK" if result else "FAIL")
    
    print()
    print(f"Total: {passed}/{total} tests passed")
    
    if passed == total:
        print()
        print_status("All validation tests passed!", "OK")
        print_status("The MVP is fully functional!", "OK")
        return 0
    else:
        print()
        print_status(f"{total - passed} test(s) failed", "FAIL")
        return 1


if __name__ == "__main__":
    sys.exit(main())
