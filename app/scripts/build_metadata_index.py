#!/usr/bin/env python3
"""
CLI script to build/refresh the project metadata index.

Usage:
    python build_metadata_index.py [OPTIONS]

Options:
    --parent-dir PATH       Parent directory containing projects (default: data/raw_docs)
    --output PATH           Output metadata index file (default: data/metadata_index.json)
    --refresh               Force full rebuild (default: incremental if available)
    --verbose               Enable debug logging
"""

import argparse
import logging
import json
import sys
from pathlib import Path

import argparse
import logging
import json
import sys
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

from app.core.metadata_scraper import ProjectMetadataScraper


def setup_logging(verbose: bool = False):
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Build or refresh project metadata index"
    )
    parser.add_argument(
        "--parent-dir",
        default="data/raw_docs",
        help="Parent directory containing projects",
    )
    parser.add_argument(
        "--output",
        default="data/metadata_index.json",
        help="Output metadata index file",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    logger.info(f"Starting metadata scrape...")
    logger.info(f"  Parent directory: {args.parent_dir}")
    logger.info(f"  Output file: {args.output}")

    # Run scraper
    scraper = ProjectMetadataScraper(args.parent_dir, args.output)
    result = scraper.scrape()

    # Print results
    print("\n" + "=" * 70)
    print("METADATA SCRAPE RESULTS")
    print("=" * 70)

    if result["status"] == "completed":
        print(f"✓ Status: COMPLETED")
        print(f"  Projects found: {result['projects_found']}")
        print(f"  Metadata entries: {result['metadata_entries']}")
        print(f"  Duration: {result['extraction_duration_seconds']}s")
        print(f"  Output file: {result['index_saved_to']}")

        if result["errors"]:
            print(f"\n⚠ {len(result['errors'])} errors occurred:")
            for err in result["errors"][:5]:
                print(f"    - {err}")
            if len(result["errors"]) > 5:
                print(f"    ... and {len(result['errors']) - 5} more")

        # Show summary
        with open(args.output) as f:
            index = json.load(f)

        print("\n" + "-" * 70)
        print("PROJECT SUMMARY")
        print("-" * 70)

        for pid, proj in sorted(index["projects"].items()):
            status = "✓" if (proj.get("client") or proj.get("start_date")) else "○"
            print(f"{status} {proj['project_name']:<40} ({pid})")

        return 0
    else:
        print(f"✗ Status: FAILED")
        print(f"  Error: {result.get('error', 'Unknown error')}")
        if result.get("errors"):
            for err in result["errors"][:5]:
                print(f"    - {err}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
