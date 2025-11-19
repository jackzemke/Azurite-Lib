#!/usr/bin/env python3
"""
Evaluation metrics for Project Library.

Compares API responses against ground truth and calculates:
- Citation accuracy
- Answer relevance
- Mean query latency
"""

import json
import sys
from pathlib import Path
from typing import List, Dict
import argparse


def calculate_citation_accuracy(results: List[Dict]) -> float:
    """
    Calculate citation accuracy.
    
    A citation is correct if at least one returned file contains
    an expected source keyword.
    """
    correct = 0
    total = 0
    
    for result in results:
        if "error" in result:
            continue
        
        total += 1
        expected_sources = result.get("expected_sources", [])
        
        if not expected_sources:
            # No ground truth sources, skip
            continue
        
        returned_files = [c["file_path"] for c in result.get("citations", [])]
        
        # Check if any expected keyword appears in any returned file
        match_found = any(
            any(keyword.lower() in file.lower() for keyword in expected_sources)
            for file in returned_files
        )
        
        if match_found:
            correct += 1
    
    return (correct / total * 100) if total > 0 else 0.0


def calculate_answer_relevance(results: List[Dict]) -> float:
    """
    Calculate answer relevance (simple keyword matching).
    
    Checks if expected answer keywords appear in returned answer.
    """
    relevant = 0
    total = 0
    
    for result in results:
        if "error" in result:
            continue
        
        total += 1
        expected_answer = result.get("expected_answer", "")
        actual_answer = result.get("answer", "")
        
        if not expected_answer:
            continue
        
        # Simple keyword matching (case-insensitive)
        keywords = expected_answer.lower().split()
        actual_lower = actual_answer.lower()
        
        if any(kw in actual_lower for kw in keywords):
            relevant += 1
    
    return (relevant / total * 100) if total > 0 else 0.0


def calculate_mean_latency(results: List[Dict]) -> float:
    """Calculate mean query latency in milliseconds."""
    latencies = [
        result.get("elapsed_ms", 0)
        for result in results
        if "elapsed_ms" in result
    ]
    return sum(latencies) / len(latencies) if latencies else 0.0


def generate_report(results_file: Path):
    """Generate evaluation report."""
    with open(results_file) as f:
        data = json.load(f)
    
    results = data.get("results", [])
    
    citation_acc = calculate_citation_accuracy(results)
    answer_relevance = calculate_answer_relevance(results)
    mean_latency = calculate_mean_latency(results)
    
    print("\n" + "="*60)
    print("EVALUATION METRICS")
    print("="*60)
    print(f"\nCitation Accuracy: {citation_acc:.1f}%")
    print(f"  Target: >=75% (85% ideal)")
    print(f"  Status: {'[OK] PASS' if citation_acc >= 75 else '[FAIL] FAIL'}")
    
    print(f"\nAnswer Relevance: {answer_relevance:.1f}%")
    print(f"  (Keyword-based, approximate)")
    
    print(f"\nMean Query Latency: {mean_latency:.0f}ms")
    print(f"  Target: <500ms")
    print(f"  Status: {'[OK] PASS' if mean_latency < 500 else '[FAIL] SLOW'}")
    
    print(f"\nTotal Queries: {len(results)}")
    print(f"Failed Queries: {sum(1 for r in results if 'error' in r)}")
    
    # Per-query breakdown
    print("\n" + "-"*60)
    print("PER-QUERY BREAKDOWN")
    print("-"*60)
    
    for i, result in enumerate(results, 1):
        query = result.get("query", "")
        print(f"\n[{i}] {query[:60]}...")
        
        if "error" in result:
            print(f"  [FAIL] Error: {result['error']}")
        else:
            answer = result.get("answer", "")
            citations = result.get("citations", [])
            confidence = result.get("confidence", "unknown")
            citation_correct = result.get("citation_correct", False)
            
            print(f"  Answer: {answer[:80]}...")
            print(f"  Citations: {len(citations)}, Confidence: {confidence}")
            print(f"  Citation correct: {'[OK]' if citation_correct else '[FAIL]'}")
    
    print("\n" + "="*60)


def main():
    parser = argparse.ArgumentParser(description="Calculate evaluation metrics")
    parser.add_argument(
        "--results",
        default="evaluation_results.json",
        help="Path to evaluation results JSON"
    )
    
    args = parser.parse_args()
    
    results_file = Path(args.results)
    if not results_file.exists():
        print(f"[FAIL] Results file not found: {results_file}")
        print("Run eval_cli.py first to generate results.")
        return 1
    
    generate_report(results_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
