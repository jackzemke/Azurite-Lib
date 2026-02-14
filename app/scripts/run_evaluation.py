#!/usr/bin/env python3
"""
Automated end-to-end evaluation runner.

Reads ground truth queries, sends them to the API,
collects responses, and runs metrics.

Usage:
    python -m app.scripts.run_evaluation
    python -m app.scripts.run_evaluation --base-url http://localhost:8000 --project demo_project
    python -m app.scripts.run_evaluation --semantic
"""

import argparse
import json
import sys
import time
from pathlib import Path

try:
    import httpx
except ImportError:
    print("httpx is required: pip install httpx")
    sys.exit(1)

# Add project root to path for eval_metrics import
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.eval_metrics import generate_report


def load_ground_truth(gt_path: Path) -> list[dict]:
    """Load ground truth queries from JSONL file."""
    queries = []
    with open(gt_path) as f:
        for line in f:
            line = line.strip()
            if line:
                queries.append(json.loads(line))
    return queries


def run_query(
    client: httpx.Client,
    base_url: str,
    query: str,
    project_ids: list[str] | None = None,
) -> dict:
    """Send a query to the API and return the response."""
    payload = {
        "query": query,
        "project_ids": project_ids,
        "k": 6,
    }

    try:
        resp = client.post(f"{base_url}/query", json=payload, timeout=30.0)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Run end-to-end evaluation")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="API base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--project",
        type=str,
        help="Filter queries to a specific project",
    )
    parser.add_argument(
        "--ground-truth",
        default=str(PROJECT_ROOT / "evaluation" / "ground_truth.jsonl"),
        help="Path to ground truth JSONL",
    )
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "evaluation" / "evaluation_results.json"),
        help="Path to save results JSON",
    )
    parser.add_argument(
        "--semantic",
        action="store_true",
        help="Enable semantic similarity in metrics",
    )
    args = parser.parse_args()

    gt_path = Path(args.ground_truth)
    if not gt_path.exists():
        print(f"Ground truth file not found: {gt_path}")
        return 1

    queries = load_ground_truth(gt_path)
    print(f"Loaded {len(queries)} ground truth queries from {gt_path}")

    # Check API health
    client = httpx.Client()
    try:
        health = client.get(f"{args.base_url}/health", timeout=5.0)
        health.raise_for_status()
        print(f"API is healthy: {health.json().get('models_loaded', '?')}")
    except Exception as e:
        print(f"API health check failed: {e}")
        print(f"Ensure the API is running at {args.base_url}")
        return 1

    # Run queries
    results = []
    project_ids = [args.project] if args.project else None
    total_start = time.time()

    for i, gt in enumerate(queries, 1):
        query = gt["query"]
        print(f"[{i}/{len(queries)}] {query[:60]}...", end=" ", flush=True)

        start = time.time()
        response = run_query(client, args.base_url, query, project_ids)
        elapsed = int((time.time() - start) * 1000)

        if "error" in response:
            print(f"ERROR ({elapsed}ms)")
            result = {
                "query": query,
                "query_type": gt.get("query_type", "general"),
                "expected_answer": gt.get("expected_answer", ""),
                "expected_sources": gt.get("expected_sources", []),
                "error": response["error"],
                "elapsed_ms": elapsed,
            }
        else:
            confidence = response.get("confidence", "?")
            n_citations = len(response.get("citations", []))
            print(f"OK ({elapsed}ms, {confidence}, {n_citations} citations)")
            result = {
                "query": query,
                "query_type": gt.get("query_type", "general"),
                "expected_answer": gt.get("expected_answer", ""),
                "expected_sources": gt.get("expected_sources", []),
                "answer": response.get("answer", ""),
                "citations": response.get("citations", []),
                "confidence": confidence,
                "elapsed_ms": response.get("elapsed_ms", elapsed),
            }

        results.append(result)

    total_elapsed = time.time() - total_start
    client.close()

    # Save results
    output_path = Path(args.output)
    output_data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "base_url": args.base_url,
        "project_filter": args.project,
        "total_queries": len(results),
        "total_elapsed_seconds": round(total_elapsed, 2),
        "results": results,
    }
    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)
    print(f"\nResults saved to {output_path}")

    # Generate metrics report
    generate_report(output_path, use_semantic=args.semantic)

    return 0


if __name__ == "__main__":
    sys.exit(main())
