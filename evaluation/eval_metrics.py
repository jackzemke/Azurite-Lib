#!/usr/bin/env python3
"""
Evaluation metrics for Project Library.

Compares API responses against ground truth and calculates:
- Citation precision and recall
- Answer relevance (keyword + semantic similarity)
- Per-query-type breakdown
- Mean query latency
"""

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import List, Dict, Optional
import argparse


def calculate_citation_precision(results: List[Dict]) -> float:
    """
    Citation precision: what fraction of returned citations are relevant.

    A citation is relevant if its file path contains at least one expected
    source keyword.
    """
    total_citations = 0
    relevant_citations = 0

    for result in results:
        if "error" in result:
            continue

        expected_sources = result.get("expected_sources", [])
        citations = result.get("citations", [])

        for cit in citations:
            total_citations += 1
            file_path = cit.get("file_path", "").lower()
            if any(kw.lower() in file_path for kw in expected_sources):
                relevant_citations += 1

    return (relevant_citations / total_citations * 100) if total_citations > 0 else 0.0


def calculate_citation_recall(results: List[Dict]) -> float:
    """
    Citation recall: did we find at least one citation matching each expected source?

    For each query, checks if at least one expected source keyword appears
    in any returned citation.
    """
    matched = 0
    total = 0

    for result in results:
        if "error" in result:
            continue

        expected_sources = result.get("expected_sources", [])
        if not expected_sources:
            continue

        total += 1
        citations = result.get("citations", [])
        returned_files = [c.get("file_path", "").lower() for c in citations]

        # At least one expected keyword found in at least one file
        if any(
            any(kw.lower() in f for f in returned_files)
            for kw in expected_sources
        ):
            matched += 1

    return (matched / total * 100) if total > 0 else 0.0


