#!/usr/bin/env python3
"""
CLI tool for running evaluation against ground truth.

Usage:
    python eval_cli.py --project proj_demo
    python eval_cli.py --ground-truth ../evaluation/ground_truth.jsonl
"""

import argparse
import sys
import json
from pathlib import Path
import requests

API_URL = "http://127.0.0.1:8000"


def load_ground_truth(file_path: Path):
    """Load ground truth queries."""
    queries = []
    with open(file_path) as f:
        for line in f:
            queries.append(json.loads(line))
    return queries


def run_evaluation(ground_truth_file: Path, project_id: str):
    """Run evaluation against ground truth."""
    print(f"Loading ground truth from: {ground_truth_file}")
    queries = load_ground_truth(ground_truth_file)
    print(f"Loaded {len(queries)} queries\n")
    
    results = []
    correct_citations = 0
    total_queries = len(queries)
    
    for i, item in enumerate(queries, 1):
        query_text = item["query"]
        expected_answer = item.get("expected_answer", "")
        expected_sources = item.get("expected_sources", [])
        
        print(f"[{i}/{total_queries}] Query: {query_text[:50]}...")
        
        try:
            response = requests.post(
                f"{API_URL}/api/v1/query",
                json={
                    "project_id": project_id,
                    "query": query_text,
                    "k": 6,
                }
            )
            response.raise_for_status()
            result = response.json()
            
            # Check if any expected source appears in citations
            returned_files = [c["file_path"] for c in result["citations"]]
            citation_correct = any(
                any(exp in file for exp in expected_sources)
                for file in returned_files
            ) if expected_sources else False
            
            if citation_correct or not expected_sources:
                correct_citations += 1
                status = "[OK]"
            else:
                status = "[FAIL]"
            
            print(f"  {status} Answer: {result['answer'][:80]}...")
            print(f"    Citations: {len(result['citations'])}, Confidence: {result['confidence']}")
            
            results.append({
                "query": query_text,
                "answer": result["answer"],
                "citations": result["citations"],
                "confidence": result["confidence"],
                "expected_sources": expected_sources,
                "citation_correct": citation_correct,
            })
            
        except Exception as e:
            print(f"  [FAIL] Failed: {e}")
            results.append({
                "query": query_text,
                "error": str(e),
                "citation_correct": False,
            })
    
    # Calculate metrics
    citation_accuracy = (correct_citations / total_queries) * 100 if total_queries > 0 else 0
    
    print("\n" + "="*60)
    print("EVALUATION RESULTS")
    print("="*60)
    print(f"Total queries: {total_queries}")
    print(f"Citation accuracy: {citation_accuracy:.1f}%")
    print(f"Target: >=75% (85% ideal)")
    
    if citation_accuracy >= 85:
        print("[OK] EXCELLENT: Exceeds ideal target")
    elif citation_accuracy >= 75:
        print("[OK] GOOD: Meets minimum target")
    else:
        print("[FAIL] NEEDS IMPROVEMENT: Below target")
    
    # Save results
    output_file = Path("evaluation_results.json")
    with open(output_file, 'w') as f:
        json.dump({
            "total_queries": total_queries,
            "citation_accuracy": citation_accuracy,
            "results": results,
        }, f, indent=2)
    
    print(f"\nDetailed results saved to: {output_file}")
    
    return 0 if citation_accuracy >= 75 else 1


def main():
    parser = argparse.ArgumentParser(description="Evaluate Project Library against ground truth")
    parser.add_argument("--project", required=True, help="Project ID")
    parser.add_argument(
        "--ground-truth",
        default="evaluation/ground_truth.jsonl",
        help="Path to ground truth JSONL file"
    )
    parser.add_argument("--api-url", default=API_URL, help="API base URL")
    
    args = parser.parse_args()
    
    global API_URL
    API_URL = args.api_url
    
    ground_truth_file = Path(args.ground_truth)
    if not ground_truth_file.exists():
        print(f"[FAIL] Ground truth file not found: {ground_truth_file}")
        return 1
    
    return run_evaluation(ground_truth_file, args.project)


if __name__ == "__main__":
    sys.exit(main())