def calculate_answer_relevance(results: List[Dict]) -> float:
    """
    Answer relevance via keyword matching.

    Checks if expected answer keywords appear in the actual answer.
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

        # Multi-word expected answers: check if the full phrase appears
        if " " in expected_answer:
            if expected_answer.lower() in actual_answer.lower():
                relevant += 1
                continue

        # Single-word: check individual keywords
        keywords = expected_answer.lower().split()
        actual_lower = actual_answer.lower()
        if any(kw in actual_lower for kw in keywords):
            relevant += 1

    return (relevant / total * 100) if total > 0 else 0.0


def calculate_exact_value_accuracy(results: List[Dict]) -> float:
    """
    Exact value accuracy for measurement/cost queries.

    Checks if the expected numeric value appears exactly in the answer.
    Only applies to queries with numeric expected answers.
    """
    matched = 0
    total = 0

    for result in results:
        if "error" in result:
            continue

        expected = result.get("expected_answer", "")
        actual = result.get("answer", "")
        query_type = result.get("query_type", "")

        # Only check numeric answers (measurements, costs)
        if query_type not in ("measurement", "cost"):
            continue

        # Extract numbers from expected answer
        import re
        numbers = re.findall(r'\d+\.?\d*', expected)
        if not numbers:
            continue

        total += 1

        # Check if any expected number appears in actual answer
        if any(num in actual for num in numbers):
            matched += 1

    return (matched / total * 100) if total > 0 else 0.0


def calculate_semantic_similarity(results: List[Dict]) -> Optional[float]:
    """
    Semantic similarity between expected and actual answers.

    Uses sentence-transformers to compute cosine similarity.
    Returns None if the model is not available.
    """
    try:
        from sentence_transformers import SentenceTransformer
        import numpy as np
    except ImportError:
        return None

    pairs = []
    for result in results:
        if "error" in result:
            continue
        expected = result.get("expected_answer", "")
        actual = result.get("answer", "")
        if expected and actual:
            pairs.append((expected, actual))

    if not pairs:
        return None

    model = SentenceTransformer("all-MiniLM-L6-v2")

    expected_texts = [p[0] for p in pairs]
    actual_texts = [p[1] for p in pairs]

    expected_embs = model.encode(expected_texts, convert_to_numpy=True)
    actual_embs = model.encode(actual_texts, convert_to_numpy=True)

    # Cosine similarity
    similarities = []
    for e, a in zip(expected_embs, actual_embs):
        cos_sim = np.dot(e, a) / (np.linalg.norm(e) * np.linalg.norm(a) + 1e-8)
        similarities.append(float(cos_sim))

    return sum(similarities) / len(similarities) * 100 if similarities else None


def calculate_mean_latency(results: List[Dict]) -> float:
    """Calculate mean query latency in milliseconds."""
    latencies = [
        result.get("elapsed_ms", 0)
        for result in results
        if "elapsed_ms" in result
    ]
    return sum(latencies) / len(latencies) if latencies else 0.0


def per_type_breakdown(results: List[Dict]) -> Dict[str, Dict]:
    """
    Break down metrics by query_type.

    Returns dict mapping query_type to metrics dict.
    """
    by_type = defaultdict(list)
    for result in results:
        qtype = result.get("query_type", "general")
        by_type[qtype].append(result)

    breakdown = {}
    for qtype, type_results in sorted(by_type.items()):
        breakdown[qtype] = {
            "count": len(type_results),
            "answer_relevance": calculate_answer_relevance(type_results),
            "citation_recall": calculate_citation_recall(type_results),
            "mean_latency_ms": calculate_mean_latency(type_results),
            "errors": sum(1 for r in type_results if "error" in r),
        }

    return breakdown


def generate_report(results_file: Path, use_semantic: bool = False):
    """Generate evaluation report."""
    with open(results_file) as f:
        data = json.load(f)

    results = data.get("results", [])

    citation_precision = calculate_citation_precision(results)
    citation_recall = calculate_citation_recall(results)
    answer_relevance = calculate_answer_relevance(results)
    exact_value_acc = calculate_exact_value_accuracy(results)
    mean_latency = calculate_mean_latency(results)

    print("\n" + "=" * 60)
    print("EVALUATION METRICS")
    print("=" * 60)

    print(f"\nCitation Precision: {citation_precision:.1f}%")
    print(f"  (What fraction of returned citations are relevant)")

    print(f"\nCitation Recall: {citation_recall:.1f}%")
    print(f"  Target: >=75%")
    print(f"  Status: {'PASS' if citation_recall >= 75 else 'FAIL'}")

    print(f"\nAnswer Relevance: {answer_relevance:.1f}%")
    print(f"  (Keyword-based)")

    print(f"\nExact Value Accuracy: {exact_value_acc:.1f}%")
    print(f"  (For measurement/cost queries only)")

    if use_semantic:
        semantic_sim = calculate_semantic_similarity(results)
        if semantic_sim is not None:
            print(f"\nSemantic Similarity: {semantic_sim:.1f}%")
            print(f"  (Cosine similarity of answer embeddings)")
        else:
            print("\nSemantic Similarity: N/A (sentence-transformers not available)")

    print(f"\nMean Query Latency: {mean_latency:.0f}ms")
    print(f"  Target: <2000ms")
    print(f"  Status: {'PASS' if mean_latency < 2000 else 'SLOW'}")

    print(f"\nTotal Queries: {len(results)}")
    print(f"Failed Queries: {sum(1 for r in results if 'error' in r)}")

    # Per-type breakdown
    breakdown = per_type_breakdown(results)
    if breakdown:
        print("\n" + "-" * 60)
        print("PER-QUERY-TYPE BREAKDOWN")
        print("-" * 60)

        for qtype, metrics in breakdown.items():
            print(f"\n  {qtype} ({metrics['count']} queries):")
            print(f"    Answer Relevance: {metrics['answer_relevance']:.1f}%")
            print(f"    Citation Recall:  {metrics['citation_recall']:.1f}%")
            print(f"    Mean Latency:     {metrics['mean_latency_ms']:.0f}ms")
            if metrics["errors"]:
                print(f"    Errors:           {metrics['errors']}")

    # Per-query breakdown
    print("\n" + "-" * 60)
    print("PER-QUERY BREAKDOWN")
    print("-" * 60)

    for i, result in enumerate(results, 1):
        query = result.get("query", "")
        qtype = result.get("query_type", "?")
        print(f"\n[{i}] [{qtype}] {query[:60]}...")

        if "error" in result:
            print(f"  FAIL: {result['error']}")
        else:
            answer = result.get("answer", "")
            citations = result.get("citations", [])
            confidence = result.get("confidence", "unknown")
            elapsed = result.get("elapsed_ms", 0)

            print(f"  Answer: {answer[:80]}...")
            print(f"  Citations: {len(citations)}, Confidence: {confidence}, Latency: {elapsed}ms")

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Calculate evaluation metrics")
    parser.add_argument(
        "--results",
        default="evaluation_results.json",
        help="Path to evaluation results JSON",
    )
    parser.add_argument(
        "--semantic",
        action="store_true",
        help="Enable semantic similarity scoring (requires sentence-transformers)",
    )

    args = parser.parse_args()

    results_file = Path(args.results)
    if not results_file.exists():
        print(f"Results file not found: {results_file}")
        print("Run the evaluation runner first to generate results.")
        return 1

    generate_report(results_file, use_semantic=args.semantic)
    return 0


if __name__ == "__main__":
    sys.exit(main())
